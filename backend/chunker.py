"""
chunker.py -- VAD-based audio chunking.

Consumes raw PCM frames from the audio capture queue, runs WebRTC VAD
to detect speech, and produces audio chunks split on silence boundaries.
Each chunk is saved as a temporary .wav file for the transcriber.
"""

import os
import sys
import struct
import tempfile
import time
import queue
from collections import deque

import numpy as np
import soundfile as sf

try:
    import webrtcvad
except ImportError:
    webrtcvad = None
    print("[chunker] WARNING: webrtcvad not installed, using energy-based VAD fallback", file=sys.stderr)

SAMPLE_RATE = 16000
FRAME_DURATION_MS = 30
FRAME_SIZE = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)  # 480 samples

# Chunking parameters
VAD_AGGRESSIVENESS = 2          # 0-3, higher = more aggressive filtering
SILENCE_THRESHOLD_MS = 500      # ms of silence to trigger chunk flush
MIN_CHUNK_DURATION_S = 1.0      # minimum chunk length (seconds)
MAX_CHUNK_DURATION_S = 15.0     # maximum chunk length before forced flush
PRE_SPEECH_BUFFER_MS = 300      # ms of audio to keep before speech starts
CHUNK_MAX_AGE_S = 90 * 60      # delete chunks older than 1.5 hours (5400 s)
CHUNK_CLEANUP_INTERVAL_S = 300  # run cleanup sweep every 5 minutes


class EnergyVAD:
    """Fallback VAD using simple energy thresholding."""

    def __init__(self, threshold=500):
        self.threshold = threshold

    def is_speech(self, frame_bytes, sample_rate):
        samples = np.frombuffer(frame_bytes, dtype=np.int16)
        energy = np.sqrt(np.mean(samples.astype(np.float64) ** 2))
        return energy > self.threshold


