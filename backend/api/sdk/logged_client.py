import time

import requests
from django.conf import settings
from google import genai
from google.genai import types

DEFAULT_MODEL = "gemini-flash-latest"
INGESTION_URL = "http://127.0.0.1:8000/api/logs/"

# Our internal roles are "user"/"assistant"; Gemini expects "user"/"model".
ROLE_MAP = {"user": "user", "assistant": "model"}


class LoggedGeminiClient:
    """Thin wrapper around the Gemini SDK that captures inference metadata
    (latency, token usage, status, previews) and ships it to the ingestion
    endpoint after every call, success or failure."""

    def __init__(self, api_key=None, model=DEFAULT_MODEL, ingestion_url=INGESTION_URL):
        self.client = genai.Client(api_key=api_key or settings.GEMINI_API_KEY)
        self.model = model
        self.ingestion_url = ingestion_url

    def send(self, *, session_id, messages, conversation_id=None, system=None):
        start = time.monotonic()
        input_preview = messages[-1]["content"][:200] if messages else ""

        contents = [
            types.Content(
                role=ROLE_MAP[m["role"]], parts=[types.Part(text=m["content"])]
            )
            for m in messages
        ]

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system or "You are a helpful assistant."
                ),
            )
            latency_ms = (time.monotonic() - start) * 1000
            output_text = response.text or ""
            usage = response.usage_metadata
            self._log(
                conversation_id=conversation_id,
                session_id=session_id,
                latency_ms=latency_ms,
                input_tokens=usage.prompt_token_count if usage else None,
                output_tokens=usage.candidates_token_count if usage else None,
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
        payload = {
            "conversation": str(conversation_id) if conversation_id else None,
            "session_id": session_id,
            "provider": "google",
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
