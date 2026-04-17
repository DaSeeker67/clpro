"""
assistant.py — AI answer generation (provider-agnostic).

When a question is detected, sends the rolling transcript context
plus the question to the configured AI provider's streaming API.
Answers are brief and direct — designed for a small overlay.
"""

import sys
import time

from provider import BaseProvider


SYSTEM_PROMPT = """\
You are an expert technical copilot running as a stealth overlay during coding interviews, online assessments, and technical rounds. Your job is to give COMPLETE, WORKING, CORRECT answers — not hints.

CRITICAL RULES:
- NEVER say just "the answer is yes" or give a one-liner for a coding/DSA problem.
- NEVER give a partial answer. If it's a coding problem, write the FULL working function.
- NEVER explain what you're going to do — just do it.
- Do NOT reveal you are an AI or listening.
- Format for fast reading: headers, bullets, fenced code blocks.

━━━ CODING / DSA / ALGORITHM PROBLEMS ━━━
When a coding problem is detected (mentions array, tree, graph, string, DP, recursion, two pointers, binary search, complexity, function, implement, write, code, return, input/output, etc.):
1. **Intuition** (2-3 lines max): The core idea / pattern being used.
2. **Approach**: Step-by-step algorithm in plain English (3-6 bullets).
3. **Code**: Full working solution in the language asked (default Python). Correct, runnable, handles edge cases.
4. **Dry Run**: Trace through the given example input step by step to prove correctness.
5. **Complexity**: Time: O(...) | Space: O(...) with one-line justification.

━━━ MCQ / MULTIPLE CHOICE ━━━
- State the correct option letter+label first: **B) O(n log n)**
- One-line justification. Nothing else.

━━━ APTITUDE / MATH / QUANTITATIVE ━━━
- Final answer first, then step-by-step working showing key formula.
- Keep it under 6 lines.

━━━ CONCEPTUAL / TECHNICAL ━━━
- 2-4 sentences with one concrete example. No fluff.

━━━ BEHAVIORAL / GENERAL MEETING ━━━
- 2-3 sharp sentences. Every word must earn its place.
- If context is too unclear: say exactly "Not enough context yet — please repeat the question."
"""


class Assistant:
    """Generates brief answers to detected questions using the configured AI provider."""

    def __init__(self, provider: BaseProvider, user_context: str = ""):
        self.provider = provider
        self.user_context = user_context
        self._total_calls = 0
        self._total_latency = 0.0
        print(f"[assistant] Initialized with {provider.name} provider", file=sys.stderr)

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
            messages = [
                {"role": "system", "content": self._build_system_prompt()},
                {"role": "user", "content": user_message},
            ]
            answer = self.provider.chat_complete(
                messages, temperature=0.3, max_tokens=1200, stream=False
            )
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
        try:
            user_message = self._build_user_message(context, question)
            messages = [
                {"role": "system", "content": self._build_system_prompt()},
                {"role": "user", "content": user_message},
            ]
            for chunk in self.provider.chat_complete(
                messages, temperature=0.3, max_tokens=1200, stream=True
            ):
                # Track stats on completion
                if chunk["type"] == "done":
                    self._total_calls += 1
                    self._total_latency += chunk["latency_ms"]
                yield chunk

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
        max_context_chars = 3000
        if len(context) > max_context_chars:
            context = "..." + context[-max_context_chars:]

        # Detect problem type to give the model a stronger hint
        q_lower = question.lower()
        coding_keywords = [
            "array", "string", "tree", "graph", "linked list", "stack", "queue",
            "dp", "dynamic programming", "recursion", "binary search", "two pointer",
            "sliding window", "hash", "sort", "implement", "function", "algorithm",
            "complexity", "return", "input", "output", "code", "write a", "program",
            "subarray", "subsequence", "matrix", "heap", "trie", "backtrack",
        ]
        is_coding = any(kw in q_lower for kw in coding_keywords)

        if is_coding:
            type_hint = (
                "This is a CODING/DSA problem. You MUST provide:\n"
                "1. Intuition (what pattern/technique applies)\n"
                "2. Step-by-step approach\n"
                "3. Full working code (Python unless another language is specified)\n"
                "4. Dry run on the example input shown\n"
                "5. Time & Space complexity\n"
                "Do NOT give a one-liner answer. Write the complete solution."
            )
        else:
            type_hint = "Answer directly and concisely. If MCQ, state the option first. If math/aptitude, show working."

        return (
            f"Recent transcript (last ~2 min):\n"
            f"---\n{context}\n---\n\n"
            f"Question/Problem:\n\"{question}\"\n\n"
            f"{type_hint}"
        )

    @property
    def avg_latency_ms(self):
        if self._total_calls == 0:
            return 0
        return self._total_latency / self._total_calls
