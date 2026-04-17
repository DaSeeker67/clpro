"""
audio_capture.py — System audio loopback capture.

Captures system audio output (not microphone) so it doesn't trigger
any browser permission indicators. Uses multiple strategies:
  - Windows: WASAPI loopback (pyaudiowpatch), Stereo Mix, or microphone fallback
  - macOS: BlackHole virtual audio device
  - Linux: PulseAudio monitor source
"""

import sys
import queue
import threading
import numpy as np

# Target format for Whisper
SAMPLE_RATE = 16000
CHANNELS = 1
BLOCK_SIZE = 480  # 30ms at 16kHz — matches WebRTC VAD frame size


class AudioCapture:
    """
    Captures system audio via loopback and pushes 30ms frames
    into a thread-safe queue for downstream processing.
    Handles sample rate conversion if the device doesn't support 16kHz.

    mode:
      "auto"     — try WASAPI loopback first, fall back to mic (default, legacy)
      "loopback" — only try WASAPI loopback, fail if unavailable
      "mic"      — only use microphone input
    """

    def __init__(self, audio_queue: queue.Queue, device=None, mode="auto"):
        self.audio_queue = audio_queue
        self.device = device
        self.mode = mode
        self.stream = None
        self._running = False
        self._native_sr = SAMPLE_RATE
        self._native_channels = CHANNELS
        self._use_wasapi = False
        self._wasapi_thread = None

    def _sd_callback(self, indata, frames, time_info, status):
        """sounddevice callback — converts and pushes PCM bytes into the queue."""
        if status:
            print(f"[audio] {status}", file=sys.stderr)
        self._process_audio(indata)

    def _process_audio(self, indata):
        """Convert audio data to 16kHz mono int16 PCM and push to queue."""
        if isinstance(indata, np.ndarray):
            audio = indata
        else:
            audio = np.frombuffer(indata, dtype=np.float32)

        # Get mono channel
        if audio.ndim > 1 and audio.shape[1] > 1:
            audio = audio[:, 0]
        else:
            audio = audio.flatten()

        # Resample to 16kHz if needed
        if self._native_sr != SAMPLE_RATE:
            ratio = SAMPLE_RATE / self._native_sr
            new_len = int(len(audio) * ratio)
            if new_len == 0:
                return
            indices = np.arange(new_len) / ratio
            indices = np.clip(indices, 0, len(audio) - 1).astype(int)
            audio = audio[indices]

        # Convert float32 to int16 PCM (what WebRTC VAD expects)
        audio_int16 = (audio * 32767).astype(np.int16)
        self.audio_queue.put(audio_int16.tobytes())

    def _try_wasapi_loopback(self):
        """Try to start WASAPI loopback capture via pyaudiowpatch (Windows only), robustly matching default output device (including headphones)."""
        try:
            import pyaudiowpatch as pyaudio

            p = pyaudio.PyAudio()

            # Find the default WASAPI output device's loopback
            wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_idx = wasapi_info["defaultOutputDevice"]
            default_speakers = p.get_device_info_by_index(default_idx)
            print(f"[audio] Default output device: {default_speakers['name']} (index {default_idx})", file=sys.stderr)

            # Collect ALL loopback devices
            loopback_devices = []
            for i in range(p.get_device_count()):
                dev = p.get_device_info_by_index(i)
                if dev["name"].endswith(" [Loopback]") and dev["hostApi"] == wasapi_info["index"]:
                    loopback_devices.append(dev)
                    print(f"[audio] Found loopback: {dev['name']} (index {dev['index']})", file=sys.stderr)

            if not loopback_devices:
                print("[audio] No WASAPI loopback devices found.", file=sys.stderr)
                p.terminate()
                return False

            # Try to match the default output device name (case-insensitive, ignore [Loopback] suffix)
            base_name = default_speakers["name"].replace(" [Loopback]", "").strip().lower()
            loopback_device = None
            for dev in loopback_devices:
                dev_base = dev["name"].replace(" [Loopback]", "").strip().lower()
                if dev_base == base_name:
                    loopback_device = dev
                    print(f"[audio] Matched loopback device: {dev['name']} (index {dev['index']})", file=sys.stderr)
                    break

            # If not exact, try substring match (for some USB/Bluetooth devices)
            if loopback_device is None:
                for dev in loopback_devices:
                    dev_base = dev["name"].replace(" [Loopback]", "").strip().lower()
                    if base_name in dev_base or dev_base in base_name:
                        loopback_device = dev
                        print(f"[audio] Substring-matched loopback device: {dev['name']} (index {dev['index']})", file=sys.stderr)
                        break

            # Fallback: just use the first available loopback device
            if loopback_device is None:
                loopback_device = loopback_devices[0]
                print(f"[audio] Fallback to first loopback device: {loopback_device['name']} (index {loopback_device['index']})", file=sys.stderr)

            self._native_sr = int(loopback_device["defaultSampleRate"])
            self._native_channels = min(loopback_device["maxInputChannels"], 2)
            native_block = int(self._native_sr * 0.03)  # 30ms

            print(f"[audio] WASAPI loopback device selected: {loopback_device['name']} (index {loopback_device['index']})", file=sys.stderr)
            print(f"[audio] Native: {self._native_sr}Hz, {self._native_channels}ch -> resampling to {SAMPLE_RATE}Hz mono", file=sys.stderr)

            self._pyaudio = p
            self._wasapi_failed = False

            # Test if the loopback actually produces data before committing
            test_ok = self._test_wasapi_stream(p, loopback_device, native_block)

            if not test_ok:
                print("[audio] WASAPI loopback test failed (no data / blocked)", file=sys.stderr)
                self.stream = None
                self._use_wasapi = False
                return False

            self.stream = p.open(
                format=pyaudio.paFloat32,
                channels=self._native_channels,
                rate=self._native_sr,
                input=True,
                input_device_index=loopback_device["index"],
                frames_per_buffer=native_block,
            )
            self._use_wasapi = True

            # Read in a background thread since pyaudio doesn't always support callbacks for loopback
            self._wasapi_thread = threading.Thread(target=self._wasapi_read_loop, daemon=True)
            self._wasapi_thread.start()

            return True

        except Exception as e:
            print(f"[audio] WASAPI loopback failed: {e}", file=sys.stderr)
            return False

    def _test_wasapi_stream(self, p, device, block_size):
        """Check if the WASAPI loopback stream can be opened (non-blocking).

        The old approach tried to read() data within 2 seconds, which blocks
        indefinitely when no audio is currently playing — causing a false failure.
        Simply opening and closing the stream is sufficient to confirm the device
        is accessible; actual audio will flow once something plays.
        """
        import pyaudiowpatch as pyaudio
        try:
            test_stream = p.open(
                format=pyaudio.paFloat32,
                channels=self._native_channels,
                rate=self._native_sr,
                input=True,
                input_device_index=device["index"],
                frames_per_buffer=block_size,
            )
            test_stream.close()
            print("[audio] WASAPI loopback stream opened OK", file=sys.stderr)
            return True
        except Exception as e:
            print(f"[audio] WASAPI test open failed: {e}", file=sys.stderr)
            return False

    def _wasapi_read_loop(self):
        """Background thread that reads from WASAPI loopback stream."""
        native_block = int(self._native_sr * 0.03)

        print("[audio] WASAPI loopback: read loop started", file=sys.stderr)
        while self._running:
            try:
                data = self.stream.read(native_block, exception_on_overflow=False)
                audio = np.frombuffer(data, dtype=np.float32)

                if self._native_channels > 1:
                    audio = audio.reshape(-1, self._native_channels)
                self._process_audio(audio)
            except OSError:
                if self._running:
                    print("[audio] WASAPI read: stream closed", file=sys.stderr)
                break
            except Exception as e:
                if self._running:
                    print(f"[audio] WASAPI read error: {e}", file=sys.stderr)
                break

    def start(self):
        """Start capturing audio based on self.mode."""
        self._running = True
        self._wasapi_failed = False

        if self.mode == "loopback":
            # Only try WASAPI loopback — fail if unavailable
            if sys.platform == "win32":
                if self._try_wasapi_loopback():
                    print("[audio] Capture started (WASAPI loopback)", file=sys.stderr)
                    return
            raise RuntimeError("WASAPI loopback not available")

        if self.mode == "mic":
            # Only use microphone input
            self._start_mic()
            return

        # mode == "auto": try WASAPI loopback first, fall back to mic
        if sys.platform == "win32" and self.device is None:
            if self._try_wasapi_loopback():
                print("[audio] Capture started (WASAPI loopback)", file=sys.stderr)
                return

        self._start_mic()

    def _start_mic(self):
        """Start microphone capture."""
        import sounddevice as sd

        print("[audio] Using microphone input", file=sys.stderr)
        default_idx = sd.default.device[0]
        if default_idx is not None and default_idx >= 0:
            dev = sd.query_devices(default_idx)
            self.device = default_idx
            self._native_sr = int(dev["default_samplerate"])
            self._native_channels = min(dev["max_input_channels"], 2)
        else:
            # Find any input device
            for i, dev in enumerate(sd.query_devices()):
                if dev["max_input_channels"] > 0:
                    self.device = i
                    self._native_sr = int(dev["default_samplerate"])
                    self._native_channels = min(dev["max_input_channels"], 2)
                    break
            if self.device is None:
                raise RuntimeError("No audio input device found")

        dev_info = sd.query_devices(self.device)
        print(f"[audio] Using device: {dev_info['name']}", file=sys.stderr)
        print(f"[audio] Native: {self._native_sr}Hz, {self._native_channels}ch -> resampling to {SAMPLE_RATE}Hz mono", file=sys.stderr)

        native_block = int(self._native_sr * 0.03)

        self.stream = sd.InputStream(
            device=self.device,
            samplerate=self._native_sr,
            channels=self._native_channels,
            dtype="float32",
            blocksize=native_block,
            callback=self._sd_callback,
        )
        self.stream.start()
        print("[audio] Capture started (microphone)", file=sys.stderr)

    def stop(self):
        """Stop the audio capture stream."""
        self._running = False
        if self._use_wasapi:
            if self.stream:
                self.stream.stop_stream()
                self.stream.close()
            if hasattr(self, '_pyaudio'):
                self._pyaudio.terminate()
            print("[audio] WASAPI capture stopped", file=sys.stderr)
        elif self.stream:
            self.stream.stop()
            self.stream.close()
            print("[audio] Capture stopped", file=sys.stderr)


