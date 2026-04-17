"""
provider.py — Unified AI provider abstraction.

Supports Groq, OpenAI, and Claude (Anthropic) as interchangeable backends.
Each provider normalises its SDK into a common interface so that
assistant.py, screenshot.py, and transcriber.py stay provider-agnostic.
"""

import os
import sys
import time
import base64
from abc import ABC, abstractmethod


# ──────────────────────────────────────────────
# Quota / Rate-Limit Error Detection
# ──────────────────────────────────────────────
class QuotaExceededError(Exception):
    """Raised when an API key has exceeded its quota or rate limit."""
    def __init__(self, provider: str, original_error: Exception = None):
        self.provider = provider
        self.original_error = original_error
        super().__init__(f"{provider} API quota exceeded. Check your plan and billing.")


def is_quota_error(error) -> bool:
    """Detect if an exception is a quota/rate-limit/billing error from any provider."""
    err_str = str(error).lower()
    quota_keywords = [
        "quota", "rate_limit", "rate limit", "insufficient_quota",
        "exceeded", "billing", "429", "too many requests",
        "resource_exhausted", "overloaded",
    ]
    return any(kw in err_str for kw in quota_keywords)


def friendly_quota_message(provider_name: str) -> str:
    """Return a user-friendly quota error message for display in the overlay."""
    links = {
        "groq": "console.groq.com",
        "openai": "platform.openai.com/settings/organization/billing",
        "claude": "console.anthropic.com/settings/plans",
    }
    link = links.get(provider_name, "your provider dashboard")
    return f"[!] {provider_name.upper()} API quota exceeded. Check your plan & billing at {link}"


# ──────────────────────────────────────────────
# Default models per provider
# ──────────────────────────────────────────────
PROVIDER_DEFAULTS = {
    "groq": {
        "chat_model": "llama-3.3-70b-versatile",
        "vision_model": "meta-llama/llama-4-scout-17b-16e-instruct",
        "stt_model": "whisper-large-v3-turbo",
    },
    "openai": {
        "chat_model": "gpt-4o",
        "vision_model": "gpt-4o",
        "stt_model": "whisper-1",
    },
    "claude": {
        "chat_model": "claude-sonnet-4-20250514",
        "vision_model": "claude-sonnet-4-20250514",
        "stt_model": None,  # Falls back to Groq Whisper
    },
}


# ──────────────────────────────────────────────
# Base class
# ──────────────────────────────────────────────
class BaseProvider(ABC):
    """Abstract base for all AI providers."""

    name: str = "base"

    def __init__(self, api_key: str, fallback_key: str = None):
        self.api_key = api_key
        self.fallback_key = fallback_key

    @abstractmethod
    def chat_complete(self, messages: list, temperature: float = 0.3,
                      max_tokens: int = 1200, stream: bool = True):
        """
        Generate a chat completion.

        When stream=True, yields dicts:
            {"type": "chunk", "text": "...", "latency_ms": float}
            {"type": "done",  "text": "full text", "latency_ms": float}
            {"type": "error", "text": "Error: ...", "latency_ms": float}

        When stream=False, returns a single string.
        """
        ...

    @abstractmethod
    def vision_complete(self, messages: list, temperature: float = 0.3,
                        max_tokens: int = 1024, stream: bool = True):
        """
        Generate a vision completion (image + text).
        Same yield contract as chat_complete.
        """
        ...

    @abstractmethod
    def transcribe(self, wav_path: str, language: str = "en") -> str:
        """Transcribe audio file. Returns text string."""
        ...

    @property
    def supports_transcription(self) -> bool:
        """Whether this provider natively supports STT."""
        return True


