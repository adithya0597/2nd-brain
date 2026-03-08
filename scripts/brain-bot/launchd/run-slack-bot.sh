#!/bin/bash
# Wrapper script for launchd — sources .env and uses venv Python
set -euo pipefail

cd /Users/adithya/Documents/2nd-brain/scripts/slack-bot

# Source environment variables
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

# Use venv Python — fail loudly if missing
if [ -x venv/bin/python ]; then
    exec venv/bin/python app.py
else
    echo "ERROR: venv/bin/python not found at $(pwd)/venv/" >&2
    echo "Run: python3 -m venv venv && venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi
