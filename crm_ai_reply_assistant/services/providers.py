# Part of the crm_ai_reply_assistant module. See LICENSE file for details.
"""LLM provider clients.

One thin client per provider, all behind a common :class:`BaseProvider`
interface so the Odoo layer never embeds a vendor SDK call directly and so the
network call can be mocked in tests. Each client streams the draft as it is
generated and records token usage so a cost estimate can be derived.

SDKs are imported lazily inside each client: only the provider actually
configured needs its library installed, and a missing library raises a clear,
translatable :class:`~odoo.exceptions.UserError` rather than an ImportError
traceback at module load.
"""
import json
import logging

from odoo import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Indicative pricing in USD per 1,000,000 tokens, as (input, output).
# Used only for the cost estimate shown in the log — verify against the
# provider's current pricing (for Anthropic, see the claude-api skill). Unknown
# models fall back to the provider's flagship price so the estimate is never
# silently zero.
PRICING = {
    'anthropic': {
        'claude-opus-4-8': (5.0, 25.0),
        'claude-opus-4-7': (5.0, 25.0),
        'claude-opus-4-6': (5.0, 25.0),
        'claude-sonnet-4-6': (3.0, 15.0),
        'claude-haiku-4-5': (1.0, 5.0),
        '_default': (5.0, 25.0),
    },
    'openai': {
        'gpt-4o': (2.5, 10.0),
        'gpt-4o-mini': (0.15, 0.6),
        '_default': (2.5, 10.0),
    },
    # Ollama runs locally; there is no per-token cost.
    'ollama': {'_default': (0.0, 0.0)},
}

# Per-provider default model used when none is configured in Settings.
DEFAULT_MODELS = {
    'anthropic': 'claude-opus-4-8',
    'openai': 'gpt-4o',
    'ollama': 'llama3.1',
}

# Cap the draft length. An email reply is short; this keeps latency and cost
# bounded. Well under the streaming threshold where SDK timeouts matter.
MAX_OUTPUT_TOKENS = 2048


def estimate_cost(provider, model, input_tokens, output_tokens):
    """Return an indicative USD cost for a generation.

    :param str provider: provider key (anthropic/openai/ollama)
    :param str model: model name
    :param int input_tokens: prompt tokens billed
    :param int output_tokens: completion tokens billed
    :rtype: float
    """
    table = PRICING.get(provider, {})
    in_price, out_price = table.get(model) or table.get('_default', (0.0, 0.0))
    return (input_tokens or 0) / 1e6 * in_price + \
           (output_tokens or 0) / 1e6 * out_price


class BaseProvider:
    """Common interface for the LLM provider clients.

    Subclasses implement :meth:`stream`, a generator yielding text chunks. When
    the generator is exhausted, :attr:`usage` holds the token counts as
    ``{'input_tokens': int, 'output_tokens': int}``.
    """

    key = None  # provider key, set by subclasses

    def __init__(self, model=None, api_key=None, base_url=None):
        self.model = model or DEFAULT_MODELS.get(self.key)
        self.api_key = api_key
        self.base_url = base_url
        self.usage = {'input_tokens': 0, 'output_tokens': 0}

    def stream(self, system, user_content):
        """Yield draft text chunks for the given system + user prompt.

        :param str system: the system prompt
        :param str user: the assembled lead context + conversation
        :returns: generator of ``str`` chunks
        """
        raise NotImplementedError

    def _require(self, value, message):
        """Raise a translatable UserError if a required setting is missing."""
        if not value:
            raise UserError(message)
        return value


class AnthropicProvider(BaseProvider):
    """Anthropic Claude via the official ``anthropic`` SDK (Messages API)."""

    key = 'anthropic'

    def stream(self, system, user_content):
        self._require(self.api_key, _(
            "No Anthropic API key configured. Set it in "
            "Settings → AI Reply Drafter."))
        try:
            import anthropic
        except ImportError as exc:
            raise UserError(_(
                "The 'anthropic' Python package is required for the Anthropic "
                "provider. Install it with: pip install anthropic")) from exc

        client = anthropic.Anthropic(api_key=self.api_key)
        # Streamed so the UI can show the draft live. Thinking is left off:
        # email drafting is simple and the system prompt already constrains the
        # model to output only the email body.
        with client.messages.stream(
            model=self.model,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user_content}],
        ) as stream:
            for text in stream.text_stream:
                yield text
            final = stream.get_final_message()
            self.usage = {
                'input_tokens': final.usage.input_tokens,
                'output_tokens': final.usage.output_tokens,
            }


class OpenAIProvider(BaseProvider):
    """OpenAI via the official ``openai`` SDK (Chat Completions, streamed)."""

    key = 'openai'

    def stream(self, system, user_content):
        self._require(self.api_key, _(
            "No OpenAI API key configured. Set it in "
            "Settings → AI Reply Drafter."))
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise UserError(_(
                "The 'openai' Python package is required for the OpenAI "
                "provider. Install it with: pip install openai")) from exc

        # base_url defaults to OpenAI; set it for an OpenAI-compatible gateway
        # such as OpenRouter (https://openrouter.ai/api/v1).
        client = OpenAI(api_key=self.api_key, base_url=self.base_url or None)
        stream = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            max_tokens=MAX_OUTPUT_TOKENS,
            stream=True,
            # Ask for the final usage chunk while streaming.
            stream_options={"include_usage": True},
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
            # The terminal chunk carries usage and has empty choices.
            if getattr(chunk, 'usage', None):
                self.usage = {
                    'input_tokens': chunk.usage.prompt_tokens,
                    'output_tokens': chunk.usage.completion_tokens,
                }


class OllamaProvider(BaseProvider):
    """Local Ollama server over its HTTP chat API (streamed, no API key)."""

    key = 'ollama'

    def stream(self, system, user_content):
        base_url = self._require(self.base_url, _(
            "No Ollama base URL configured. Set it in "
            "Settings → AI Reply Drafter.")).rstrip('/')
        try:
            import requests
        except ImportError as exc:
            raise UserError(_(
                "The 'requests' Python package is required for the Ollama "
                "provider. Install it with: pip install requests")) from exc

        try:
            response = requests.post(
                "%s/api/chat" % base_url,
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_content},
                    ],
                    "stream": True,
                },
                stream=True,
                timeout=300,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise UserError(_(
                "Could not reach the Ollama server at %(url)s: %(err)s",
                url=base_url, err=exc)) from exc

        for line in response.iter_lines():
            if not line:
                continue
            data = json.loads(line)
            message = data.get('message') or {}
            if message.get('content'):
                yield message['content']
            if data.get('done'):
                self.usage = {
                    'input_tokens': data.get('prompt_eval_count', 0),
                    'output_tokens': data.get('eval_count', 0),
                }


_PROVIDERS = {
    'anthropic': AnthropicProvider,
    'openai': OpenAIProvider,
    'ollama': OllamaProvider,
}


def get_provider(provider_key, **kwargs):
    """Instantiate the client for ``provider_key``.

    :raises UserError: if the provider key is unknown.
    """
    cls = _PROVIDERS.get(provider_key)
    if not cls:
        raise UserError(_("Unknown LLM provider: %s", provider_key))
    return cls(**kwargs)