# ──────────────────────────────────────────────
# Groq Provider
# ──────────────────────────────────────────────
class GroqProvider(BaseProvider):
    """Groq Cloud — LLaMA models via ultra-fast inference."""

    name = "groq"

    def __init__(self, api_key: str, fallback_key: str = None):
        super().__init__(api_key, fallback_key)
        from groq import Groq
        self.client = Groq(api_key=api_key)
        self.fallback_client = Groq(api_key=fallback_key) if fallback_key else None
        self.defaults = PROVIDER_DEFAULTS["groq"]
        print("[provider] Initialized GroqProvider", file=sys.stderr)

    def chat_complete(self, messages, temperature=0.3, max_tokens=1200, stream=True):
        return self._complete(messages, self.defaults["chat_model"],
                              temperature, max_tokens, stream)

    def vision_complete(self, messages, temperature=0.3, max_tokens=1024, stream=True):
        return self._complete(messages, self.defaults["vision_model"],
                              temperature, max_tokens, stream)

    def _complete(self, messages, model, temperature, max_tokens, stream):
        from groq import RateLimitError

        start = time.time()
        api_args = dict(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
        )

        if not stream:
            try:
                try:
                    resp = self.client.chat.completions.create(**api_args)
                except RateLimitError:
                    if not self.fallback_client:
                        raise
                    print("[provider:groq] Rate-limited, using fallback", file=sys.stderr)
                    resp = self.fallback_client.chat.completions.create(**api_args)
                return resp.choices[0].message.content.strip()
            except Exception as e:
                return f"Error: {e}"

        # Streaming
        def _stream():
            nonlocal start
            first_token = True
            full_text = []
            try:
                try:
                    stream_resp = self.client.chat.completions.create(**api_args)
                except RateLimitError:
                    if not self.fallback_client:
                        raise
                    print("[provider:groq] Rate-limited, using fallback", file=sys.stderr)
                    stream_resp = self.fallback_client.chat.completions.create(**api_args)

                for chunk in stream_resp:
                    if chunk.choices[0].delta.content:
                        text = chunk.choices[0].delta.content
                        full_text.append(text)
                        latency_ms = (time.time() - start) * 1000
                        if first_token:
                            print(f"[provider:groq] First token: {latency_ms:.0f}ms", file=sys.stderr)
                            first_token = False
                        yield {"type": "chunk", "text": text, "latency_ms": latency_ms}

                total = (time.time() - start) * 1000
                yield {"type": "done", "text": "".join(full_text), "latency_ms": total}

            except Exception as e:
                latency_ms = (time.time() - start) * 1000
                print(f"[provider:groq] Stream error: {e}", file=sys.stderr)
                msg = friendly_quota_message("groq") if is_quota_error(e) else f"Error: {e}"
                yield {"type": "error", "text": msg, "latency_ms": latency_ms}

        return _stream()

    def transcribe(self, wav_path: str, language: str = "en") -> str:
        from groq import RateLimitError

        try:
            try:
                with open(wav_path, "rb") as f:
                    resp = self.client.audio.transcriptions.create(
                        file=("audio.wav", f),
                        model=self.defaults["stt_model"],
                        language=language,
                        response_format="text",
                    )
            except RateLimitError:
                if not self.fallback_client:
                    raise
                print("[provider:groq] STT rate-limited, using fallback", file=sys.stderr)
                with open(wav_path, "rb") as f:
                    resp = self.fallback_client.audio.transcriptions.create(
                        file=("audio.wav", f),
                        model=self.defaults["stt_model"],
                        language=language,
                        response_format="text",
                    )
            return resp.strip() if isinstance(resp, str) else resp.text.strip()
        except Exception as e:
            print(f"[provider:groq] Transcribe error: {e}", file=sys.stderr)
            if is_quota_error(e):
                raise QuotaExceededError("groq", e)
            return ""


