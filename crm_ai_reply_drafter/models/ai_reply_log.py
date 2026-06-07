# Part of the crm_ai_reply_drafter module. See LICENSE file for details.
from odoo import api, fields, models


class AiReplyLog(models.Model):
    _name = 'crm.ai.reply.log'
    _description = 'AI Reply Drafter Generation Log'
    _order = 'create_date desc'
    _rec_name = 'lead_id'

    lead_id = fields.Many2one(
        'crm.lead', string='Lead/Opportunity', ondelete='set null', index=True,
        help='The lead this draft was generated for.')
    user_id = fields.Many2one(
        'res.users', string='Salesperson', required=True, index=True,
        default=lambda self: self.env.user,
        help='The user who requested the draft.')
    provider = fields.Char(string='Provider', readonly=True)
    model = fields.Char(string='Model', readonly=True)
    status = fields.Selection(
        selection=[('success', 'Success'), ('error', 'Error')],
        string='Status', default='success', required=True, readonly=True)
    error_message = fields.Text(string='Error', readonly=True)

    input_tokens = fields.Integer(string='Input Tokens', readonly=True)
    output_tokens = fields.Integer(string='Output Tokens', readonly=True)
    total_tokens = fields.Integer(
        string='Total Tokens', compute='_compute_total_tokens', store=True)

    cost_estimate = fields.Monetary(
        string='Cost Estimate', currency_field='currency_id', readonly=True,
        help='Estimated cost from the provider token pricing. Indicative only.')
    currency_id = fields.Many2one(
        'res.currency', string='Currency', readonly=True,
        default=lambda self: self.env.ref('base.USD', raise_if_not_found=False),
        help='Provider pricing is quoted in USD.')

    draft_preview = fields.Text(
        string='Draft', readonly=True,
        help='The text that was generated and shown to the user.')

    @api.depends('input_tokens', 'output_tokens')
    def _compute_total_tokens(self):
        for log in self:
            log.total_tokens = (log.input_tokens or 0) + (log.output_tokens or 0)
