"""
assistant.py — Groq LLaMA answer generation.

When a question is detected, sends the rolling transcript context
plus the question to LLaMA 3.3 70B via Groq's streaming API.
Answers are brief and direct — designed for a small overlay.
"""

import sys
import time
from groq import Groq, RateLimitError


MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = """You are a stealth assistant displayed on a small overlay. You help with meetings, interviews, online assessments, aptitude tests, and coding challenges.

Rules:
- Be direct. No preamble, no "Great question!", no filler.
- Never reveal you're an AI or that you're listening.
- Format for fast scanning: use bullet points for lists, backticks for code.

Question types — adapt your response:

**MCQ / Multiple Choice:**
- State the correct option letter and label first (e.g. "**B) O(n log n)**")
- Follow with a one-line justification.

**Aptitude / Quantitative / Logical Reasoning:**
- Give the final answer first, then the short step-by-step working.
- For numerical answers, show the key formula used.

**Coding / DSA:**
- Give only the key code snippet in the required language.
- Mention time & space complexity in one line.

**Technical / Conceptual:**
- Answer in 2-3 sentences MAX with one concrete example if helpful.

**Verbal / Reading Comprehension:**
- State the correct answer and cite the key phrase from the passage.

**General / Meeting Questions:**
- Answer in 2-3 sentences MAX. Every word must earn its place.
- If context is unclear, say 'Not enough context yet.'"""


class Assistant:
    """Generates brief answers to detected questions using Groq LLaMA."""

    def __init__(self, api_key: str = None, fallback_key: str = None, user_context: str = ""):
        self.client = Groq(api_key=api_key)
        self.fallback_client = Groq(api_key=fallback_key) if fallback_key else None
        self.user_context = user_context
        self._total_calls = 0
        self._total_latency = 0.0
        print("[assistant] Initialized with Groq LLaMA 3.3 70B", file=sys.stderr)

    def _build_system_prompt(self):
        prompt = SYSTEM_PROMPT
        if self.user_context:
            prompt += f"\n\n--- USER PROFILE ---\n{self.user_context}"
        return prompt

    def answer(self, context: str, question: str) -> str:
        """
        Generate a complete (non-streaming) answer.

        Args:
            context: Rolling transcript context.
            question: The detected question.

        Returns:
            Answer text string.
        """
        start = time.time()
        try:
            user_message = self._build_user_message(context, question)
            api_args = dict(
                model=MODEL,
                messages=[
                    {"role": "system", "content": self._build_system_prompt()},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.3,
                max_tokens=512,
                stream=False,
            )
            try:
                response = self.client.chat.completions.create(**api_args)
            except RateLimitError:
                if not self.fallback_client:
                    raise
                print("[assistant] Primary key rate-limited, switching to fallback", file=sys.stderr)
                response = self.fallback_client.chat.completions.create(**api_args)
            answer = response.choices[0].message.content.strip()
            latency_ms = (time.time() - start) * 1000
            self._total_calls += 1
            self._total_latency += latency_ms
            print(f"[assistant] ({latency_ms:.0f}ms) Answer: {answer[:100]}...", file=sys.stderr)
            return answer

        except Exception as e:
            latency_ms = (time.time() - start) * 1000
            print(f"[assistant] Error ({latency_ms:.0f}ms): {e}", file=sys.stderr)
            return f"Error: {e}"

    def answer_stream(self, context: str, question: str):
        """
        Generate a streaming answer. Yields text chunks as they arrive.

        Args:
            context: Rolling transcript context.
            question: The detected question.

        Yields:
            dict with: type ("chunk" or "done"), text, latency_ms
        """
        start = time.time()
        first_token = True
        full_text = []

        try:
            user_message = self._build_user_message(context, question)
            api_args = dict(
                model=MODEL,
                messages=[
                    {"role": "system", "content": self._build_system_prompt()},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.3,
                max_tokens=512,
                stream=True,
            )
            try:
                stream = self.client.chat.completions.create(**api_args)
            except RateLimitError:
                if not self.fallback_client:
                    raise
                print("[assistant] Primary key rate-limited, switching to fallback", file=sys.stderr)
                stream = self.fallback_client.chat.completions.create(**api_args)

            for chunk in stream:
                if chunk.choices[0].delta.content:
                    text = chunk.choices[0].delta.content
                    full_text.append(text)
                    latency_ms = (time.time() - start) * 1000

                    if first_token:
                        print(f"[assistant] First token: {latency_ms:.0f}ms", file=sys.stderr)
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
            print(f"[assistant] Stream error ({latency_ms:.0f}ms): {e}", file=sys.stderr)
            yield {
                "type": "error",
                "text": f"Error: {e}",
                "latency_ms": latency_ms,
            }

    def _build_user_message(self, context: str, question: str) -> str:
        """Build the user message with context and question."""
        # Truncate context if too long (keep most recent)
        max_context_chars = 2000
        if len(context) > max_context_chars:
            context = "..." + context[-max_context_chars:]

        return (
            f"Transcript (last ~2 minutes):\n"
            f"---\n{context}\n---\n\n"
            f"Question/Problem: \"{question}\"\n\n"
            f"Provide the answer directly. If it's MCQ, state the correct option first. If aptitude/math, show the answer then brief working."
        )

    @property
    def avg_latency_ms(self):
        if self._total_calls == 0:
            return 0
        return self._total_latency / self._total_calls