# ──────────────────────────────────────────────
# OpenAI Provider
# ──────────────────────────────────────────────
class OpenAIProvider(BaseProvider):
    """OpenAI — GPT-4o for chat/vision, Whisper for STT."""

    name = "openai"

    def __init__(self, api_key: str, fallback_key: str = None):
        super().__init__(api_key, fallback_key)
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key)
        self.defaults = PROVIDER_DEFAULTS["openai"]
        print("[provider] Initialized OpenAIProvider", file=sys.stderr)

    def chat_complete(self, messages, temperature=0.3, max_tokens=1200, stream=True):
        return self._complete(messages, self.defaults["chat_model"],
                              temperature, max_tokens, stream)

    def vision_complete(self, messages, temperature=0.3, max_tokens=1024, stream=True):
        return self._complete(messages, self.defaults["vision_model"],
                              temperature, max_tokens, stream)

    def _complete(self, messages, model, temperature, max_tokens, stream):
        start = time.time()
        api_args = dict(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
        )

        if not stream:
            try:
                resp = self.client.chat.completions.create(**api_args)
                return resp.choices[0].message.content.strip()
            except Exception as e:
                return f"Error: {e}"

        # Streaming
        def _stream():
            nonlocal start
            first_token = True
            full_text = []
            try:
                stream_resp = self.client.chat.completions.create(**api_args)
                for chunk in stream_resp:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        text = delta.content
                        full_text.append(text)
                        latency_ms = (time.time() - start) * 1000
                        if first_token:
                            print(f"[provider:openai] First token: {latency_ms:.0f}ms", file=sys.stderr)
                            first_token = False
                        yield {"type": "chunk", "text": text, "latency_ms": latency_ms}

                total = (time.time() - start) * 1000
                yield {"type": "done", "text": "".join(full_text), "latency_ms": total}

            except Exception as e:
                latency_ms = (time.time() - start) * 1000
                print(f"[provider:openai] Stream error: {e}", file=sys.stderr)
                msg = friendly_quota_message("openai") if is_quota_error(e) else f"Error: {e}"
                yield {"type": "error", "text": msg, "latency_ms": latency_ms}

        return _stream()

    def transcribe(self, wav_path: str, language: str = "en") -> str:
        try:
            with open(wav_path, "rb") as f:
                resp = self.client.audio.transcriptions.create(
                    file=f,
                    model=self.defaults["stt_model"],
                    language=language,
                    response_format="text",
                )
            return resp.strip() if isinstance(resp, str) else resp.text.strip()
        except Exception as e:
            print(f"[provider:openai] Transcribe error: {e}", file=sys.stderr)
            if is_quota_error(e):
                raise QuotaExceededError("openai", e)
            return ""


