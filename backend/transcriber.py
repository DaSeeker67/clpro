"""
transcriber.py — Speech-to-text integration (provider-agnostic).

Sends audio chunks (.wav files) to the configured provider's STT API.
For providers without native STT (e.g. Claude), falls back to Groq Whisper.
"""

import os
import sys
import time

from provider import BaseProvider, QuotaExceededError


class Transcriber:
    """Transcribes audio chunks using the configured AI provider's STT API."""

    def __init__(self, provider: BaseProvider):
        """
        Args:
            provider: AI provider instance (handles STT routing internally).
        """
        self.provider = provider
        self._total_calls = 0
        self._total_latency = 0.0
        self._quota_warned = False  # Only show quota error once, not per chunk
        stt_info = "native" if provider.supports_transcription else "Groq fallback"
        print(f"[transcriber] Initialized with {provider.name} provider ({stt_info})", file=sys.stderr)

    def transcribe(self, wav_path: str, language: str = "en") -> dict:
        """
        Transcribe a .wav file.

        Args:
            wav_path: Path to the .wav audio file.
            language: Language code (default: English).

        Returns:
            dict with keys: text, duration_ms, success, quota_error (optional)
        """
        if not os.path.exists(wav_path):
            return {"text": "", "duration_ms": 0, "success": False}

        start = time.time()
        try:
            text = self.provider.transcribe(wav_path, language)
            latency_ms = (time.time() - start) * 1000
            self._total_calls += 1
            self._total_latency += latency_ms
            self._quota_warned = False  # Reset on success

            if text:
                print(f"[transcriber] ({latency_ms:.0f}ms) \"{text[:80]}{'...' if len(text) > 80 else ''}\"", file=sys.stderr)

            return {
                "text": text,
                "duration_ms": latency_ms,
                "success": bool(text),
            }

        except QuotaExceededError as e:
            latency_ms = (time.time() - start) * 1000
            if not self._quota_warned:
                print(f"[transcriber] QUOTA EXCEEDED ({latency_ms:.0f}ms): {e}", file=sys.stderr)
                self._quota_warned = True
            return {
                "text": "",
                "duration_ms": latency_ms,
                "success": False,
                "quota_error": str(e),
            }

        except Exception as e:
            latency_ms = (time.time() - start) * 1000
            print(f"[transcriber] Error ({latency_ms:.0f}ms): {e}", file=sys.stderr)
            return {
                "text": "",
                "duration_ms": latency_ms,
                "success": False,
            }

    @property
    def avg_latency_ms(self):
        if self._total_calls == 0:
            return 0
        return self._total_latency / self._total_calls

    def cleanup_chunk(self, wav_path: str):
        """Delete a processed chunk file."""
        try:
            if os.path.exists(wav_path):
                os.remove(wav_path)
        except OSError:
            pass
