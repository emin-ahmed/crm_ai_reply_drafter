# Part of the crm_ai_reply_assistant module. See LICENSE file for details.
from odoo import api, fields, models


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    # Drives visibility of the Draft Reply button: only meaningful once there
    # is a real conversation message (comment/email) to reply to. The automatic
    # "created" log note (a notification) does not count.
    has_chatter_messages = fields.Boolean(
        compute='_compute_has_chatter_messages',
        help="Technical: True when the lead has at least one comment/email "
             "message in its chatter.")

    @api.depends('message_ids', 'message_ids.message_type')
    def _compute_has_chatter_messages(self):
        for lead in self:
            lead.has_chatter_messages = bool(lead.message_ids.filtered(
                lambda m: m.message_type in ('comment', 'email')))

    def action_ai_draft_reply(self):
        """Open the AI Reply Drafter wizard for this lead.

        Creates a transient wizard record bound to the lead and returns an
        act_window action that opens it as a dialog. The wizard's OWL component
        streams the draft on mount.
        """
        self.ensure_one()
        wizard = self.env['crm.ai.reply.wizard'].create({'lead_id': self.id})
        return {
            'type': 'ir.actions.act_window',
            'name': 'Draft Reply',
            'res_model': 'crm.ai.reply.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
