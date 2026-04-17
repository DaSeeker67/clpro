import sys
import time

try:
    import pyaudiowpatch as pyaudio
except ImportError:
    print("pyaudiowpatch is not installed. Run: pip install pyaudiowpatch", file=sys.stderr)
    sys.exit(1)

p = pyaudio.PyAudio()

try:
    wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
except Exception as e:
    print(f"WASAPI not available: {e}", file=sys.stderr)
    sys.exit(1)

print("\n=== WASAPI Loopback Devices ===")
loopback_devices = []
for i in range(p.get_device_count()):
    dev = p.get_device_info_by_index(i)
    if dev["name"].endswith(" [Loopback]") and dev["hostApi"] == wasapi_info["index"]:
        loopback_devices.append(dev)
        print(f"{i}: {dev['name']} | SR: {dev['defaultSampleRate']} | Channels: {dev['maxInputChannels']}")

if not loopback_devices:
    print("No WASAPI loopback devices found.", file=sys.stderr)
    sys.exit(1)

for dev in loopback_devices:
    print(f"\nTesting device: {dev['name']}")
    try:
        stream = p.open(
            format=pyaudio.paFloat32,
            channels=min(dev["maxInputChannels"], 2),
            rate=int(dev["defaultSampleRate"]),
            input=True,
            input_device_index=dev["index"],
            frames_per_buffer=int(dev["defaultSampleRate"] * 0.03),
        )
        print("  Opened stream. Reading 1s of audio...")
        data = stream.read(int(dev["defaultSampleRate"] * 1), exception_on_overflow=False)
        import numpy as np
        audio = np.frombuffer(data, dtype=np.float32)
        rms = np.sqrt(np.mean(audio ** 2))
        print(f"  RMS: {rms:.6f}")
        if rms < 1e-7:
            print("  ⚠️  No signal detected (all zeros or silence)")
        else:
            print("  ✅ Audio signal detected!")
        stream.close()
    except Exception as e:
        print(f"  ❌ Failed to open/read: {e}")

p.terminate()
print("\nDone.")