# ─── sounddevice device detection (fallback) ────────────

def _get_sd_loopback():
    """Find loopback device via sounddevice (Stereo Mix / mic fallback)."""
    import sounddevice as sd

    if sys.platform == "win32":
        return _get_windows_sd_loopback()
    elif sys.platform == "darwin":
        return _get_blackhole_device()
    elif sys.platform.startswith("linux"):
        return _get_pulse_monitor()
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")


def _get_windows_sd_loopback():
    import sounddevice as sd

    devices = sd.query_devices()
    hostapis = sd.query_hostapis()

    API_PENALTY = {}
    for idx, api in enumerate(hostapis):
        name = api["name"].lower()
        if "mme" in name:
            API_PENALTY[idx] = 0
        elif "directsound" in name:
            API_PENALTY[idx] = 1
        elif "wasapi" in name:
            API_PENALTY[idx] = 2
        else:
            API_PENALTY[idx] = 10

    candidates = []
    for i, dev in enumerate(devices):
        name_lower = dev["name"].lower()
        if dev["max_input_channels"] <= 0:
            continue
        api_penalty = API_PENALTY.get(dev["hostapi"], 10)
        if "stereo mix" in name_lower:
            candidates.append((0, api_penalty, i, dev))
        elif "loopback" in name_lower:
            candidates.append((1, api_penalty, i, dev))
        elif "what u hear" in name_lower or "what you hear" in name_lower:
            candidates.append((2, api_penalty, i, dev))

    if candidates:
        candidates.sort(key=lambda x: (x[0], x[1]))
        _, api_pen, idx, dev = candidates[0]
        if api_pen >= 10:
            api_name = hostapis[dev["hostapi"]]["name"]
            print(f"[audio] WARNING: {dev['name']} only available via {api_name}, may be unreliable", file=sys.stderr)
        return (idx, int(dev["default_samplerate"]), min(dev["max_input_channels"], 2))

    # Fall back to default microphone
    print("[audio] No loopback device found, falling back to microphone", file=sys.stderr)
    default_idx = sd.default.device[0]
    if default_idx is not None and default_idx >= 0:
        dev = sd.query_devices(default_idx)
        print(f"[audio] Using microphone: {dev['name']}", file=sys.stderr)
        return (default_idx, int(dev["default_samplerate"]), min(dev["max_input_channels"], 2))

    for i, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
            return (i, int(dev["default_samplerate"]), min(dev["max_input_channels"], 2))

    raise RuntimeError("No audio input device found.")


