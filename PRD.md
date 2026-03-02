# Product Requirements Document (PRD): AI-Powered Local Second Brain

## 1. Product Overview
The objective of this product is to build a Personal Knowledge Management (PKM) system that acts as an autonomous thinking partner and an automated life manager. Rather than forcing the user to adopt heavy, manual organizational paradigms (like rigid folders or forced tagging), the system relies on an AI agent—powered by Claude Code—that interacts directly with a local file vault (Obsidian), a relational database (Notion), and a local index (SQLite). 

The AI agent organizes text, retrieves lost ideas, synthesizes scattered information, and detects latent patterns across the user's life using native natural language commands. The ultimate goal is to lower the friction of capturing knowledge to near-zero while maximizing the serendipity and utility of retrieval.

## 2. Core Methodologies

### 2.1 The ICOR Structure
Information across all systems is mapped to the user's life using the ICOR hierarchy:
- **Dimensions:** Broad life categories (e.g., Health, Wealth, Relationships).
- **Key Elements:** Specific focus areas within a dimension (e.g., "Weightlifting" or "Personal Brand").
- **Goals:** Measurable outcomes mapped to a Key Element. Goals can *only* be achieved through linked projects or habits.
- **Projects:** Ephemeral efforts with a distinct definition of done.
- **Habits/Routines:** Ongoing processes meant to sustain a standard.

### 2.2 Relational Interconnectivity
The system thrives on bidirectional linking within the Obsidian markdown vault. By connecting disparate files without strict heirarchies, the system forms a network of ideas. This non-linear structure allows the AI agent to traverse the link graph, surface latent patterns, track the evolution of concepts, and connect seemingly unrelated life domains into a cohesive worldview.

## 3. Technical Architecture Overview
The technical stack bridges local privacy with cloud-based relational structures and agentic intelligence:
* **Local File Storage (Obsidian):** The foundation is a local folder of Markdown files. This ensures privacy, offline capability, and allows the AI to traverse local link graphs seamlessly.
* **Relational Database (Notion / SQLite):** Notion is utilized for structured relational views (e.g., dynamic dashboards, task tables, CRMs) that benefit from rich UI. A local SQLite database (managed via tools like TablePlus) is used to rapidly index AI-generated summaries, structure dense metadata, and quickly query thousands of short journal entries.
* **Agentic Processing (Claude Code CLI):** The central processing agent. Given context limits, Claude Code reads local Markdown files, queries SQLite, and fetches Notion pages. It maintains persistent context about the user's life without requiring complex UI coding.
* **External Integrations (MCP Servers):** The system connects to external tools via Model Context Protocol (MCP). Tana is used for rapid voice/text capture, Readwise/Reader for highlights, and Todoist/Notion for pushing actionable tasks.

## 4. Key Functional Areas

### 4.1 Frictionless Capture & Journaling
The barrier to entry for a thought must be zero. Users log thoughts, meeting notes, chess games, or daily occurrences in basic 1-3 line entries. There are no mandatory fields. The AI agent, on its scheduled runs, parses these logs, tags them conceptually, and links them to the appropriate ICOR element. External inputs (Tana voice notes, Reader highlights) are formatted automatically via MCP pipelines.

### 4.2 AI "Skills" (Standard Operating Procedures)
The core automation relies on "Skills"—markdown-based instruction files detailing how the AI should behave. When the user drops a raw meeting transcript, the AI reads the `Meeting_CRM_Skill.md`, extracts action items, updates the Notion CRM, and generates a coaching summary.

### 4.3 The "Cockpit" Dashboard
A unified interface (likely hosted in Notion or a generated local Dashboard) providing read-only visuals of the ICOR stack. It utilizes "Attention Indicators"—AI-calculated metrics (red dots) showing how often a Key Element is mentioned in daily journals. Neglected areas are automatically flagged for user reflection.

### 4.4 Advanced CLI Commands
Through Claude Code, the user invokes specialized commands (e.g., `/trace`, `/emerge`, `/drift`) that trigger deep vault scans to challenge beliefs, surface unarticulated patterns, or synthesize months of fragmented thought into a cohesive thesis.

### 4.5 Autonomous Action Generation
The system extracts action items from passing thoughts and automatically routes them. Saying "remind me to call John about the film project" in a daily note will result in a synthesized task sent to Notion/Todoist, properly tagged under the "Film" project.

## 5. Success Metrics
* **Capture Friction:** reduction in time from 'thought generation' to 'system storage'.
* **Recall Rate:** The frequency at which the AI surfaces a forgotten but highly relevant note during a working session.
* **Goal Alignment:** Decrease in the behavioral "drift" (the gap between stated intentions and actual daily journaling focus).

## 6. Future Scope
* **Voice-Native AI Interface:** Direct voice-to-vault interaction without intermediate tools.
* **Predictive Patterning:** The AI anticipates project blockers before they happen by referencing historic project failures in the vault.
