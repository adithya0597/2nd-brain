#!/usr/bin/env bash
# Source this before running the bot with demo data.
# Usage: source scripts/demo-env.sh && python scripts/brain-bot/app.py

export BRAIN_DB_PATH="$(cd "$(dirname "$0")/.." && pwd)/data/brain_demo.db"
export BRAIN_VAULT_PATH="$(cd "$(dirname "$0")/.." && pwd)/vault"

# Disable external integrations — prevent fake data leaking
unset NOTION_TOKEN
export TELEGRAM_BOT_TOKEN="demo-no-token"
export GROUP_CHAT_ID="0"

echo "Demo mode active:"
echo "  DB:    $BRAIN_DB_PATH"
echo "  Vault: $BRAIN_VAULT_PATH"
echo "  Notion: DISABLED"
echo "  Telegram: DISABLED"
