# Part of the crm_ai_reply_drafter module. See LICENSE file for details.
import sys
import types
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.crm_ai_reply_drafter.services import providers


class FakeProvider(providers.BaseProvider):
    """A provider stub that yields canned chunks instead of calling an API."""

    key = 'anthropic'
    CHUNKS = ["Hello ", "Jane,\n", "thanks for reaching out."]

    def stream(self, system, user):
        self.last_system = system
        self.last_user = user
        for chunk in self.CHUNKS:
            yield chunk
        self.usage = {'input_tokens': 120, 'output_tokens': 30}


@tagged('post_install', '-at_install')
class TestAiReplyService(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.service = cls.env['crm.ai.reply.service']
        cls.ICP = cls.env['ir.config_parameter'].sudo()
        cls.ICP.set_param('crm_ai_reply_drafter.provider', 'anthropic')
        cls.ICP.set_param('crm_ai_reply_drafter.model', 'claude-opus-4-8')
        cls.ICP.set_param('crm_ai_reply_drafter.anthropic_api_key', 'sk-ant-test')
        cls.ICP.set_param('crm_ai_reply_drafter.system_prompt', 'You are a sales rep.')
        cls.ICP.set_param('crm_ai_reply_drafter.max_context_messages', '20')

        cls.lead = cls.env['crm.lead'].create({
            'name': 'Big deal',
            'type': 'opportunity',
            'contact_name': 'Jane Doe',
            'email_from': 'jane@example.com',
            'expected_revenue': 5000.0,
        })
        # Two chatter messages to give the prompt some conversation.
        cls.lead.message_post(body='<p>Hi, is this still available?</p>',
                              message_type='comment')
        cls.lead.message_post(body='<p>Yes — can you send pricing?</p>',
                              message_type='comment')

    # --- prompt building -----------------------------------------------------

    def test_build_prompt_includes_lead_and_conversation(self):
        system, user = self.service.build_prompt(self.lead)
        self.assertEqual(system, 'You are a sales rep.')
        self.assertIn('Big deal', user)
        self.assertIn('Jane Doe', user)
        self.assertIn('5000', user)
        self.assertIn('is this still available?', user)
        self.assertIn('can you send pricing?', user)

    def test_conversation_is_chronological(self):
        _system, user = self.service.build_prompt(self.lead)
        self.assertLess(
            user.index('is this still available?'),
            user.index('can you send pricing?'),
            "Messages should appear oldest-first in the prompt.")

    def test_max_context_messages_limits_conversation(self):
        self.ICP.set_param('crm_ai_reply_drafter.max_context_messages', '1')
        _system, user = self.service.build_prompt(self.lead)
        # Only the most recent message should survive the cap.
        self.assertIn('can you send pricing?', user)
        self.assertNotIn('is this still available?', user)

    # --- configuration / provider selection ---------------------------------

    def test_prepare_requires_api_key(self):
        self.ICP.set_param('crm_ai_reply_drafter.anthropic_api_key', '')
        with self.assertRaises(UserError):
            self.service.prepare(self.lead)

    def test_get_provider_unknown_raises(self):
        self.ICP.set_param('crm_ai_reply_drafter.provider', 'nope')
        with self.assertRaises(UserError):
            self.service._get_provider()

    def test_openai_compatible_base_url_is_passed(self):
        """An OpenAI-compatible gateway (e.g. OpenRouter) flows base_url through."""
        self.ICP.set_param('crm_ai_reply_drafter.provider', 'openai')
        self.ICP.set_param('crm_ai_reply_drafter.openai_api_key', 'sk-or-test')
        self.ICP.set_param('crm_ai_reply_drafter.openai_base_url',
                           'https://openrouter.ai/api/v1')
        self.ICP.set_param('crm_ai_reply_drafter.model',
                           'anthropic/claude-sonnet-4')
        cfg = self.service._get_config()
        self.assertEqual(cfg['base_url'], 'https://openrouter.ai/api/v1')
        provider = self.service._get_provider(cfg)
        self.assertEqual(provider.key, 'openai')
        self.assertEqual(provider.base_url, 'https://openrouter.ai/api/v1')
        self.assertEqual(provider.model, 'anthropic/claude-sonnet-4')

    def test_settings_fields_are_classifiable(self):
        """res.config.settings opens without the Text-field classification error.

        config_parameter fields must be a simple scalar type; default_get runs
        _get_classified_fields, which raises for an unsupported type (e.g. Text).
        """
        settings = self.env['res.config.settings']
        values = settings.default_get(list(settings.fields_get()))
        self.assertIn('crm_ai_system_prompt', values)

    # --- streaming (LLM call mocked) -----------------------------------------

    def test_stream_yields_chunks_and_usage(self):
        with patch.object(providers, 'get_provider', return_value=FakeProvider(
                model='claude-opus-4-8', api_key='sk-ant-test')):
            provider, system, user = self.service.prepare(self.lead)
            collected = "".join(provider.stream(system, user))
        self.assertEqual(collected, "Hello Jane,\nthanks for reaching out.")
        self.assertEqual(provider.usage['input_tokens'], 120)
        self.assertEqual(provider.usage['output_tokens'], 30)

    def test_anthropic_provider_parses_sdk_stream(self):
        """AnthropicProvider drives the SDK and reads usage — SDK fully mocked."""
        fake_anthropic = self._build_fake_anthropic_module(
            chunks=["Hi ", "there"], input_tokens=10, output_tokens=5)
        with patch.dict(sys.modules, {'anthropic': fake_anthropic}):
            provider = providers.AnthropicProvider(
                model='claude-opus-4-8', api_key='sk-ant-test')
            text = "".join(provider.stream('sys', 'user'))
        self.assertEqual(text, "Hi there")
        self.assertEqual(provider.usage, {'input_tokens': 10, 'output_tokens': 5})

    # --- logging & cost ------------------------------------------------------

    def test_log_generation_records_tokens_and_cost(self):
        log = self.service.log_generation(
            self.lead, 'anthropic', 'claude-opus-4-8',
            {'input_tokens': 1_000_000, 'output_tokens': 1_000_000},
            'Draft body', status='success')
        self.assertEqual(log.lead_id, self.lead)
        self.assertEqual(log.total_tokens, 2_000_000)
        # opus 4.8 pricing: $5 in + $25 out per 1M → $30 for 1M+1M.
        self.assertAlmostEqual(log.cost_estimate, 30.0, places=4)
        self.assertEqual(log.status, 'success')

    def test_estimate_cost_unknown_model_uses_default(self):
        cost = providers.estimate_cost(
            'anthropic', 'some-future-model', 1_000_000, 0)
        self.assertAlmostEqual(cost, 5.0, places=4)  # _default input price

    def test_estimate_cost_ollama_is_free(self):
        self.assertEqual(
            providers.estimate_cost('ollama', 'llama3.1', 999, 999), 0.0)

    # --- wizard / lead actions ----------------------------------------------

    def test_action_ai_draft_reply_opens_wizard(self):
        action = self.lead.action_ai_draft_reply()
        self.assertEqual(action['res_model'], 'crm.ai.reply.wizard')
        wizard = self.env['crm.ai.reply.wizard'].browse(action['res_id'])
        self.assertEqual(wizard.lead_id, self.lead)
        self.assertEqual(wizard.state, 'streaming')

    def test_use_draft_opens_composer_prefilled(self):
        wizard = self.env['crm.ai.reply.wizard'].create({
            'lead_id': self.lead.id,
            'state': 'done',
            'generated_draft': 'Line one\nLine two',
        })
        action = wizard.action_use_draft()
        self.assertEqual(action['res_model'], 'mail.compose.message')
        ctx = action['context']
        self.assertEqual(ctx['default_model'], 'crm.lead')
        self.assertEqual(ctx['default_res_ids'], self.lead.ids)
        self.assertIn('Line one', ctx['default_body'])
        self.assertIn('<br', ctx['default_body'])  # newline preserved as <br/>

    def test_send_now_posts_to_chatter(self):
        wizard = self.env['crm.ai.reply.wizard'].create({
            'lead_id': self.lead.id,
            'state': 'done',
            'generated_draft': 'Hi Jane,\nHere is the quote you asked for.',
        })
        before = len(self.lead.message_ids)
        action = wizard.action_send_now()
        self.assertEqual(action['type'], 'ir.actions.act_window_close')
        self.lead.invalidate_recordset()
        self.assertEqual(len(self.lead.message_ids), before + 1)
        latest = self.lead.message_ids[0]
        self.assertIn('Here is the quote', latest.body)
        self.assertIn('<br', latest.body)  # newline preserved as <br/>

    def test_send_now_without_text_raises(self):
        wizard = self.env['crm.ai.reply.wizard'].create({
            'lead_id': self.lead.id, 'state': 'done'})
        with self.assertRaises(UserError):
            wizard.action_send_now()

    def test_use_draft_without_text_raises(self):
        wizard = self.env['crm.ai.reply.wizard'].create({
            'lead_id': self.lead.id, 'state': 'done'})
        with self.assertRaises(UserError):
            wizard.action_use_draft()

    def test_has_chatter_messages_flag(self):
        self.assertTrue(self.lead.has_chatter_messages)
        empty = self.env['crm.lead'].create({'name': 'No chatter yet'})
        # A freshly created lead with no posted messages.
        self.assertFalse(empty.has_chatter_messages)

    # --- helpers -------------------------------------------------------------

    def _build_fake_anthropic_module(self, chunks, input_tokens, output_tokens):
        """Construct a stand-in ``anthropic`` module for AnthropicProvider.

        Uses concrete classes (not MagicMock) so the streaming context manager
        and ``text_stream`` iterator behave exactly like the real SDK.
        """
        class _Usage:
            def __init__(self, i, o):
                self.input_tokens = i
                self.output_tokens = o

        class _Final:
            usage = _Usage(input_tokens, output_tokens)

        class _StreamCM:
            text_stream = iter(chunks)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def get_final_message(self):
                return _Final()

        class _Messages:
            def stream(self, **kwargs):
                return _StreamCM()

        class _Client:
            def __init__(self, **kwargs):
                self.messages = _Messages()

        module = types.ModuleType('anthropic')
        module.Anthropic = _Client
        return module
