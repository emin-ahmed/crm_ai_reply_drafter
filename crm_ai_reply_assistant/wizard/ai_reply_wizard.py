# Part of the crm_ai_reply_assistant module. See LICENSE file for details.
from markupsafe import escape, Markup

from odoo import _, fields, models
from odoo.exceptions import UserError


class AiReplyWizard(models.TransientModel):
    _name = 'crm.ai.reply.wizard'
    _description = 'AI Reply Drafter Wizard'

    lead_id = fields.Many2one(
        'crm.lead', string='Lead/Opportunity', required=True, readonly=True,
        ondelete='cascade')
    state = fields.Selection(
        selection=[
            ('streaming', 'Generating'),
            ('done', 'Ready'),
            ('error', 'Failed'),
        ],
        string='Status', default='streaming', required=True)
    generated_draft = fields.Text(
        string='Draft', help='The reply email body produced by the model.')
    error_message = fields.Text(string='Error')

    # Filled in by the streaming controller when generation completes, for
    # display and so the log/composer can reference them.
    input_tokens = fields.Integer(string='Input Tokens', readonly=True)
    output_tokens = fields.Integer(string='Output Tokens', readonly=True)
    cost_estimate = fields.Monetary(
        string='Cost Estimate', currency_field='currency_id', readonly=True)
    currency_id = fields.Many2one(
        'res.currency', readonly=True,
        default=lambda self: self.env.ref('base.USD', raise_if_not_found=False))

    def _draft_html(self):
        """Return the (possibly edited) draft as HTML, preserving line breaks."""
        return Markup("<p>%s</p>") % Markup("<br/>").join(
            escape(line) for line in (self.generated_draft or '').split('\n'))

    def action_send_now(self):
        """Post the draft to the lead's chatter and email the customer.

        This is the one-click path: the salesperson has reviewed (and may have
        edited) the draft in the wizard, so clicking Send posts it as a chatter
        message and notifies the lead's contact by email through the configured
        mail server. Still not auto-send — it requires this explicit click.
        """
        self.ensure_one()
        if not self.generated_draft:
            raise UserError(_("There is no draft to send yet."))
        self.lead_id.message_post(
            body=self._draft_html(),
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
            partner_ids=self.lead_id.partner_id.ids,
        )
        return {'type': 'ir.actions.act_window_close'}

    def action_use_draft(self):
        """Open the email composer pre-filled with the generated draft.

        The secondary path, for when the salesperson wants the full composer
        (attachments, extra recipients, subject) before sending.
        """
        self.ensure_one()
        if not self.generated_draft:
            raise UserError(_("There is no draft to use yet."))

        # Preserve line breaks when moving plain text into the HTML composer.
        body = self._draft_html()

        ctx = {
            'default_model': 'crm.lead',
            'default_res_ids': self.lead_id.ids,
            'default_composition_mode': 'comment',
            'default_body': body,
        }
        if self.lead_id.partner_id:
            ctx['default_partner_ids'] = self.lead_id.partner_id.ids
        return {
            'type': 'ir.actions.act_window',
            'name': _('Send Reply'),
            'res_model': 'mail.compose.message',
            'view_mode': 'form',
            'target': 'new',
            'context': ctx,
        }
