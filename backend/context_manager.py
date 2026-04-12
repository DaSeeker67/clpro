"""
context_manager.py — Rolling transcript buffer + question detection.

Maintains a sliding window of recent transcript text (~120 seconds)
and detects when a question has been asked, triggering the assistant.
"""

import re
import sys
import time
from collections import deque


# How many seconds of transcript to keep
CONTEXT_WINDOW_SECONDS = 120

# Trigger phrases that indicate a question (even without ?)
QUESTION_TRIGGERS = [
    # General question starters
    "can you", "could you", "would you",
    "what is", "what are", "what was", "what were", "what do", "what does",
    "how do", "how does", "how is", "how are", "how can", "how would",
    "how many", "how much",
    "why is", "why are", "why do", "why does", "why did",
    "when is", "when are", "when do", "when does", "when did",
    "where is", "where are", "where do", "where does",
    "who is", "who are", "who does", "who did",
    "which is", "which are", "which of", "which one",
    "is it", "is there", "are there", "do you", "does it",
    "explain", "tell me about", "describe",
    "any questions", "thoughts on", "opinion on",
    # MCQ / OA / Aptitude triggers
    "the answer is", "correct answer", "correct option",
    "option a", "option b", "option c", "option d",
    "choose the", "select the", "pick the",
    "find the value", "find the number", "calculate",
    "solve", "evaluate", "simplify", "compute",
    "the value of", "the result of",
    "which of the following", "all of the above", "none of the above",
    "true or false", "is true", "is false",
    "the output", "what will be the output", "what is the output",
    "time complexity", "space complexity",
    "given that", "if the",
    "ratio", "percentage", "probability", "average",
    "profit", "loss", "interest", "speed", "distance",
]

# Minimum time between question triggers (avoid spamming the LLM)
QUESTION_COOLDOWN_SECONDS = 8


class TranscriptSegment:
    """A single transcribed segment with timestamp."""

    def __init__(self, text: str, timestamp: float = None):
        self.text = text
        self.timestamp = timestamp or time.time()

    def __repr__(self):
        return f"Segment({self.text[:40]}..., {self.timestamp:.0f})"


class ContextManager:
    """
    Manages rolling transcript and detects questions.
    """

    def __init__(self, window_seconds: int = CONTEXT_WINDOW_SECONDS):
        self.window_seconds = window_seconds
        self.segments: deque[TranscriptSegment] = deque()
        self._last_question_time = 0
        self._total_segments = 0
        print(f"[context] Initialized ({window_seconds}s window)", file=sys.stderr)

    def add_transcript(self, text: str) -> dict:
        """
        Add a new transcript segment and check for questions.

        Args:
            text: Transcribed text from the latest audio chunk.

        Returns:
            dict with:
                - context: full rolling transcript string
                - question: detected question string, or None
                - is_question: bool
        """
        text = text.strip()
        if not text:
            return {"context": self.get_context(), "question": None, "is_question": False}

        segment = TranscriptSegment(text)
        self.segments.append(segment)
        self._total_segments += 1

        # Prune old segments
        self._prune()

        # Check for questions
        question = self._detect_question(text)

        return {
            "context": self.get_context(),
            "question": question,
            "is_question": question is not None,
        }

    def get_context(self) -> str:
        """Get the full rolling transcript as a single string."""
        return " ".join(seg.text for seg in self.segments)

    def get_recent(self, seconds: int = 30) -> str:
        """Get transcript from the last N seconds."""
        cutoff = time.time() - seconds
        return " ".join(
            seg.text for seg in self.segments if seg.timestamp >= cutoff
        )

    def _prune(self):
        """Remove segments older than the context window."""
        cutoff = time.time() - self.window_seconds
        while self.segments and self.segments[0].timestamp < cutoff:
            self.segments.popleft()

    def _detect_question(self, text: str) -> str | None:
        """
        Detect if the latest text contains a question.
        Returns the question text, or None.
        """
        now = time.time()
        if now - self._last_question_time < QUESTION_COOLDOWN_SECONDS:
            return None

        text_lower = text.lower().strip()

        # Direct question mark
        if "?" in text:
            self._last_question_time = now
            # Extract the sentence containing ?
            sentences = re.split(r'(?<=[.!?])\s+', text)
            questions = [s for s in sentences if "?" in s]
            if questions:
                return questions[-1].strip()  # Return the last question
            return text

        # Trigger phrase detection
        for trigger in QUESTION_TRIGGERS:
            if trigger in text_lower:
                self._last_question_time = now
                # Try to extract the relevant sentence
                sentences = re.split(r'(?<=[.!])\s+', text)
                for sentence in reversed(sentences):
                    if trigger in sentence.lower():
                        return sentence.strip()
                return text

        return None

    def force_question(self, lookback_seconds: int = 10) -> dict:
        """
        Force-trigger a question on the most recent audio.
        Used for manual trigger mode (hotkey).
        """
        recent = self.get_recent(lookback_seconds)
        if recent:
            self._last_question_time = time.time()
            return {
                "context": self.get_context(),
                "question": recent,
                "is_question": True,
            }
        return {"context": self.get_context(), "question": None, "is_question": False}

    @property
    def segment_count(self):
        return len(self.segments)
