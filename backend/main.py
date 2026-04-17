"""
main.py — Backend orchestrator for Cluely Pro.

Wires the full pipeline: audio capture -> VAD chunker -> Whisper STT ->
context manager -> LLaMA assistant. Runs in the terminal for Phase 1,
or as a child process for Electron (Phase 2).

Usage:
    python main.py              # interactive terminal mode
    python main.py --ipc        # JSON-line IPC mode (for Electron)
"""

import os
import sys
import io
import json
import queue
import signal
import threading
import argparse
import time

# Force UTF-8 encoding for stdout/stderr (critical when spawned from Electron)
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from dotenv import load_dotenv

from audio_capture import AudioCapture
from chunker import AudioChunker
from transcriber import Transcriber
from context_manager import ContextManager
from assistant import Assistant
from screenshot import ScreenshotAnalyzer

# Load .env from project root (or next to exe when packaged)
if getattr(sys, 'frozen', False):
    # Running as PyInstaller bundle
    _base = os.path.dirname(sys.executable)
    _env_path = os.path.join(_base, "..", ".env")
else:
    _env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(_env_path)


# ──────────────────────────────────────────────
# Color output helpers (terminal mode only)
# ──────────────────────────────────────────────
class Colors:
    RESET = "\033[0m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    MAGENTA = "\033[35m"
    RED = "\033[31m"


def print_colored(prefix, color, text):
    """Print colored output to stderr (so stdout stays clean for IPC)."""
    print(f"{color}{Colors.BOLD}[{prefix}]{Colors.RESET} {text}", file=sys.stderr)


def print_transcript(text):
    print_colored("TRANSCRIPT", Colors.CYAN, text)


def print_question(text):
    print_colored("QUESTION", Colors.YELLOW, text)


def print_answer(text):
    print_colored("ANSWER", Colors.GREEN, text)


def print_status(text):
    print_colored("STATUS", Colors.DIM, text)


# ──────────────────────────────────────────────
# IPC (JSON-line communication with Electron)
# ──────────────────────────────────────────────
def emit_ipc(msg_type: str, **kwargs):
    """Send a JSON-line message to stdout (read by Electron main process)."""
    msg = {"type": msg_type, **kwargs}
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


# ──────────────────────────────────────────────
# Main pipeline
# ──────────────────────────────────────────────
class CopilotPipeline:
    """
    Main orchestrator tying all components together.
    """

    def __init__(self, ipc_mode: bool = False):
        self.ipc_mode = ipc_mode
        self._running = False
        self._initialized = False

        # Shared chunk queue (both sources feed into this)
        self.chunk_queue = queue.Queue()   # .wav file paths

        # Separate audio queues per source (keeps VAD state independent)
        self.audio_queue_loopback = queue.Queue()
        self.audio_queue_mic = queue.Queue()

        # State
        self._listening = True
        self._threads = []

        # Components
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key or api_key == "your_key_here":
            msg = "No API key set. Please add your Groq API key in Settings."
            print(f"ERROR: {msg}", file=sys.stderr)
            if self.ipc_mode:
                emit_ipc("answer_error", text=msg)
                # Keep running so user can set key via settings and restart
                return
            else:
                sys.exit(1)
        fallback_key = os.getenv("GROQ_API_fallback")
        user_context = os.getenv("CLUELY_USER_CONTEXT", "")

        # Dual audio capture: loopback (speaker) + microphone
        self.capture_loopback = AudioCapture(self.audio_queue_loopback, mode="loopback")
        # self.capture_mic = AudioCapture(self.audio_queue_mic, mode="mic")
        self.chunker_loopback = AudioChunker(self.audio_queue_loopback, self.chunk_queue)
        # self.chunker_mic = AudioChunker(self.audio_queue_mic, self.chunk_queue)

        self.transcriber = Transcriber(api_key=api_key, fallback_key=fallback_key)
        self.context = ContextManager()
        self.assistant = Assistant(api_key=api_key, fallback_key=fallback_key, user_context=user_context)
        self.screenshotter = ScreenshotAnalyzer(api_key=api_key, fallback_key=fallback_key)

        self._initialized = True

    def start(self):
        """Start all pipeline components."""
        self._running = True

        if not getattr(self, '_initialized', False):
            # No API key — just listen for quit command in IPC mode
            if self.ipc_mode:
                stdin_thread = threading.Thread(target=self._stdin_listener, daemon=True)
                stdin_thread.start()
                self._threads.append(stdin_thread)
            return

        if self.ipc_mode:
            emit_ipc("status", text="Starting pipeline...")
        else:
            print_status("Starting Cluely Pro...")
            print_status("Press Ctrl+Shift+H to toggle listening")
            print_status("Press Ctrl+Shift+A to force-answer on last 10s")
            print_status("Press Ctrl+C to exit")
            print()

        # Start audio capture — try both loopback and mic independently
        loopback_ok = False

        try:
            self.capture_loopback.start()
            loopback_ok = True
        except Exception as e:
            print(f"[pipeline] Speaker/loopback capture failed: {e}", file=sys.stderr)

        if not loopback_ok:
            error_msg = "System audio (WASAPI loopback) failed"
            print(f"[ERROR] {error_msg}", file=sys.stderr)
            if self.ipc_mode:
                emit_ipc("status", text="Audio failed - screenshot mode only (Ctrl+G)")
            else:
                print_status("Audio failed — screenshot mode still works")
        else:
            print(f"[pipeline] Audio source active: speaker", file=sys.stderr)
            if self.ipc_mode:
                emit_ipc("status", text="Capturing: speaker")

            chunker_thread_lb = threading.Thread(target=self.chunker_loopback.run, daemon=True)
            chunker_thread_lb.start()
            self._threads.append(chunker_thread_lb)

            # Start transcription consumer in a thread
            transcribe_thread = threading.Thread(target=self._transcription_loop, daemon=True)
            transcribe_thread.start()
            self._threads.append(transcribe_thread)

        # Start hotkey listener (terminal mode only)
        if not self.ipc_mode:
            hotkey_thread = threading.Thread(target=self._hotkey_listener, daemon=True)
            hotkey_thread.start()
            self._threads.append(hotkey_thread)
        else:
            # In IPC mode, listen for commands from stdin
            stdin_thread = threading.Thread(target=self._stdin_listener, daemon=True)
            stdin_thread.start()
            self._threads.append(stdin_thread)

        if self.ipc_mode:
            emit_ipc("status", text="Pipeline running")

    def _transcription_loop(self):
        """Consume chunks from the chunk queue, transcribe, and process."""
        while self._running:
            try:
                chunk_path = self.chunk_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if not self._listening:
                self.transcriber.cleanup_chunk(chunk_path)
                continue

            # Transcribe
            result = self.transcriber.transcribe(chunk_path)
            self.transcriber.cleanup_chunk(chunk_path)

            if not result["success"] or not result["text"]:
                continue

            text = result["text"]

            # Emit transcript
            if self.ipc_mode:
                emit_ipc("transcript", text=text)
            else:
                print_transcript(text)

            # Process through context manager
            ctx_result = self.context.add_transcript(text)

            if ctx_result["is_question"]:
                question = ctx_result["question"]
                context = ctx_result["context"]

                if self.ipc_mode:
                    emit_ipc("question", text=question)
                else:
                    print_question(question)

                # Generate answer (streaming)
                self._generate_answer(context, question)

    def _generate_answer(self, context: str, question: str):
        """Generate and emit a streamed answer."""
        if self.ipc_mode:
            # Stream to IPC
            emit_ipc("answer_start", question=question)
            full_text = ""
            for chunk in self.assistant.answer_stream(context, question):
                if chunk["type"] == "chunk":
                    full_text += chunk["text"]
                    emit_ipc("answer_chunk", text=chunk["text"])
                elif chunk["type"] == "done":
                    emit_ipc("answer_done", text=full_text, latency_ms=chunk["latency_ms"])
                elif chunk["type"] == "error":
                    emit_ipc("answer_error", text=chunk["text"])
        else:
            # Terminal: stream to stderr
            sys.stderr.write(f"\n{Colors.GREEN}{Colors.BOLD}[ANSWER]{Colors.RESET} ")
            full_text = ""
            for chunk in self.assistant.answer_stream(context, question):
                if chunk["type"] == "chunk":
                    sys.stderr.write(chunk["text"])
                    sys.stderr.flush()
                    full_text += chunk["text"]
                elif chunk["type"] == "done":
                    sys.stderr.write(f"\n{Colors.DIM}({chunk['latency_ms']:.0f}ms){Colors.RESET}\n\n")
                    sys.stderr.flush()
                elif chunk["type"] == "error":
                    sys.stderr.write(f"\n{Colors.RED}Error: {chunk['text']}{Colors.RESET}\n\n")
                    sys.stderr.flush()

    def _hotkey_listener(self):
        """Listen for hotkeys using pynput (terminal mode)."""
        try:
            from pynput import keyboard

            # Track pressed keys
            pressed = set()

            def on_press(key):
                pressed.add(key)
                # Ctrl+Shift+H — toggle listening
                if (keyboard.Key.ctrl_l in pressed or keyboard.Key.ctrl_r in pressed) and \
                   (keyboard.Key.shift in pressed or keyboard.Key.shift_l in pressed or keyboard.Key.shift_r in pressed):
                    try:
                        if hasattr(key, 'char') and key.char == 'h':
                            self._toggle_listening()
                        elif hasattr(key, 'char') and key.char == 'a':
                            self._force_answer()
                    except AttributeError:
                        pass

            def on_release(key):
                pressed.discard(key)

            with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
                listener.join()

        except ImportError:
            print_status("pynput not installed — hotkeys disabled")

    def _stdin_listener(self):
        """Listen for JSON commands from Electron (IPC mode)."""
        while self._running:
            try:
                line = sys.stdin.readline()
                if not line:
                    break
                msg = json.loads(line.strip())
                cmd = msg.get("command")
                if cmd == "toggle":
                    self._toggle_listening()
                elif cmd == "force_answer":
                    self._force_answer()
                elif cmd == "screenshot":
                    image_path = msg.get("image_path", "")
                    if image_path:
                        self._analyze_screenshot(image_path)
                elif cmd == "chat":
                    prompt = msg.get("prompt", "")
                    if prompt:
                        self._handle_chat(prompt)
                elif cmd == "set_user_context":
                    ctx = msg.get("user_context", "")[:1000]
                    if hasattr(self, 'assistant'):
                        self.assistant.user_context = ctx
                        print(f"[pipeline] User context updated ({len(ctx)} chars)", file=sys.stderr)
                elif cmd == "quit":
                    self.stop()
            except (json.JSONDecodeError, Exception):
                continue

    def _toggle_listening(self):
        """Toggle listening on/off."""
        self._listening = not self._listening
        state = "ON" if self._listening else "OFF"
        if self.ipc_mode:
            emit_ipc("listening", state=state)
        else:
            print_status(f"Listening: {state}")

    def _force_answer(self):
        """Force an answer on the last 10 seconds of audio."""
        result = self.context.force_question(lookback_seconds=10)
        if result["is_question"]:
            if not self.ipc_mode:
                print_question(f"[FORCED] {result['question'][:80]}...")
            self._generate_answer(result["context"], result["question"])
        else:
            if self.ipc_mode:
                emit_ipc("status", text="No recent context to answer")
            else:
                print_status("No recent context to answer")

    def _analyze_screenshot(self, image_path: str):
        """Analyze a screenshot using vision AI."""
        if self.ipc_mode:
            emit_ipc("answer_start", question="[Screenshot Analysis]")
            full_text = ""
            for chunk in self.screenshotter.analyze_screenshot(image_path):
                if chunk["type"] == "chunk":
                    full_text += chunk["text"]
                    emit_ipc("answer_chunk", text=chunk["text"])
                elif chunk["type"] == "done":
                    emit_ipc("answer_done", text=full_text, latency_ms=chunk["latency_ms"])
                elif chunk["type"] == "error":
                    emit_ipc("answer_error", text=chunk["text"])
        else:
            sys.stderr.write(f"\n{Colors.MAGENTA}{Colors.BOLD}[SCREENSHOT]{Colors.RESET} Analyzing...\n")
            sys.stderr.write(f"{Colors.GREEN}{Colors.BOLD}[ANSWER]{Colors.RESET} ")
            for chunk in self.screenshotter.analyze_screenshot(image_path):
                if chunk["type"] == "chunk":
                    sys.stderr.write(chunk["text"])
                    sys.stderr.flush()
                elif chunk["type"] == "done":
                    sys.stderr.write(f"\n{Colors.DIM}({chunk['latency_ms']:.0f}ms){Colors.RESET}\n\n")
                    sys.stderr.flush()
                elif chunk["type"] == "error":
                    sys.stderr.write(f"\n{Colors.RED}Error: {chunk['text']}{Colors.RESET}\n\n")
                    sys.stderr.flush()

        # Cleanup temp file
        try:
            if os.path.exists(image_path):
                os.remove(image_path)
        except OSError:
            pass

    def _handle_chat(self, prompt: str):
        """Handle a direct chat prompt from the user."""
        # Use any available meeting context
        context = self.context.get_context() if self.context.segment_count > 0 else ""
        self._generate_answer(context, prompt)

    def stop(self):
        """Stop all pipeline components."""
        self._running = False
        self.capture_loopback.stop()
        self.chunker_loopback.stop()
        self.chunker_loopback.cleanup()

        if self.ipc_mode:
            emit_ipc("status", text="Pipeline stopped")
        else:
            print()
            print_status("Cluely Pro stopped")
            print_status(f"Transcriber avg latency: {self.transcriber.avg_latency_ms:.0f}ms")
            print_status(f"Assistant avg latency: {self.assistant.avg_latency_ms:.0f}ms")
            print_status(f"Total segments processed: {self.context.segment_count}")

    def wait(self):
        """Block until stopped (Ctrl+C or quit command)."""
        try:
            while self._running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()


def main():
    parser = argparse.ArgumentParser(description="Cluely Pro — Stealth Meeting Copilot")
    parser.add_argument("--ipc", action="store_true", help="Run in IPC mode (JSON-line stdin/stdout)")
    args = parser.parse_args()

    pipeline = CopilotPipeline(ipc_mode=args.ipc)

    # Handle graceful shutdown
    def signal_handler(sig, frame):
        pipeline.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    pipeline.start()
    pipeline.wait()


if __name__ == "__main__":
    main()
