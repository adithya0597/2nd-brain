#!/usr/bin/env python3
"""Interactive Telegram bot setup for Second Brain.

Usage:
    python scripts/setup-telegram.py          # Interactive setup
    python scripts/setup-telegram.py --help   # Show help
    python scripts/setup-telegram.py --check  # Verify existing .env config
"""
import argparse
import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Resolve paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
BOT_DIR = SCRIPT_DIR / "brain-bot"
ENV_FILE = BOT_DIR / ".env"

# Telegram Bot API base
API_BASE = "https://api.telegram.org/bot{token}"

# Forum topics to create
TOPICS = [
    ("brain-inbox", "Drop thoughts here — bot classifies and routes"),
    ("brain-daily", "Morning briefings and evening reviews"),
    ("brain-actions", "Action items with interactive buttons"),
    ("brain-dashboard", "ICOR heatmap, attention scores, project status"),
    ("brain-ideas", "Idea generation reports"),
    ("brain-drift", "Alignment drift reports"),
    ("brain-insights", "Pattern synthesis, ghost reflections, trace timelines"),
    ("brain-health", "Health & Vitality captures"),
    ("brain-wealth", "Wealth & Finance captures"),
    ("brain-relations", "Relationships captures"),
    ("brain-growth", "Mind & Growth captures"),
    ("brain-purpose", "Purpose & Impact captures"),
    ("brain-systems", "Systems & Environment captures"),
    ("brain-projects", "Active projects and weekly summaries"),
    ("brain-resources", "Resource catalog and monthly digests"),
]

# Bot commands to register
BOT_COMMANDS = [
    ("today", "Morning review and daily briefing"),
    ("close", "Evening review and day wrap-up"),
    ("drift", "Alignment drift analysis"),
    ("emerge", "Surface unnamed patterns"),
    ("ideas", "Generate actionable ideas"),
    ("schedule", "Energy-aware weekly planning"),
    ("ghost", "Digital twin response"),
    ("status", "Quick status dashboard"),
    ("sync", "Sync with Notion"),
    ("projects", "Active project dashboard"),
    ("resources", "Knowledge base catalog"),
    ("trace", "Concept evolution timeline"),
    ("connect", "Serendipity engine"),
    ("challenge", "Red-team a belief"),
    ("graduate", "Promote journal themes"),
    ("context", "Load session context"),
    ("find", "Semantic vault search"),
    ("help", "List available commands"),
    ("engage", "Engagement analysis"),
    ("dashboard", "Full ICOR dashboard"),
]


def api_call(token: str, method: str, data: dict | None = None) -> dict:
    """Make a Telegram Bot API call."""
    url = f"{API_BASE.format(token=token)}/{method}"
    if data:
        body = json.dumps(data).encode()
        req = Request(url, data=body, headers={"Content-Type": "application/json"})
    else:
        req = Request(url)

    try:
        with urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
    except HTTPError as e:
        body = e.read().decode()
        try:
            err = json.loads(body)
            print(f"  API error: {err.get('description', body)}")
        except json.JSONDecodeError:
            print(f"  HTTP {e.code}: {body[:200]}")
        return {"ok": False}
    except URLError as e:
        print(f"  Network error: {e.reason}")
        return {"ok": False}

    return result


def verify_token(token: str) -> dict | None:
    """Verify bot token via getMe. Returns bot info or None."""
    result = api_call(token, "getMe")
    if result.get("ok"):
        return result["result"]
    return None


def detect_owner(token: str) -> int | None:
    """Try to detect owner's chat ID from recent messages."""
    print("\n  To auto-detect your Telegram user ID:")
    print("  1. Open Telegram and send any message to your bot")
    print("  2. Press Enter here when done...")
    input()

    result = api_call(token, "getUpdates", {"limit": 10, "timeout": 5})
    if not result.get("ok"):
        return None

    updates = result.get("result", [])
    for update in reversed(updates):
        msg = update.get("message", {})
        user = msg.get("from", {})
        if user.get("id"):
            name = user.get("first_name", "")
            username = user.get("username", "")
            print(f"  Found: {name} (@{username}) — ID: {user['id']}")
            return user["id"]

    print("  No messages found. You can set OWNER_TELEGRAM_ID manually in .env")
    return None


def create_forum_group(token: str, bot_info: dict) -> tuple[int | None, dict[str, int]]:
    """Guide user to create a forum group and create topics.

    Returns (group_chat_id, {topic_name: thread_id}).
    """
    print("\n--- Forum Group Setup ---")
    print("To use forum topics, you need a Telegram group with Topics enabled.")
    print("")
    print("Option 1: Create a new group")
    print("  1. Open Telegram → New Group → Add your bot")
    print("  2. Go to Group Settings → Topics → Enable")
    print("")
    print("Option 2: Use an existing forum group")
    print("  1. Add your bot to the group as admin")
    print("  2. Make sure Topics is enabled in group settings")
    print("")

    group_id_str = input("Enter the group chat ID (negative number, e.g., -1001234567890): ").strip()
    if not group_id_str:
        print("  Skipping forum group setup. You can configure GROUP_CHAT_ID later.")
        return None, {}

    try:
        group_id = int(group_id_str)
    except ValueError:
        print("  Invalid group ID. Skipping topic creation.")
        return None, {}

    # Verify bot is in the group
    result = api_call(token, "getChat", {"chat_id": group_id})
    if not result.get("ok"):
        print("  Could not access group. Make sure the bot is added as admin.")
        return group_id, {}

    chat = result["result"]
    is_forum = chat.get("is_forum", False)
    if not is_forum:
        print(f"  Warning: Group '{chat.get('title', '')}' does not have Topics enabled.")
        print("  Enable Topics in group settings, then re-run this setup.")
        return group_id, {}

    print(f"  Connected to forum group: {chat.get('title', '')}")

    # Create topics
    topic_ids: dict[str, int] = {}
    print(f"\n  Creating {len(TOPICS)} forum topics...")

    for name, description in TOPICS:
        result = api_call(token, "createForumTopic", {
            "chat_id": group_id,
            "name": name,
            "icon_custom_emoji_id": None,
        })
        if result.get("ok"):
            thread_id = result["result"]["message_thread_id"]
            topic_ids[name] = thread_id
            print(f"    + {name} (thread_id={thread_id})")
        else:
            print(f"    x {name} — failed (may already exist)")
        time.sleep(0.5)  # Rate limit

    return group_id, topic_ids


def set_bot_commands(token: str) -> bool:
    """Register bot commands with Telegram."""
    commands = [{"command": cmd, "description": desc} for cmd, desc in BOT_COMMANDS]
    result = api_call(token, "setMyCommands", {"commands": commands})
    return result.get("ok", False)


def write_env_file(
    token: str,
    owner_id: int | None,
    group_id: int | None,
    topic_ids: dict[str, int],
) -> None:
    """Write .env file for the bot."""
    lines = [
        f"# Generated by setup-telegram.py",
        f"TELEGRAM_BOT_TOKEN={token}",
        f"OWNER_TELEGRAM_ID={owner_id or ''}",
        f"GROUP_CHAT_ID={group_id or ''}",
        f"",
        f"# Anthropic API",
        f"ANTHROPIC_API_KEY=",
        f"ANTHROPIC_MODEL=claude-sonnet-4-5-20250929",
        f"",
        f"# Notion Integration (optional)",
        f"NOTION_TOKEN=",
        f"",
        f"# Classifier (optional)",
        f"CLASSIFIER_LLM_MODEL=claude-haiku-4-5-20251001",
        f"",
    ]

    # Topic IDs
    if topic_ids:
        lines.append("# Forum topic thread IDs")
        for name, tid in topic_ids.items():
            env_key = f"TOPIC_{name.upper().replace('-', '_')}"
            lines.append(f"{env_key}={tid}")
        lines.append("")

    content = "\n".join(lines)

    if ENV_FILE.exists():
        overwrite = input(f"\n  {ENV_FILE} already exists. Overwrite? [y/N]: ").strip().lower()
        if overwrite != "y":
            # Write to .env.generated instead
            alt = BOT_DIR / ".env.generated"
            alt.write_text(content)
            print(f"  Written to {alt} (merge manually)")
            return

    ENV_FILE.write_text(content)
    print(f"  Written to {ENV_FILE}")


