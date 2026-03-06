#!/usr/bin/env python3
"""Create and configure Second Brain Slack channels. Idempotent."""
import json
import os
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).parent.parent

# Load .env
env_file = PROJECT_ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
if not TOKEN:
    print("ERROR: SLACK_BOT_TOKEN not set. Add it to .env or export it.")
    sys.exit(1)

# Channel definitions: (name, topic, purpose, welcome)
CHANNELS = [
    ("brain-inbox", "Capture anything here",
     "Drop thoughts here. Bot routes to the right dimension.",
     "Welcome to *#brain-inbox*. Drop any thought, idea, or capture here. The bot will auto-classify by ICOR dimension."),
    ("brain-daily", "Morning briefings & evening reviews",
     "Morning briefings and evening reviews.",
     "Welcome to *#brain-daily*. Briefings at 7am, reviews at 9pm. Use `/brain-today` or `/brain-close` on demand."),
    ("brain-actions", "Action items with interactive buttons",
     "Action items extracted from your journal and captures.",
     "Welcome to *#brain-actions*. Action items with Complete, Snooze, and Delegate buttons."),
    ("brain-dashboard", "ICOR heatmap & project status",
     "ICOR heatmap, attention scores, project status.",
     "Welcome to *#brain-dashboard*. Updated twice daily (6am, 6pm). Use `/brain-status` anytime."),
    ("brain-ideas", "Idea generation reports",
     "Generated ideas and opportunity reports.",
     "Welcome to *#brain-ideas*. Use `/brain-ideas` to generate idea reports."),
    ("brain-drift", "Alignment analysis",
     "Alignment analysis: intentions vs behavior.",
     "Welcome to *#brain-drift*. Weekly reports Sunday 6pm. Use `/brain-drift` anytime."),
    ("brain-insights", "Pattern synthesis & reflections",
     "Pattern synthesis, ghost reflections, trace timelines.",
     "Welcome to *#brain-insights*. Use `/brain-emerge` or `/brain-ghost` for insights."),
    ("brain-health", "Health & Vitality",
     "Health & Vitality — fitness, nutrition, mental health.",
     "Welcome to *#brain-health*. Health & Vitality captures routed from #brain-inbox."),
    ("brain-wealth", "Wealth & Finance",
     "Wealth & Finance — investments, budgets, income.",
     "Welcome to *#brain-wealth*. Wealth & Finance captures routed from #brain-inbox."),
    ("brain-relations", "Relationships",
     "Relationships — family, friends, networking.",
     "Welcome to *#brain-relations*. Relationships captures routed from #brain-inbox."),
    ("brain-growth", "Mind & Growth",
     "Mind & Growth — learning, reading, skill development.",
     "Welcome to *#brain-growth*. Mind & Growth captures routed from #brain-inbox."),
    ("brain-purpose", "Purpose & Impact",
     "Purpose & Impact — career, mission, legacy.",
     "Welcome to *#brain-purpose*. Purpose & Impact captures routed from #brain-inbox."),
    ("brain-systems", "Systems & Environment",
     "Systems & Environment — tools, workflows, organization.",
     "Welcome to *#brain-systems*. Systems & Environment captures routed from #brain-inbox."),
    ("brain-projects", "Active projects & cross-dimensional tracking",
     "Active projects, milestones, and cross-dimensional project views.",
     "Welcome to *#brain-projects*. Weekly summaries Monday 9am. Use `/brain-projects`."),
    ("brain-resources", "Reference materials & knowledge bases",
     "Reference materials, tools, templates, and knowledge base catalog.",
     "Welcome to *#brain-resources*. Monthly digests on the 1st. Use `/brain-resources`."),
]


def slack_api(method: str, payload: dict) -> dict:
    """Call a Slack Web API method."""
    data = json.dumps(payload).encode()
    req = Request(
        f"https://slack.com/api/{method}",
        data=data,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    with urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def get_existing_channels() -> set[str]:
    """Fetch names of existing channels."""
    result = slack_api("conversations.list", {
        "types": "public_channel,private_channel",
        "limit": 200,
    })
    if not result.get("ok"):
        print(f"WARNING: Could not list channels: {result.get('error')}")
        return set()
    return {ch["name"] for ch in result.get("channels", [])}


def main():
    print("Fetching existing channels...")
    existing = get_existing_channels()

    created = 0
    skipped = 0

    for name, topic, purpose, welcome in CHANNELS:
        if name in existing:
            print(f"  SKIP: #{name} (already exists)")
            skipped += 1
            continue

        print(f"  CREATE: #{name}")
        result = slack_api("conversations.create", {"name": name, "is_private": True})

        if not result.get("ok"):
            error = result.get("error", "unknown")
            if error == "name_taken":
                print("    Already exists (not in initial list)")
                skipped += 1
                continue
            print(f"    ERROR: {error}")
            continue

        channel_id = result["channel"]["id"]

        slack_api("conversations.setTopic", {"channel": channel_id, "topic": topic})
        slack_api("conversations.setPurpose", {"channel": channel_id, "purpose": purpose})
        slack_api("chat.postMessage", {"channel": channel_id, "text": welcome})

        created += 1
        time.sleep(0.3)  # Rate limit courtesy

    print(f"\nDone: {created} created, {skipped} skipped.")

    # Join all brain channels
    print("\nJoining channels...")
    joined = 0
    result = slack_api("conversations.list", {"types": "public_channel,private_channel", "limit": 200})
    if result.get("ok"):
        for ch in result.get("channels", []):
            if ch["name"].startswith("brain-"):
                join_result = slack_api("conversations.join", {"channel": ch["id"]})
                if join_result.get("ok"):
                    print(f"  JOINED: #{ch['name']}")
                    joined += 1
                else:
                    print(f"  SKIP: #{ch['name']} ({join_result.get('error', 'unknown')})")
                time.sleep(0.2)
    print(f"\nJoined {joined} channels.")


if __name__ == "__main__":
    main()
