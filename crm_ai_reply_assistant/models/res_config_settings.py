# Part of the crm_ai_reply_assistant module. See LICENSE file for details.
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # All settings are stored as ir.config_parameter (global, not per-company).
    # The service layer reads them via env['ir.config_parameter'].sudo().
    crm_ai_provider = fields.Selection(
        selection=[
            ('anthropic', 'Anthropic (Claude)'),
            ('openai', 'OpenAI'),
            ('ollama', 'Ollama (local)'),
        ],
        string='LLM Provider',
        default='anthropic',
        config_parameter='crm_ai_reply_assistant.provider',
        help='Which LLM provider drafts the replies. One provider per '
             'configuration — pick the one whose API key you set below.')
    crm_ai_model = fields.Char(
        string='Model',
        config_parameter='crm_ai_reply_assistant.model',
        help='Model name for the selected provider, e.g. claude-opus-4-8, '
             'gpt-4o, or llama3.1.')
    crm_ai_anthropic_api_key = fields.Char(
        string='Anthropic API Key',
        config_parameter='crm_ai_reply_assistant.anthropic_api_key',
        help='Create one at https://console.anthropic.com/. Stored as a '
             'system parameter — never commit it.')
    crm_ai_openai_api_key = fields.Char(
        string='OpenAI API Key',
        config_parameter='crm_ai_reply_assistant.openai_api_key',
        help='Create one at https://platform.openai.com/. Stored as a system '
             'parameter — never commit it.')
    crm_ai_openai_base_url = fields.Char(
        string='OpenAI API Base URL',
        config_parameter='crm_ai_reply_assistant.openai_base_url',
        help='Optional. Leave empty for OpenAI. Set to an OpenAI-compatible '
             'endpoint to use another gateway, e.g. https://openrouter.ai/api/v1 '
             'for OpenRouter (use the matching API key and provider-prefixed '
             'model id, e.g. anthropic/claude-sonnet-4).')
    crm_ai_ollama_base_url = fields.Char(
        string='Ollama Base URL',
        default='http://localhost:11434',
        config_parameter='crm_ai_reply_assistant.ollama_base_url',
        help='URL of your local Ollama server. No API key needed.')
    # Char (not Text): res.config.settings config_parameter fields must be a
    # simple scalar type. Char maps to an unbounded varchar in Postgres, so it
    # still holds a long multi-line prompt; the view renders it with
    # widget="text" as a textarea.
    crm_ai_system_prompt = fields.Char(
        string='System Prompt',
        config_parameter='crm_ai_reply_assistant.system_prompt',
        help='Instruction template that steers every draft. The lead data and '
             'chatter history are appended to this automatically.')
    crm_ai_max_context_messages = fields.Integer(
        string='Max Context Messages',
        default=20,
        config_parameter='crm_ai_reply_assistant.max_context_messages',
        help='How many of the most recent chatter messages to include in the '
             'prompt, oldest first.')
