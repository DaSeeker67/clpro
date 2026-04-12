"""
transcriber.py — Groq Whisper STT integration.

Sends audio chunks (.wav files) to Groq's Whisper API for transcription.
Returns text with ~300-500ms latency per chunk.
"""

import os
import sys
import time

from groq import Groq, RateLimitError


# Whisper model — turbo variant is fastest
MODEL = "whisper-large-v3-turbo"


class Transcriber:
    """Transcribes audio chunks using Groq's Whisper API."""

    def __init__(self, api_key: str = None, fallback_key: str = None):
        """
        Args:
            api_key: Groq API key. If None, reads from GROQ_API_KEY env var.
            fallback_key: Fallback Groq API key used when primary is rate-limited.
        """
        self.client = Groq(api_key=api_key)
        self.fallback_client = Groq(api_key=fallback_key) if fallback_key else None
        self._total_calls = 0
        self._total_latency = 0.0
        print("[transcriber] Initialized with Groq Whisper", file=sys.stderr)

    def transcribe(self, wav_path: str, language: str = "en") -> dict:
        """
        Transcribe a .wav file.

        Args:
            wav_path: Path to the .wav audio file.
            language: Language code (default: English).

        Returns:
            dict with keys: text, duration_ms, success
        """
        if not os.path.exists(wav_path):
            return {"text": "", "duration_ms": 0, "success": False}

        start = time.time()
        try:
            try:
                with open(wav_path, "rb") as audio_file:
                    response = self.client.audio.transcriptions.create(
                        file=("audio.wav", audio_file),
                        model=MODEL,
                        language=language,
                        response_format="text",
                    )
            except RateLimitError:
                if not self.fallback_client:
                    raise
                print("[transcriber] Primary key rate-limited, switching to fallback", file=sys.stderr)
                with open(wav_path, "rb") as audio_file:
                    response = self.fallback_client.audio.transcriptions.create(
                        file=("audio.wav", audio_file),
                        model=MODEL,
                        language=language,
                        response_format="text",
                    )

            latency_ms = (time.time() - start) * 1000
            self._total_calls += 1
            self._total_latency += latency_ms

            text = response.strip() if isinstance(response, str) else response.text.strip()

            if text:
                print(f"[transcriber] ({latency_ms:.0f}ms) \"{text[:80]}{'...' if len(text) > 80 else ''}\"" , file=sys.stderr)

            return {
                "text": text,
                "duration_ms": latency_ms,
                "success": True,
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
