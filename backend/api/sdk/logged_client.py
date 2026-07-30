import time

import requests
from django.conf import settings
from google import genai
from google.genai import types

DEFAULT_MODEL = "gemini-flash-latest"
DEFAULT_PROVIDER = "google"  # "google" | "anthropic" | "openai"
INGESTION_URL = "http://127.0.0.1:8000/api/logs/"

# Internal roles are "user"/"assistant"; provider SDKs map differently
ROLE_MAP = {"user": "user", "assistant": "model"}  # Gemini expects "model"


class LoggedInferenceClient:
    """Multi-provider inference wrapper that captures metadata regardless of provider.

    Supports:
    - google/gemini (real, free tier via Google AI Studio)
    - anthropic/claude (mocked, requires paid API key)
    - openai/gpt-4 (mocked, requires paid API key)

    Mocking allows demonstrating multi-provider architecture without needing
    paid API credentials for every provider.
    """

    def __init__(self, provider=DEFAULT_PROVIDER, model=None, api_key=None, ingestion_url=INGESTION_URL):
        self.provider = provider.lower()
        self.ingestion_url = ingestion_url

        # Provider-specific model defaults
        if model is None:
            if self.provider == "google":
                model = "gemini-flash-latest"
            elif self.provider == "anthropic":
                model = "claude-3-5-sonnet-20241022"
            elif self.provider == "openai":
                model = "gpt-4-turbo"
            else:
                raise ValueError(f"Unknown provider: {self.provider}")

        self.model = model

        # Initialize provider-specific clients (real or mock)
        if self.provider == "google":
            self.client = genai.Client(api_key=api_key or settings.GEMINI_API_KEY)
        elif self.provider == "anthropic":
            # Claude client would go here; we're mocking instead
            self.client = None
        elif self.provider == "openai":
            # OpenAI client would go here; we're mocking instead
            self.client = None
        else:
            raise ValueError(f"Unknown provider: {self.provider}")

    def send(self, *, session_id, messages, conversation_id=None, system=None):
        """Send inference request to the provider, log metadata, return reply."""
        start = time.monotonic()
        input_preview = messages[-1]["content"][:200] if messages else ""

        try:
            if self.provider == "google":
                output_text, input_tokens, output_tokens = self._call_gemini(messages, system)
            elif self.provider == "anthropic":
                output_text, input_tokens, output_tokens = self._call_claude_mock(messages, system)
            elif self.provider == "openai":
                output_text, input_tokens, output_tokens = self._call_gpt_mock(messages, system)

            latency_ms = (time.monotonic() - start) * 1000
            self._log(
                conversation_id=conversation_id,
                session_id=session_id,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                status="success",
                error_message=None,
                input_preview=input_preview,
                output_preview=output_text[:200],
            )
            return output_text

        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000
            self._log(
                conversation_id=conversation_id,
                session_id=session_id,
                latency_ms=latency_ms,
                input_tokens=None,
                output_tokens=None,
                status="error",
                error_message=str(exc),
                input_preview=input_preview,
                output_preview="",
            )
            raise

    def _call_gemini(self, messages, system):
        """Real call to Google Gemini API (free tier via Google AI Studio)."""
        contents = [
            types.Content(
                role=ROLE_MAP[m["role"]], parts=[types.Part(text=m["content"])]
            )
            for m in messages
        ]

        response = self.client.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system or "You are a helpful assistant."
            ),
        )
        output_text = response.text or ""
        usage = response.usage_metadata
        return (
            output_text,
            usage.prompt_token_count if usage else 0,
            usage.candidates_token_count if usage else 0,
        )

    def _call_claude_mock(self, messages, system):
        """Mock Claude response (demonstrates multi-provider architecture).

        Note: Real Claude calls require paid Anthropic API key.
        This mock shows the provider abstraction works; swap with real SDK
        if API credentials become available.
        """
        last_user_msg = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"),
            "hello"
        )

        # Mock response based on question pattern
        if "name" in last_user_msg.lower():
            response = f"I'm Claude, an AI assistant made by Anthropic. My name reflects my creator's initials."
        elif "weather" in last_user_msg.lower():
            response = "I don't have real-time weather data, but I can help you understand weather patterns or find resources."
        elif "2+2" in last_user_msg or "2 + 2" in last_user_msg:
            response = "2 + 2 = 4"
        elif "previous" in last_user_msg.lower() or "earlier" in last_user_msg.lower():
            response = "I can see the conversation history and maintain context across our discussion."
        else:
            response = f"[Claude Mock] I would respond to: '{last_user_msg[:50]}...'"

        # Mock token counts (realistic estimate)
        input_tokens = len(last_user_msg.split()) + 50
        output_tokens = len(response.split()) + 20

        return response, input_tokens, output_tokens

    def _call_gpt_mock(self, messages, system):
        """Mock GPT-4 response (demonstrates multi-provider architecture).

        Note: Real GPT calls require paid OpenAI API key.
        This mock shows the provider abstraction works; swap with real SDK
        if API credentials become available.
        """
        last_user_msg = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"),
            "hello"
        )

        # Mock response based on question pattern
        if "name" in last_user_msg.lower():
            response = f"I'm GPT-4, an AI model developed by OpenAI."
        elif "weather" in last_user_msg.lower():
            response = "I can provide information about weather conditions, though I don't have access to real-time data."
        elif "2+2" in last_user_msg or "2 + 2" in last_user_msg:
            response = "2 + 2 = 4"
        elif "previous" in last_user_msg.lower() or "earlier" in last_user_msg.lower():
            response = "Yes, I can refer back to our earlier conversation in this thread."
        else:
            response = f"[GPT-4 Mock] Regarding your question: '{last_user_msg[:50]}...'"

        # Mock token counts (realistic estimate)
        input_tokens = len(last_user_msg.split()) + 60
        output_tokens = len(response.split()) + 25

        return response, input_tokens, output_tokens

    def _log(
        self,
        conversation_id,
        session_id,
        latency_ms,
        input_tokens,
        output_tokens,
        status,
        error_message,
        input_preview,
        output_preview,
    ):
        """Send metadata to the ingestion endpoint."""
        payload = {
            "conversation": str(conversation_id) if conversation_id else None,
            "session_id": session_id,
            "provider": self.provider,
            "model": self.model,
            "latency_ms": latency_ms,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "status": status,
            "error_message": error_message,
            "input_preview": input_preview,
            "output_preview": output_preview,
        }
        try:
            requests.post(self.ingestion_url, json=payload, timeout=5)
        except requests.RequestException:
            # A logging failure should never break the chat response itself.
            pass


# Backwards compatibility alias
LoggedGeminiClient = LoggedInferenceClient