def _get_blackhole_device():
    import sounddevice as sd
    for i, dev in enumerate(sd.query_devices()):
        if "blackhole" in dev["name"].lower() and dev["max_input_channels"] > 0:
            return (i, int(dev["default_samplerate"]), 1)
    raise RuntimeError("BlackHole not found. Install from https://existential.audio/blackhole/")


def _get_pulse_monitor():
    import sounddevice as sd
    for i, dev in enumerate(sd.query_devices()):
        if "monitor" in dev["name"].lower() and dev["max_input_channels"] > 0:
            return (i, int(dev["default_samplerate"]), 1)
    raise RuntimeError("PulseAudio monitor source not found. Try: pactl load-module module-loopback")

    @property
    def is_running(self):
        return self._running


if __name__ == "__main__":
    """Quick test: capture 5 seconds and save to test_capture.wav"""
    import soundfile as sf
    import time

    print("Recording 5 seconds of system audio...")
    q = queue.Queue()
    cap = AudioCapture(q)
    cap.start()

    frames = []
    start = time.time()
    while time.time() - start < 5:
        try:
            data = q.get(timeout=0.1)
            frames.append(np.frombuffer(data, dtype=np.int16))
        except queue.Empty:
            continue

    cap.stop()

    if frames:
        audio = np.concatenate(frames)
        sf.write("test_capture.wav", audio, SAMPLE_RATE, subtype="PCM_16")
        print(f"Saved test_capture.wav ({len(audio)/SAMPLE_RATE:.1f}s)")
    else:
        print("No audio captured!")
