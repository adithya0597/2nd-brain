#!/usr/bin/env python3
"""Archive deprecated Slack channels that were consolidated in Sprint 4.

Usage:
    python scripts/archive-channels.py --dry-run   # Preview what would be archived
    python scripts/archive-channels.py              # Actually archive channels
"""
import argparse
import os
import sys

try:
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError
except ImportError:
    print("slack_sdk not installed. Run: pip install slack_sdk")
    sys.exit(1)

# Channels consolidated in Sprint 4 (16->4 channel architecture)
DEPRECATED_CHANNELS = [
    "brain-health",
    "brain-wealth",
    "brain-relations",
    "brain-growth",
    "brain-purpose",
    "brain-systems",
    "brain-actions",
    "brain-drift",
    "brain-ideas",
    "brain-projects",
    "brain-resources",
]


def resolve_channel_id(client: WebClient, name: str) -> str | None:
    """Find channel ID by name."""
    try:
        resp = client.conversations_list(types="public_channel,private_channel", limit=200)
        for ch in resp.get("channels", []):
            if ch["name"] == name:
                return ch["id"]
    except SlackApiError as e:
        print(f"  Error listing channels: {e}")
    return None


def archive_channel(client: WebClient, channel_id: str, name: str, dry_run: bool) -> bool:
    """Archive a single channel."""
    if dry_run:
        print(f"  [DRY RUN] Would archive #{name} ({channel_id})")
        return True
    try:
        client.conversations_archive(channel=channel_id)
        print(f"  Archived #{name} ({channel_id})")
        return True
    except SlackApiError as e:
        if "already_archived" in str(e):
            print(f"  Already archived: #{name}")
            return True
        print(f"  Failed to archive #{name}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Archive deprecated brain channels")
    parser.add_argument("--dry-run", action="store_true", help="Preview without archiving")
    args = parser.parse_args()

    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        print("SLACK_BOT_TOKEN not set. Export it or add to .env")
        sys.exit(1)

    client = WebClient(token=token)

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Archiving {len(DEPRECATED_CHANNELS)} deprecated channels:\n")

    success = 0
    for name in DEPRECATED_CHANNELS:
        channel_id = resolve_channel_id(client, name)
        if channel_id:
            if archive_channel(client, channel_id, name, args.dry_run):
                success += 1
        else:
            print(f"  Channel #{name} not found (may already be archived)")
            success += 1  # Count as success if not found

    print(f"\nResult: {success}/{len(DEPRECATED_CHANNELS)} channels processed")


if __name__ == "__main__":
    main()
