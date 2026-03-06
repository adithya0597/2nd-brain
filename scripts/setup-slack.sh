#!/usr/bin/env bash
#
# setup-slack.sh — Create and configure Second Brain Slack channels.
#
# Usage: ./scripts/setup-slack.sh
#
# Reads SLACK_BOT_TOKEN from .env (or environment).
# Idempotent: skips channels that already exist.
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Load .env if present
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    # shellcheck disable=SC2046
    export $(grep -v '^#' "$PROJECT_ROOT/.env" | grep -v '^\s*$' | xargs)
fi

if [[ -z "${SLACK_BOT_TOKEN:-}" ]]; then
    echo "ERROR: SLACK_BOT_TOKEN not set. Add it to .env or export it."
    exit 1
fi

API="https://slack.com/api"

# -----------------------------------------------------------------------
# Channel definitions: name|topic|purpose
# -----------------------------------------------------------------------
CHANNELS=(
    "brain-inbox|Capture anything here|Drop thoughts here. Bot routes to the right dimension."
    "brain-daily|Morning briefings & evening reviews|Morning briefings and evening reviews."
    "brain-actions|Action items with interactive buttons|Action items extracted from your journal and captures."
    "brain-dashboard|ICOR heatmap & project status|ICOR heatmap, attention scores, project status."
    "brain-ideas|Idea generation reports|Generated ideas and opportunity reports."
    "brain-drift|Alignment analysis|Alignment analysis: intentions vs behavior."
    "brain-insights|Pattern synthesis & reflections|Pattern synthesis, ghost reflections, trace timelines."
    "brain-health|Health & Vitality|Health & Vitality — fitness, nutrition, mental health."
    "brain-wealth|Wealth & Finance|Wealth & Finance — investments, budgets, income."
    "brain-relations|Relationships|Relationships — family, friends, networking."
    "brain-growth|Mind & Growth|Mind & Growth — learning, reading, skill development."
    "brain-purpose|Purpose & Impact|Purpose & Impact — career, mission, legacy."
    "brain-systems|Systems & Environment|Systems & Environment — tools, workflows, organization."
    "brain-projects|Active projects & cross-dimensional tracking|Active projects, milestones, and cross-dimensional project views."
    "brain-resources|Reference materials & knowledge bases|Reference materials, tools, templates, and knowledge base catalog."
)

# Welcome message lookup (bash 3.x compatible — no associative arrays)
get_welcome_msg() {
    case "$1" in
        brain-inbox)    echo "Welcome to *#brain-inbox*. Drop any thought, idea, or capture here. The bot will automatically classify it by ICOR dimension and route it to the right channel.";;
        brain-daily)    echo "Welcome to *#brain-daily*. Morning briefings (7am) and evening reviews (9pm). Use \`/brain-today\` or \`/brain-close\` on demand.";;
        brain-actions)  echo "Welcome to *#brain-actions*. Action items with interactive buttons: Complete, Snooze, or Delegate.";;
        brain-dashboard) echo "Welcome to *#brain-dashboard*. ICOR heatmap and project status posted twice daily (6am, 6pm). Use \`/brain-status\` anytime.";;
        brain-ideas)    echo "Welcome to *#brain-ideas*. AI-generated idea reports. Use \`/brain-ideas\` to trigger one.";;
        brain-drift)    echo "Welcome to *#brain-drift*. Weekly drift reports (Sunday 6pm). Use \`/brain-drift\` anytime.";;
        brain-insights) echo "Welcome to *#brain-insights*. Pattern synthesis and reflections. Use \`/brain-emerge\` or \`/brain-ghost\`.";;
        brain-health)   echo "Welcome to *#brain-health*. Health & Vitality captures routed from #brain-inbox.";;
        brain-wealth)   echo "Welcome to *#brain-wealth*. Wealth & Finance captures routed from #brain-inbox.";;
        brain-relations) echo "Welcome to *#brain-relations*. Relationships captures routed from #brain-inbox.";;
        brain-growth)   echo "Welcome to *#brain-growth*. Mind & Growth captures routed from #brain-inbox.";;
        brain-purpose)  echo "Welcome to *#brain-purpose*. Purpose & Impact captures routed from #brain-inbox.";;
        brain-systems)  echo "Welcome to *#brain-systems*. Systems & Environment captures routed from #brain-inbox.";;
        brain-projects) echo "Welcome to *#brain-projects*. Weekly summaries (Monday 9am) and project views. Use \`/brain-projects\`.";;
        brain-resources) echo "Welcome to *#brain-resources*. Monthly digests (1st, 10am) and knowledge base. Use \`/brain-resources\`.";;
        *)              echo "Welcome to #$1.";;
    esac
}

