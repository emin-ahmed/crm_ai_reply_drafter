# Part of the crm_ai_reply_drafter module. See LICENSE file for details.
"""Service layer for the AI Reply Drafter.

An :class:`~odoo.models.AbstractModel` so it is reachable as
``env['crm.ai.reply.service']`` from controllers, wizards and tests, while the
heavy lifting (provider clients, prompt assembly) stays in plain Python modules
that are easy to mock.
"""
import logging

from odoo import _, api, models
from odoo.exceptions import UserError

from . import providers
from .prompt_builder import build_user_content

_logger = logging.getLogger(__name__)


class AiReplyService(models.AbstractModel):
    _name = 'crm.ai.reply.service'
    _description = 'AI Reply Drafter Service'

    @api.model
    def _get_config(self):
        """Read the effective configuration from system parameters.

        :returns: dict with provider, model, api_key, base_url, system_prompt,
            max_messages.
        :rtype: dict
        """
        get_param = self.env['ir.config_parameter'].sudo().get_param
        provider = get_param('crm_ai_reply_drafter.provider', 'anthropic')
        keys = {
            'anthropic': 'crm_ai_reply_drafter.anthropic_api_key',
            'openai': 'crm_ai_reply_drafter.openai_api_key',
        }
        # base_url is provider-specific: Ollama's local server, or an optional
        # OpenAI-compatible endpoint (e.g. OpenRouter). Anthropic uses its own.
        if provider == 'ollama':
            base_url = get_param('crm_ai_reply_drafter.ollama_base_url') or \
                'http://localhost:11434'
        elif provider == 'openai':
            base_url = get_param('crm_ai_reply_drafter.openai_base_url') or False
        else:
            base_url = False
        return {
            'provider': provider,
            'model': get_param('crm_ai_reply_drafter.model') or
            providers.DEFAULT_MODELS.get(provider),
            'api_key': get_param(keys.get(provider, '')) or False,
            'base_url': base_url,
            'system_prompt': get_param('crm_ai_reply_drafter.system_prompt') or '',
            'max_messages': int(
                get_param('crm_ai_reply_drafter.max_context_messages') or 20),
        }

    @api.model
    def _get_provider(self, config=None):
        """Instantiate the configured provider client."""
        config = config or self._get_config()
        return providers.get_provider(
            config['provider'],
            model=config['model'],
            api_key=config['api_key'],
            base_url=config['base_url'],
        )

    @api.model
    def build_prompt(self, lead):
        """Return ``(system_prompt, user_content)`` for a lead.

        :param lead: a single ``crm.lead`` record
        :rtype: tuple(str, str)
        """
        lead.ensure_one()
        config = self._get_config()
        user_content = build_user_content(lead, config['max_messages'])
        return config['system_prompt'], user_content

    @api.model
    def stream_reply(self, lead):
        """Yield draft text chunks for a lead, then expose usage.

        The returned generator yields ``str`` chunks. Once exhausted, read the
        token usage from the provider via :meth:`finalize` (the caller keeps a
        reference to the provider through :meth:`prepare`).

        Most callers should use :meth:`prepare` directly for finer control.
        """
        provider, system, user_content = self.prepare(lead)
        yield from provider.stream(system, user_content)

    @api.model
    def prepare(self, lead):
        """Build everything needed to stream a reply.

        :returns: ``(provider, system_prompt, user_content)``. The caller drives
            ``provider.stream(system, user)`` and afterwards reads
            ``provider.usage`` and calls :meth:`log_generation`.
        """
        lead.ensure_one()
        config = self._get_config()
        if config['provider'] in ('anthropic', 'openai') and not config['api_key']:
            raise UserError(_(
                "No API key configured for the %s provider. Set it in "
                "Settings → AI Reply Drafter.", config['provider']))
        provider = self._get_provider(config)
        user_content = build_user_content(lead, config['max_messages'])
        return provider, config['system_prompt'], user_content

    @api.model
    def log_generation(self, lead, provider_key, model, usage, draft,
                       status='success', error_message=False):
        """Record one generation in the log model and return the record.

        :param lead: the ``crm.lead`` (may be empty for a failed lookup)
        :param str provider_key: provider used
        :param str model: model used
        :param dict usage: ``{'input_tokens', 'output_tokens'}``
        :param str draft: the generated text
        :param str status: ``'success'`` or ``'error'``
        :param str error_message: error text when status is ``'error'``
        :rtype: recordset of ``crm.ai.reply.log``
        """
        usage = usage or {}
        input_tokens = usage.get('input_tokens', 0)
        output_tokens = usage.get('output_tokens', 0)
        cost = providers.estimate_cost(
            provider_key, model, input_tokens, output_tokens)
        return self.env['crm.ai.reply.log'].sudo().create({
            'lead_id': lead.id if lead else False,
            'user_id': self.env.user.id,
            'provider': provider_key,
            'model': model,
            'status': status,
            'error_message': error_message,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'cost_estimate': cost,
            'draft_preview': draft or '',
        })
