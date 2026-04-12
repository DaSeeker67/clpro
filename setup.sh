#!/bin/bash
set -e

echo ""
echo "╔══════════════════════════════════╗"
echo "║    Cluely Pro — Setup (Unix)     ║"
echo "╚══════════════════════════════════╝"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python 3 not found. Install it first."
    exit 1
fi

# Check Node
if ! command -v node &> /dev/null; then
    echo "[ERROR] Node.js not found. Install from https://nodejs.org"
    exit 1
fi

# Install Python dependencies
echo "[1/4] Installing Python dependencies..."
pip3 install -r backend/requirements.txt

# Install Node dependencies
echo "[2/4] Installing Node dependencies..."
npm install

# Setup .env
echo "[3/4] Setting up environment..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env — please add your GROQ_API_KEY"
    echo "Get your free key at: https://console.groq.com/keys"
else
    echo ".env already exists, skipping"
fi

# macOS: Check BlackHole
echo "[4/4] Checking audio setup..."
if [[ "$OSTYPE" == "darwin"* ]]; then
    if ! system_profiler SPAudioDataType 2>/dev/null | grep -qi "blackhole"; then
        echo ""
        echo "⚠️  BlackHole virtual audio device not detected!"
        echo "   Install it from: https://existential.audio/blackhole/"
        echo "   Then create a Multi-Output Device in Audio MIDI Setup"
        echo "   that includes both BlackHole and your speakers."
        echo ""
    else
        echo "BlackHole detected ✓"
    fi
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    if pactl list sources 2>/dev/null | grep -qi "monitor"; then
        echo "PulseAudio monitor source detected ✓"
    else
        echo "⚠️  No PulseAudio monitor source found."
        echo "   Try: pactl load-module module-loopback"
    fi
fi

echo ""
echo "══════════════════════════════════════"
echo " Setup complete!"
echo ""
echo " Next steps:"
echo "   1. Edit .env and add your GROQ_API_KEY"
echo "   2. Terminal mode:  python3 backend/main.py"
echo "   3. Overlay mode:   npm start"
echo "══════════════════════════════════════"
echo ""