# -----------------------------------------------------------------------
# Helper: call Slack API
# -----------------------------------------------------------------------
slack_api() {
    local method="$1"
    shift
    curl -s -X POST "$API/$method" \
        -H "Authorization: Bearer $SLACK_BOT_TOKEN" \
        -H "Content-Type: application/json; charset=utf-8" \
        "$@"
}

# -----------------------------------------------------------------------
# Get existing channels to check for duplicates
# -----------------------------------------------------------------------
echo "Fetching existing channels..."
EXISTING=$(slack_api "conversations.list" \
    -d '{"types":"public_channel,private_channel","limit":200}' \
    | python3 -c "
import sys, json
data = json.load(sys.stdin)
if data.get('ok'):
    for ch in data.get('channels', []):
        print(ch['name'])
" 2>/dev/null || true)

# -----------------------------------------------------------------------
# Create channels
# -----------------------------------------------------------------------
created=0
skipped=0

for entry in "${CHANNELS[@]}"; do
    IFS='|' read -r name topic purpose <<< "$entry"

    # Check if channel already exists
    if echo "$EXISTING" | grep -qx "$name"; then
        echo "  SKIP: #$name (already exists)"
        skipped=$((skipped + 1))
        continue
    fi

    echo "  CREATE: #$name"

    # Create the channel
    result=$(slack_api "conversations.create" \
        -d "$(python3 -c "
import json
print(json.dumps({'name': '$name', 'is_private': True}))
")")

    ok=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('ok', False))" 2>/dev/null || echo "False")

    if [[ "$ok" != "True" ]]; then
        error=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error', 'unknown'))" 2>/dev/null || echo "unknown")
        if [[ "$error" == "name_taken" ]]; then
            echo "    Already exists (not in initial list)"
            skipped=$((skipped + 1))
            continue
        fi
        echo "    ERROR: $error"
        continue
    fi

    channel_id=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin)['channel']['id'])" 2>/dev/null)

    # Set topic
    slack_api "conversations.setTopic" \
        -d "$(python3 -c "
import json
print(json.dumps({'channel': '$channel_id', 'topic': '$topic'}))
")" > /dev/null

    # Set purpose
    slack_api "conversations.setPurpose" \
        -d "$(python3 -c "
import json
print(json.dumps({'channel': '$channel_id', 'purpose': '$purpose'}))
")" > /dev/null

    # Post welcome message
    welcome="$(get_welcome_msg "$name")"
    slack_api "chat.postMessage" \
        -d "$(python3 -c "
import json
print(json.dumps({'channel': '$channel_id', 'text': '''$welcome'''}))
")" > /dev/null

    created=$((created + 1))
done

echo ""
echo "Done: $created created, $skipped skipped."
echo ""
echo "Next steps:"
echo "  1. Invite the bot to each channel: /invite @YourBotName"
echo "  2. Or use the Slack API to join channels programmatically."
echo "  3. Configure slash commands in your Slack app settings:"
echo "     /brain-today, /brain-close, /brain-drift, /brain-emerge,"
echo "     /brain-ideas, /brain-schedule, /brain-ghost, /brain-status, /brain-sync,"
echo "     /brain-projects, /brain-resources"