class AudioChunker:
    """
    Reads audio frames from a queue, applies VAD, and produces
    speech chunks as temporary .wav files.
    """

    def __init__(self, audio_queue: queue.Queue, chunk_queue: queue.Queue):
        """
        Args:
            audio_queue: Input queue of raw PCM bytes (30ms frames of int16).
            chunk_queue: Output queue of file paths to .wav chunks.
        """
        import threading
        self.audio_queue = audio_queue
        self.chunk_queue = chunk_queue
        self._running = False

        # Initialize VAD
        if webrtcvad is not None:
            self.vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
            self._is_speech = self._webrtc_is_speech
        else:
            self.vad = EnergyVAD()
            self._is_speech = self._energy_is_speech

        # State
        self._speech_buffer = []       # frames of current speech segment
        self._pre_buffer = deque(maxlen=int(PRE_SPEECH_BUFFER_MS / FRAME_DURATION_MS))
        self._silence_frames = 0
        self._in_speech = False
        self._chunk_count = 0

        # Purge any leftover chunk dirs from previous sessions before creating a new one
        self._purge_old_sessions()

        # Temp directory for chunks (this session)
        self._tmp_dir = tempfile.mkdtemp(prefix="cluely_chunks_")
        print(f"[chunker] Temp dir: {self._tmp_dir}", file=sys.stderr)

        # Background cleanup thread (started in run())
        self._cleanup_stop = threading.Event()
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop, daemon=True, name="chunker-cleanup"
        )

    @staticmethod
    def _purge_old_sessions():
        """Delete all cluely_chunks_* directories left over from previous sessions."""
        import shutil
        tmp = tempfile.gettempdir()
        deleted = 0
        for name in os.listdir(tmp):
            if name.startswith("cluely_chunks_"):
                path = os.path.join(tmp, name)
                try:
                    shutil.rmtree(path)
                    deleted += 1
                except Exception as e:
                    print(f"[chunker] Could not remove old session dir {path}: {e}", file=sys.stderr)
        if deleted:
            print(f"[chunker] Purged {deleted} old session dir(s) from temp", file=sys.stderr)


    def _webrtc_is_speech(self, frame_bytes):
        """Check if frame contains speech using WebRTC VAD."""
        # WebRTC VAD expects exactly 480 bytes for 30ms at 16kHz (mono int16)
        expected = FRAME_SIZE * 2  # 2 bytes per int16 sample
        if len(frame_bytes) != expected:
            # Pad or truncate
            if len(frame_bytes) < expected:
                frame_bytes = frame_bytes + b"\x00" * (expected - len(frame_bytes))
            else:
                frame_bytes = frame_bytes[:expected]
        try:
            return self.vad.is_speech(frame_bytes, SAMPLE_RATE)
        except Exception:
            return False

    def _energy_is_speech(self, frame_bytes):
        """Fallback: energy-based VAD."""
        return self.vad.is_speech(frame_bytes, SAMPLE_RATE)

    def _ensure_tmp_dir(self):
        """Recreate the temp directory if it was removed (e.g. by Windows cleanup)."""
        if not os.path.exists(self._tmp_dir):
            try:
                os.makedirs(self._tmp_dir, exist_ok=True)
                print(f"[chunker] Temp dir recreated: {self._tmp_dir}", file=sys.stderr)
            except Exception:
                # If we can't recreate the original path, make a new one
                self._tmp_dir = tempfile.mkdtemp(prefix="cluely_chunks_")
                print(f"[chunker] New temp dir: {self._tmp_dir}", file=sys.stderr)

    def _cleanup_old_chunks(self):
        """Delete .wav chunk files older than CHUNK_MAX_AGE_S from the temp directory."""
        if not os.path.exists(self._tmp_dir):
            return
        now = time.time()
        deleted = 0
        for fname in os.listdir(self._tmp_dir):
            if not fname.endswith(".wav"):
                continue
            fpath = os.path.join(self._tmp_dir, fname)
            try:
                age = now - os.path.getmtime(fpath)
                if age > CHUNK_MAX_AGE_S:
                    os.remove(fpath)
                    deleted += 1
            except Exception:
                pass  # file may have just been removed by the transcriber
        if deleted:
            print(f"[chunker] Cleanup: removed {deleted} chunk(s) older than {CHUNK_MAX_AGE_S // 60} min", file=sys.stderr)

    def _cleanup_loop(self):
        """Background loop: sweep for stale chunks every CHUNK_CLEANUP_INTERVAL_S seconds."""
        while not self._cleanup_stop.wait(timeout=CHUNK_CLEANUP_INTERVAL_S):
            self._cleanup_old_chunks()

    def _flush_chunk(self):
        """Save buffered speech frames as a .wav file and enqueue it."""
        if not self._speech_buffer:
            return

        # Calculate duration
        total_frames = len(self._speech_buffer)
        duration_s = (total_frames * FRAME_SIZE) / SAMPLE_RATE

        if duration_s < MIN_CHUNK_DURATION_S:
            self._speech_buffer.clear()
            return

        # Concatenate all frames
        all_bytes = b"".join(self._speech_buffer)
        audio = np.frombuffer(all_bytes, dtype=np.int16)

        # Ensure the temp directory still exists (Windows may purge it during long sessions)
        self._ensure_tmp_dir()

        # Save to temp file — use 6-digit padding to safely support long sessions
        self._chunk_count += 1
        chunk_path = os.path.join(
            self._tmp_dir, f"chunk_{self._chunk_count:06d}.wav"
        )
        try:
            sf.write(chunk_path, audio, SAMPLE_RATE, subtype="PCM_16")
        except Exception as e:
            print(f"[chunker] Write failed for {chunk_path}: {e}", file=sys.stderr)
            self._speech_buffer.clear()
            return

        print(f"[chunker] Chunk #{self._chunk_count}: {duration_s:.1f}s -> {chunk_path}", file=sys.stderr)
        self.chunk_queue.put(chunk_path)

        self._speech_buffer.clear()

    def process_frame(self, frame_bytes):
        """Process a single audio frame through the VAD pipeline."""
        is_speech = self._is_speech(frame_bytes)

        if is_speech:
            if not self._in_speech:
                # Speech just started — include pre-buffer
                self._in_speech = True
                self._silence_frames = 0
                self._speech_buffer.extend(list(self._pre_buffer))
                print("[chunker] Speech detected", file=sys.stderr)
            self._speech_buffer.append(frame_bytes)
            self._silence_frames = 0

            # Check max duration
            total_frames = len(self._speech_buffer)
            duration_s = (total_frames * FRAME_SIZE) / SAMPLE_RATE
            if duration_s >= MAX_CHUNK_DURATION_S:
                print(f"[chunker] Max duration reached ({MAX_CHUNK_DURATION_S}s), flushing", file=sys.stderr)
                self._flush_chunk()
                self._in_speech = False
        else:
            if self._in_speech:
                self._speech_buffer.append(frame_bytes)
                self._silence_frames += 1
                silence_ms = self._silence_frames * FRAME_DURATION_MS
                if silence_ms >= SILENCE_THRESHOLD_MS:
                    # Enough silence — flush the chunk
                    self._in_speech = False
                    self._flush_chunk()
            else:
                # Not in speech — keep pre-buffer rolling
                self._pre_buffer.append(frame_bytes)

    def run(self):
        """Main loop: read frames from queue and process them."""
        self._running = True
        self._cleanup_stop.clear()
        self._cleanup_thread.start()
        print("[chunker] Started", file=sys.stderr)

        while self._running:
            try:
                frame_bytes = self.audio_queue.get(timeout=0.1)
                self.process_frame(frame_bytes)
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[chunker] Error: {e}", file=sys.stderr)
                continue

        # Flush any remaining audio
        if self._speech_buffer:
            self._flush_chunk()
        print("[chunker] Stopped", file=sys.stderr)

    def stop(self):
        """Signal the chunker to stop."""
        self._running = False
        self._cleanup_stop.set()  # wake the cleanup thread so it exits promptly

    def cleanup(self):
        """Remove temp directory and all chunk files."""
        import shutil
        if os.path.exists(self._tmp_dir):
            shutil.rmtree(self._tmp_dir)
            print(f"[chunker] Cleaned up {self._tmp_dir}", file=sys.stderr)
