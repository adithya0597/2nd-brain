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

# Use venv Python if available, otherwise fall back to system python3
if [ -x venv/bin/python ]; then
    exec venv/bin/python app.py
else
    exec python3 app.py
fi
