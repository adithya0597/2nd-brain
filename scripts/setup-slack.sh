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

# Welcome messages per channel
declare -A WELCOME_MSGS
WELCOME_MSGS["brain-inbox"]="Welcome to *#brain-inbox*. Drop any thought, idea, or capture here. The bot will automatically classify it by ICOR dimension and route it to the right channel. Actionable items are also saved to your action list."
WELCOME_MSGS["brain-daily"]="Welcome to *#brain-daily*. This channel receives your morning briefings (7am) and evening review prompts (9pm). Use \`/brain-today\` for an on-demand briefing or \`/brain-close\` for an evening review."
WELCOME_MSGS["brain-actions"]="Welcome to *#brain-actions*. Action items extracted from journal entries and captures appear here with interactive buttons: Complete, Snooze, or Delegate."
WELCOME_MSGS["brain-dashboard"]="Welcome to *#brain-dashboard*. Your ICOR heatmap, attention scores, and project status are posted here twice daily (6am, 6pm). Use \`/brain-status\` for an on-demand refresh."
WELCOME_MSGS["brain-ideas"]="Welcome to *#brain-ideas*. AI-generated idea and opportunity reports land here. Use \`/brain-ideas\` to trigger one manually."
WELCOME_MSGS["brain-drift"]="Welcome to *#brain-drift*. Weekly drift reports (Sunday 6pm) analyze the gap between your stated goals and actual journaling focus. Use \`/brain-drift\` anytime."
WELCOME_MSGS["brain-insights"]="Welcome to *#brain-insights*. Pattern synthesis, ghost reflections, and trace timelines are posted here. Use \`/brain-emerge\` or \`/brain-ghost\` to generate insights on demand."
WELCOME_MSGS["brain-health"]="Welcome to *#brain-health*. Captures related to *Health & Vitality* (fitness, nutrition, mental health, sleep) are routed here from #brain-inbox."
WELCOME_MSGS["brain-wealth"]="Welcome to *#brain-wealth*. Captures related to *Wealth & Finance* (investments, budgets, income, expenses) are routed here from #brain-inbox."
WELCOME_MSGS["brain-relations"]="Welcome to *#brain-relations*. Captures related to *Relationships* (family, friends, networking, social) are routed here from #brain-inbox."
WELCOME_MSGS["brain-growth"]="Welcome to *#brain-growth*. Captures related to *Mind & Growth* (learning, reading, skill development, education) are routed here from #brain-inbox."
WELCOME_MSGS["brain-purpose"]="Welcome to *#brain-purpose*. Captures related to *Purpose & Impact* (career, mission, leadership, legacy) are routed here from #brain-inbox."
WELCOME_MSGS["brain-systems"]="Welcome to *#brain-systems*. Captures related to *Systems & Environment* (tools, workflows, automation, organization) are routed here from #brain-inbox."
WELCOME_MSGS["brain-projects"]="Welcome to *#brain-projects*. Weekly project summaries (Monday 9am), cross-dimensional project views, and project-related captures cross-posted from #brain-inbox appear here. Use \`/brain-projects\` for an on-demand project dashboard."
WELCOME_MSGS["brain-resources"]="Welcome to *#brain-resources*. Monthly resource digests (1st of month, 10am), knowledge base catalogs, and resource-related captures cross-posted from #brain-inbox appear here. Use \`/brain-resources\` for an on-demand resource catalog."

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
print(json.dumps({'name': '$name', 'is_private': False}))
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
    welcome="${WELCOME_MSGS[$name]:-Welcome to #$name.}"
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
