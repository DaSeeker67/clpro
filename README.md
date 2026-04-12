# 🔮 Cluely Pro

**Stealth meeting copilot** — fully local, screen-capture-proof AI assistant that listens to your meetings and answers questions in real-time.

![Stealth](https://img.shields.io/badge/stealth-screen_capture_proof-blueviolet)
![License](https://img.shields.io/badge/license-MIT-green)

## How It Works

```
System Audio (loopback) → VAD → Whisper STT → Question Detection → LLaMA Answer → Stealth Overlay
```

**The stealth trick**: Captures system audio output (loopback), not the microphone — no browser permission indicators. The overlay uses `setContentProtection(true)` + `DWMWA_EXCLUDED_FROM_CAPTURE` — it's **invisible in screen recordings and screen shares**.

## Quick Start

### 1. Clone & Setup
```bash
git clone https://github.com/yourname/cluely-pro.git
cd cluely-pro

# Windows
setup.bat

# macOS / Linux
chmod +x setup.sh && ./setup.sh
```

### 2. Add Your API Key
Get a free Groq API key at [console.groq.com/keys](https://console.groq.com/keys), then:
```bash
# Edit .env
GROQ_API_KEY=gsk_your_key_here
```

### 3. Run

**Terminal mode** (Phase 1 — no overlay):
```bash
python backend/main.py
```

**Overlay mode** (full stealth):
```bash
npm start
```

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+Shift+H` | Toggle overlay visibility |
| `Ctrl+Shift+A` | Force answer on last 10s of audio |
| `Ctrl+Shift+L` | Toggle listening on/off |

## Architecture

```
cluely-pro/
├── main.js                 ← Electron: stealth window + IPC
├── preload.js              ← IPC bridge (main ↔ renderer)
├── renderer/
│   ├── index.html          ← Overlay UI
│   └── style.css           ← Dark glassmorphism styles
│
└── backend/
    ├── main.py             ← Orchestrator (pipeline + IPC)
    ├── audio_capture.py    ← WASAPI/BlackHole/Pulse loopback
    ├── chunker.py          ← WebRTC VAD + silence splitting
    ├── transcriber.py      ← Groq Whisper (whisper-large-v3-turbo)
    ├── context_manager.py  ← Rolling transcript + question detection
    └── assistant.py        ← Groq LLaMA 3.3 70B streaming
```

### Pipeline

1. **Audio Capture** — `sounddevice` loopback at 16kHz mono
2. **VAD** — WebRTC VAD (aggressiveness 2) filters silence
3. **Chunker** — Buffers speech, flushes on 500ms silence (5-15s chunks)
4. **Whisper STT** — Groq API, ~300ms latency per chunk
5. **Context Manager** — 120s sliding window, detects questions (`?` + trigger phrases)
6. **LLaMA Assistant** — Streaming 2-3 sentence answers via Groq
7. **Overlay** — Transparent, frameless, always-on-top, content-protected

### IPC Protocol

Python ↔ Electron via JSON lines on stdin/stdout:
```json
{"type": "transcript", "text": "..."}
{"type": "question", "text": "..."}
{"type": "answer_start", "question": "..."}
{"type": "answer_chunk", "text": "..."}
{"type": "answer_done", "text": "...", "latency_ms": 450}
```

## Platform Support

| Platform | Audio Capture | Status |
|----------|---------------|--------|
| **Windows** | WASAPI loopback | ✅ Works out of the box |
| **macOS** | BlackHole virtual device | ⚠️ Requires one-time install |
| **Linux** | PulseAudio monitor | ⚠️ May need `module-loopback` |

## Tech Stack

- **Runtime**: Electron + Python subprocess
- **STT**: Groq Whisper (`whisper-large-v3-turbo`)
- **LLM**: Groq LLaMA 3.3 70B (`llama-3.3-70b-versatile`)
- **Audio**: `sounddevice` + `webrtcvad`
- **Frontend**: Vanilla HTML/CSS/JS (no frameworks)

## License

MIT
