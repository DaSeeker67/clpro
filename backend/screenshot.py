"""
screenshot.py -- Screen capture + vision AI analysis (provider-agnostic).

Takes a screenshot, sends it to the configured AI provider's vision model,
and returns an AI-generated answer about what's on screen.
"""

import sys
import os
import time
import base64

from provider import BaseProvider


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
    """Captures and analyzes screenshots using the configured AI provider's vision API."""

    def __init__(self, provider: BaseProvider):
        self.provider = provider
        self._total_calls = 0
        self._total_latency = 0.0
        print(f"[screenshot] Initialized with {provider.name} provider", file=sys.stderr)

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

        try:
            # Read and base64 encode the image
            with open(image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")

            # Determine mime type
            ext = os.path.splitext(image_path)[1].lower()
            mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
            mime_type = mime_map.get(ext, "image/png")

            user_text = custom_prompt or USER_PROMPT

            # Build messages in OpenAI-compatible format
            # (provider.py handles conversion for Claude)
            messages = [
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
            ]

            for chunk in self.provider.vision_complete(
                messages, temperature=0.3, max_tokens=1024, stream=True
            ):
                if chunk["type"] == "done":
                    self._total_calls += 1
                    self._total_latency += chunk["latency_ms"]
                yield chunk

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
