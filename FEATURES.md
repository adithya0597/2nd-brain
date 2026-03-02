# Feature Specifications: AI-Powered Local Second Brain

## 1. Frictionless Capture & Journaling
* **Zero-Friction Input:** A system designed to accept raw, unformatted text. Users can log 1-3 line entries at any time without worrying about tags, folders, or metadata.
* **Centralized Intake Pipeline:** External integrations (via MCP) automatically dump raw inputs directly into the system:
  * Voice transcripts from Tana.
  * Reading highlights from Reader/Readwise.
  * Specialized files like chess PGN data.
  * *Mechanism:* Claude Code automatically processes these "inbox" dumps and categorizes them asynchronously.

## 2. AI "Skills" (Standard Operating Procedures)
Skills represent programmable agentic behaviors stored as plain markdown files (`.md`).
* **Automated Coaching & CRM:** 
  * *Trigger:* "Process meeting note."
  * *Action:* An AI skill parses the transcript, extracts insights, generates a personalized coaching summary, and automatically structured the interactions into the CRM database (Notion/SQLite).
* **Outer World Digest:** 
  * *Trigger:* "Synthesize recent readings."
  * *Action:* Scans highlights imported from Reader. Extracts core concepts and maps them against the user's active ICOR Projects, generating a customized digest explaining *why* this information is immediately relevant.

## 3. The "Cockpit" Dashboard
A read-only management interface layer (implemented via Notion or a local HTML/JS generated view).
* **ICOR Synthesis:** Dynamically displays the hierarchy of Dimensions, Goals, and Projects. The user does not edit the dashboard; it is autonomously updated by the agent.
* **Attention Indicators:** 
  * "Red dots" or visual heatmaps indicating engagement levels.
  * The system calculates frequency of journal entries mapped to specific "Key Elements."
  * If a declared focus area is neglected for X days, the dashboard visually flags it, prompting a journal entry.

## 4. Advanced Insight & Pattern Commands
The core differentiation of the system rests in these conversational CLI commands executed via Claude Code:

* **`/context load`**: Pre-loads the AI's context window. Reads core identity files, active project states, daily notes, and backlinks to establish a holistic baseline before starting a work session.
* **`/today`**: The Morning Review. Pulls calendar events, external tasks, priority messages, and the past week's sentiments to build a hyper-prioritized daily plan.
* **`/close day`**: The Evening Review. Extracts outstanding action items, surfaces new vault connections, and validates the user's confidence markers on active hypotheses.
* **`/trace [concept]`**: Time-series analysis. Tracks how a specific idea has evolved over months (e.g., scanning 13 months of notes to generate a timeline of changing beliefs).
* **`/emerge`**: Pattern synthesis. Scans scattered, unconnected notes to surface unnamed patterns, implicit directions, or conclusions the user hasn't actively realized.
* **`/drift`**: Accountability check. Compares stated intentions (Goals in the ICOR framework) against actual journal behavior over a 30-60 day period to highlight avoidance or distraction.
* **`/challenge`**: Red-teaming. Pressure-tests current beliefs by locating contradictions or counter-evidence hidden within the user's own historical notes.
* **`/ghost`**: Digital twin simulation. Builds a custom persona based on the vault's historical data to answer a question exactly how the user would respond, allowing for self-reflection on existing biases.
* **`/connect [Domain A] [Domain B]`**: Serendipity engine. Takes two disparate domains (e.g., "Web3 Architecture" and "Screenwriting") and maps a node path between them using the vault's link graph.
* **`/graduate`**: Idea maturation. Scans recent daily notes for clustered thoughts and prompts the user to elevate them out of the journal into a standalone, evergreen concept note.
* **`Deep 30-day vault scan`**: Cross-domain brainstorming. A macro analysis of recent vault activity to suggest radical new ideas, tools to build, or media to consume based on latent interests.

## 5. Autonomous Action Generation
* **Natural Language Delegation:** The AI extracts action intents directly from conversational text in daily notes or chat.
* **Automated Routing & Tagging:** The agent assigns the correct ICOR project context and priority based on surrounding text.
* **External Task Pushing:** Connects to task managers (like Todoist or Notion tasks) to push the extracted task immediately, preserving the link back to the original thought in Obsidian.