def check_config() -> None:
    """Verify existing .env configuration."""
    if not ENV_FILE.exists():
        print(f"No .env file found at {ENV_FILE}")
        print("Run: python scripts/setup-telegram.py")
        sys.exit(1)

    from dotenv import dotenv_values
    config = dotenv_values(ENV_FILE)

    print("--- Configuration Check ---")
    token = config.get("TELEGRAM_BOT_TOKEN", "")
    if token:
        bot = verify_token(token)
        if bot:
            print(f"  Bot: @{bot['username']} ({bot['first_name']}) — OK")
        else:
            print("  Bot token: INVALID")
    else:
        print("  Bot token: NOT SET")

    owner = config.get("OWNER_TELEGRAM_ID", "")
    print(f"  Owner ID: {owner or 'NOT SET'}")

    group = config.get("GROUP_CHAT_ID", "")
    print(f"  Group ID: {group or 'NOT SET'}")

    topic_count = sum(1 for k in config if k.startswith("TOPIC_"))
    print(f"  Topics configured: {topic_count}")

    api_key = config.get("ANTHROPIC_API_KEY", "")
    print(f"  Anthropic API: {'SET' if api_key else 'NOT SET'}")

    notion = config.get("NOTION_TOKEN", "")
    print(f"  Notion token: {'SET' if notion else 'NOT SET'}")


def main():
    parser = argparse.ArgumentParser(description="Set up the Second Brain Telegram bot")
    parser.add_argument("--check", action="store_true", help="Verify existing .env config")
    args = parser.parse_args()

    if args.check:
        check_config()
        return

    print("=== Second Brain Telegram Bot Setup ===\n")

    # Step 1: Bot token
    print("Step 1: Bot Token")
    print("  Create a bot via @BotFather on Telegram if you haven't already.")
    token = input("  Enter your bot token: ").strip()
    if not token:
        print("  No token provided. Exiting.")
        sys.exit(1)

    # Step 2: Verify token
    print("\nStep 2: Verifying token...")
    bot_info = verify_token(token)
    if not bot_info:
        print("  Invalid token. Please check and try again.")
        sys.exit(1)
    print(f"  Bot verified: @{bot_info['username']} ({bot_info['first_name']})")

    # Step 3: Detect owner
    print("\nStep 3: Owner Detection")
    owner_id = detect_owner(token)

    # Step 4: Forum group + topics
    group_id, topic_ids = create_forum_group(token, bot_info)

    # Step 5: Register bot commands
    print("\nStep 5: Registering bot commands...")
    if set_bot_commands(token):
        print(f"  Registered {len(BOT_COMMANDS)} commands with Telegram")
    else:
        print("  Failed to register commands (non-critical)")

    # Step 6: Write .env
    print("\nStep 6: Writing configuration...")
    write_env_file(token, owner_id, group_id, topic_ids)

    # Summary
    print("\n=== Setup Complete ===")
    print(f"  Bot: @{bot_info['username']}")
    print(f"  Owner: {owner_id or 'not set'}")
    print(f"  Group: {group_id or 'not set'}")
    print(f"  Topics: {len(topic_ids)} created")
    print("")
    print("Next steps:")
    print("  1. Edit scripts/brain-bot/.env to add ANTHROPIC_API_KEY")
    print("  2. Run: python scripts/migrate-db.py")
    print("  3. Run: cd scripts/brain-bot && pip install -r requirements.txt && python app.py")
    print("")
    print("For auto-start on macOS:")
    print("  cp scripts/brain-bot/launchd/com.brain.telegram-bot.plist ~/Library/LaunchAgents/")
    print("  launchctl load ~/Library/LaunchAgents/com.brain.telegram-bot.plist")


if __name__ == "__main__":
    main()
