"""
screenshot.py -- Screen capture + vision AI analysis.

Takes a screenshot, sends it to Groq's vision model (LLaMA 3.2 Vision),
and returns an AI-generated answer about what's on screen.
"""

import sys
import os
import time
import base64
import tempfile

from groq import Groq, RateLimitError


VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

SYSTEM_PROMPT = """You are an expert problem-solving assistant embedded in a screen overlay. When the user captures their screen, your job is to SOLVE, ANSWER, or FIX whatever is visible -- NOT to describe or extract what you see.

STRICT RULES:
- NEVER just list or repeat text from the screen. The user can already read it.
- NEVER say "I can see...", "The screen shows...", "There is a..." or similar descriptions.
- ALWAYS provide the SOLUTION, ANSWER, or EXPLANATION directly.
- Be concise but complete. Use bullet points and backticks for code.

SCENARIO-SPECIFIC:
- **MCQ / Multiple Choice** -> State the correct option letter + label first (e.g. "**B) O(n log n)**"), then a one-line justification. If multiple MCQs are visible, answer ALL of them in order.
- **Aptitude / Quantitative / Logical Reasoning** -> Give the final numerical answer first, then brief step-by-step working with the key formula.
- **Coding challenge / DSA** -> Provide the complete solution code. Mention time & space complexity.
- **Code with a bug** -> Provide the fix with corrected code.
- **Error message** -> Explain root cause and exact steps to fix.
- **Reading comprehension / verbal** -> State the correct answer and cite the key phrase.
- **Online Assessment (OA)** -> Answer every visible question. Number your answers to match the question numbers on screen.
- **Meeting slide** -> Extract key actionable takeaways only."""

USER_PROMPT = "Analyze this screenshot. DO NOT describe or extract text. SOLVE every problem and ANSWER every question visible. For MCQs, state the correct option. For aptitude/math, give the answer with brief working. For coding, give the full solution. Answer ALL visible questions."


class ScreenshotAnalyzer:
    """Captures and analyzes screenshots using Groq Vision API."""

    def __init__(self, api_key: str = None, fallback_key: str = None):
        self.client = Groq(api_key=api_key)
        self.fallback_client = Groq(api_key=fallback_key) if fallback_key else None
        self._total_calls = 0
        self._total_latency = 0.0
        print("[screenshot] Initialized with Groq Vision", file=sys.stderr)

    def analyze_screenshot(self, image_path: str, custom_prompt: str = None):
        """
        Analyze a screenshot image.

        Args:
            image_path: Path to the screenshot image file.
            custom_prompt: Optional custom prompt override.

        Yields:
            dict with: type ("chunk" or "done" or "error"), text, latency_ms
        """
        start = time.time()
        first_token = True
        full_text = []

        try:
            # Read and base64 encode the image
            with open(image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")

            # Determine mime type
            ext = os.path.splitext(image_path)[1].lower()
            mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
            mime_type = mime_map.get(ext, "image/png")

            user_text = custom_prompt or USER_PROMPT

            api_args = dict(
                model=VISION_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT,
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_text},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime_type};base64,{image_data}",
                                },
                            },
                        ],
                    }
                ],
                temperature=0.3,
                max_tokens=1024,
                stream=True,
            )
            try:
                stream = self.client.chat.completions.create(**api_args)
            except RateLimitError:
                if not self.fallback_client:
                    raise
                print("[screenshot] Primary key rate-limited, switching to fallback", file=sys.stderr)
                stream = self.fallback_client.chat.completions.create(**api_args)

            for chunk in stream:
                if chunk.choices[0].delta.content:
                    text = chunk.choices[0].delta.content
                    full_text.append(text)
                    latency_ms = (time.time() - start) * 1000

                    if first_token:
                        print(f"[screenshot] First token: {latency_ms:.0f}ms", file=sys.stderr)
                        first_token = False

                    yield {
                        "type": "chunk",
                        "text": text,
                        "latency_ms": latency_ms,
                    }

            total_latency = (time.time() - start) * 1000
            self._total_calls += 1
            self._total_latency += total_latency

            yield {
                "type": "done",
                "text": "".join(full_text),
                "latency_ms": total_latency,
            }

        except Exception as e:
            latency_ms = (time.time() - start) * 1000
            print(f"[screenshot] Error ({latency_ms:.0f}ms): {e}", file=sys.stderr)
            yield {
                "type": "error",
                "text": f"Error: {e}",
                "latency_ms": latency_ms,
            }

    @property
    def avg_latency_ms(self):
        if self._total_calls == 0:
            return 0
        return self._total_latency / self._total_calls
