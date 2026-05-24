#!/bin/bash
# Carmen Prompt Generator Bot — Quick Launcher
# Usage: ./run.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Create venv if not exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate

# Install deps
pip install -q -r requirements.txt

# Run
python telegram_bot.py