# ──────────────────────────────────────────────
# Claude (Anthropic) Provider
# ──────────────────────────────────────────────
class ClaudeProvider(BaseProvider):
    """Anthropic Claude — chat + vision, no native STT."""

    name = "claude"

    def __init__(self, api_key: str, fallback_key: str = None,
                 groq_key: str = None, groq_fallback_key: str = None):
        super().__init__(api_key, fallback_key)
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.defaults = PROVIDER_DEFAULTS["claude"]

        # Groq fallback for transcription
        self._groq_stt = None
        if groq_key:
            from groq import Groq
            self._groq_stt = Groq(api_key=groq_key)
            self._groq_stt_fallback = Groq(api_key=groq_fallback_key) if groq_fallback_key else None
        print("[provider] Initialized ClaudeProvider", file=sys.stderr)

    def chat_complete(self, messages, temperature=0.3, max_tokens=1200, stream=True):
        return self._complete(messages, self.defaults["chat_model"],
                              temperature, max_tokens, stream)

    def vision_complete(self, messages, temperature=0.3, max_tokens=1024, stream=True):
        return self._complete(messages, self.defaults["vision_model"],
                              temperature, max_tokens, stream)

    def _complete(self, messages, model, temperature, max_tokens, stream):
        """
        Anthropic uses a different message format:
        - system prompt is a top-level param, not in messages
        - no 'system' role in messages array
        """
        start = time.time()

        # Extract system prompt from messages
        system_text = ""
        user_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_text = msg["content"]
            else:
                # Convert OpenAI-style content to Anthropic format
                user_messages.append(self._convert_message(msg))

        api_args = dict(
            model=model,
            system=system_text,
            messages=user_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        if not stream:
            try:
                resp = self.client.messages.create(**api_args)
                text = resp.content[0].text.strip()
                return text
            except Exception as e:
                return f"Error: {e}"

        # Streaming
        def _stream():
            nonlocal start
            first_token = True
            full_text = []
            try:
                with self.client.messages.stream(**api_args) as stream_resp:
                    for text in stream_resp.text_stream:
                        full_text.append(text)
                        latency_ms = (time.time() - start) * 1000
                        if first_token:
                            print(f"[provider:claude] First token: {latency_ms:.0f}ms", file=sys.stderr)
                            first_token = False
                        yield {"type": "chunk", "text": text, "latency_ms": latency_ms}

                total = (time.time() - start) * 1000
                yield {"type": "done", "text": "".join(full_text), "latency_ms": total}

            except Exception as e:
                latency_ms = (time.time() - start) * 1000
                print(f"[provider:claude] Stream error: {e}", file=sys.stderr)
                msg = friendly_quota_message("claude") if is_quota_error(e) else f"Error: {e}"
                yield {"type": "error", "text": msg, "latency_ms": latency_ms}

        return _stream()

    def _convert_message(self, msg):
        """Convert OpenAI-format message to Anthropic format."""
        content = msg["content"]

        # If content is a string, keep as-is
        if isinstance(content, str):
            return {"role": msg["role"], "content": content}

        # If content is a list (multimodal), convert image_url to Anthropic's format
        anthropic_content = []
        for part in content:
            if part["type"] == "text":
                anthropic_content.append({"type": "text", "text": part["text"]})
            elif part["type"] == "image_url":
                url = part["image_url"]["url"]
                # Parse data URI: data:image/png;base64,xxxx
                if url.startswith("data:"):
                    media_type = url.split(";")[0].split(":")[1]
                    b64_data = url.split(",", 1)[1]
                    anthropic_content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": b64_data,
                        }
                    })
                else:
                    # URL-based image
                    anthropic_content.append({
                        "type": "image",
                        "source": {
                            "type": "url",
                            "url": url,
                        }
                    })

        return {"role": msg["role"], "content": anthropic_content}

    def transcribe(self, wav_path: str, language: str = "en") -> str:
        """Claude has no STT — falls back to Groq Whisper."""
        if not self._groq_stt:
            print("[provider:claude] No Groq key for STT, skipping transcription", file=sys.stderr)
            return ""

        try:
            from groq import RateLimitError
            try:
                with open(wav_path, "rb") as f:
                    resp = self._groq_stt.audio.transcriptions.create(
                        file=("audio.wav", f),
                        model="whisper-large-v3-turbo",
                        language=language,
                        response_format="text",
                    )
            except RateLimitError:
                if not self._groq_stt_fallback:
                    raise
                with open(wav_path, "rb") as f:
                    resp = self._groq_stt_fallback.audio.transcriptions.create(
                        file=("audio.wav", f),
                        model="whisper-large-v3-turbo",
                        language=language,
                        response_format="text",
                    )
            return resp.strip() if isinstance(resp, str) else resp.text.strip()
        except Exception as e:
            print(f"[provider:claude] STT error: {e}", file=sys.stderr)
            if is_quota_error(e):
                raise QuotaExceededError("claude (groq STT)", e)
            return ""

    @property
    def supports_transcription(self) -> bool:
        return self._groq_stt is not None


# ──────────────────────────────────────────────
# Factory
# ──────────────────────────────────────────────
def create_provider(name: str, **kwargs) -> BaseProvider:
    """
    Factory function to create the appropriate provider.

    Args:
        name: "groq", "openai", or "claude"
        **kwargs: Provider-specific args (api_key, fallback_key, groq_key, etc.)

    Returns:
        BaseProvider instance
    """
    name = name.lower().strip()
    if name == "groq":
        return GroqProvider(
            api_key=kwargs.get("api_key", ""),
            fallback_key=kwargs.get("fallback_key"),
        )
    elif name == "openai":
        return OpenAIProvider(
            api_key=kwargs.get("api_key", ""),
            fallback_key=kwargs.get("fallback_key"),
        )
    elif name == "claude":
        return ClaudeProvider(
            api_key=kwargs.get("api_key", ""),
            fallback_key=kwargs.get("fallback_key"),
            groq_key=kwargs.get("groq_key"),
            groq_fallback_key=kwargs.get("groq_fallback_key"),
        )
    else:
        raise ValueError(f"Unknown provider: {name}. Must be 'groq', 'openai', or 'claude'.")
