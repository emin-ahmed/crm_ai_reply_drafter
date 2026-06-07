# Part of the crm_ai_reply_drafter module. See LICENSE file for details.
"""Streaming endpoint for the AI Reply Drafter.

Streams the LLM draft to the browser as Server-Sent Events (SSE) so the OWL
component can show it live. The draft, token usage and a log entry are persisted
when the stream completes.

Odoo closes the request-bound cursor before the WSGI server lazily consumes a
streaming generator, so this controller is careful to:

* do everything that needs the request cursor (load records, read config,
  build the prompt) up front, while the cursor is alive;
* stream the provider's network response without touching the ORM;
* open a *fresh* cursor inside the generator for the final write + log.
"""
import json
import logging

from odoo import api, http
from odoo.http import request
from odoo.modules.registry import Registry

from ..services.providers import estimate_cost

_logger = logging.getLogger(__name__)


def _sse(event, payload):
    """Format one Server-Sent Event frame.

    JSON-encoding the payload keeps it on a single ``data:`` line even when the
    chunk contains newlines.
    """
    return "event: %s\ndata: %s\n\n" % (event, json.dumps(payload))


class AiReplyController(http.Controller):

    @http.route('/crm_ai_reply_drafter/stream', type='http', auth='user',
                methods=['GET'], csrf=False)
    def stream_reply(self, wizard_id=None, **kwargs):
        """Stream a draft reply for the given wizard as SSE."""
        wizard = request.env['crm.ai.reply.wizard'].browse(int(wizard_id)).exists()
        if not wizard:
            return request.not_found()
        wizard.check_access('read')

        service = request.env['crm.ai.reply.service']
        # Build everything that needs the cursor now, before streaming begins.
        try:
            provider, system, user_content = service.prepare(wizard.lead_id)
        except Exception as exc:  # config / key / dependency errors
            _logger.warning("AI reply preparation failed: %s", exc)
            return self._error_response(
                wizard.id, 'anthropic', '', str(exc))

        provider_key = provider.key
        model = provider.model
        # Capture the request identity so the generator can open its own cursor.
        dbname = request.env.cr.dbname
        uid = request.env.uid
        context = dict(request.env.context)
        lead_id = wizard.lead_id.id
        wizard_id = wizard.id

        def generate():
            chunks = []
            try:
                for text in provider.stream(system, user_content):
                    chunks.append(text)
                    yield _sse('chunk', {'text': text})
            except Exception as exc:  # noqa: BLE001 - report any failure to UI
                _logger.exception("AI reply streaming failed")
                self._persist(dbname, uid, context, wizard_id, lead_id,
                              provider_key, model, provider.usage,
                              ''.join(chunks), status='error',
                              error=str(exc))
                yield _sse('error', {'message': str(exc)})
                return

            draft = ''.join(chunks).strip()
            self._persist(dbname, uid, context, wizard_id, lead_id,
                          provider_key, model, provider.usage, draft,
                          status='success')
            yield _sse('done', {
                'input_tokens': provider.usage.get('input_tokens', 0),
                'output_tokens': provider.usage.get('output_tokens', 0),
            })

        headers = [
            ('Content-Type', 'text/event-stream'),
            ('Cache-Control', 'no-cache'),
            ('X-Accel-Buffering', 'no'),  # disable proxy buffering (nginx)
        ]
        return request.make_response(generate(), headers=headers)

    def _persist(self, dbname, uid, context, wizard_id, lead_id, provider_key,
                 model, usage, draft, status='success', error=False):
        """Write the result to the wizard and create a log, in a fresh cursor."""
        try:
            with Registry(dbname).cursor() as cr:
                env = api.Environment(cr, uid, context)
                lead = env['crm.lead'].browse(lead_id).exists()
                # The wizard's state field uses streaming/done/error; map the
                # generation status (success/error) onto it. Writing 'success'
                # would raise (invalid selection) and skip the log below.
                vals = {'state': 'done' if status == 'success' else 'error'}
                if status == 'success':
                    vals.update({
                        'generated_draft': draft,
                        'input_tokens': usage.get('input_tokens', 0),
                        'output_tokens': usage.get('output_tokens', 0),
                        'cost_estimate': estimate_cost(
                            provider_key, model,
                            usage.get('input_tokens', 0),
                            usage.get('output_tokens', 0)),
                    })
                else:
                    vals['error_message'] = error
                # Create the audit log first so it is never lost if the wizard
                # write has an issue.
                env['crm.ai.reply.service'].log_generation(
                    lead, provider_key, model, usage, draft,
                    status=status, error_message=error)
                wizard = env['crm.ai.reply.wizard'].browse(wizard_id).exists()
                if wizard:
                    wizard.write(vals)
                cr.commit()
        except Exception:  # noqa: BLE001
            _logger.exception("Failed to persist AI reply result")

    def _error_response(self, wizard_id, provider_key, model, message):
        """Return a one-frame SSE error stream for pre-stream failures."""
        def gen():
            yield _sse('error', {'message': message})
        headers = [
            ('Content-Type', 'text/event-stream'),
            ('Cache-Control', 'no-cache'),
        ]
        # Mark the wizard as failed so the form reflects it on reload.
        try:
            request.env['crm.ai.reply.wizard'].browse(wizard_id).sudo().write({
                'state': 'error', 'error_message': message})
        except Exception:  # noqa: BLE001
            pass
        return request.make_response(gen(), headers=headers)
