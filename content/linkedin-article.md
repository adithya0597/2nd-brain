---
type: linkedin-article
format: long-form article
word_count: ~2260
status: review
date: 2026-03-08
author: Bala Adithya Malaraju
---

# I Built a Second Brain Because I Couldn't Trust My First One

I met someone at a conference last month. We talked for 20 minutes about knowledge graphs, microservices, and our favorite ramen spots. Great conversation. Genuinely interesting person.

I couldn't remember their name by the time I reached my car.

This isn't new for me. Numbers vanish from my memory the moment I hear them. Dates require three calendar reminders and a sticky note. I once had a genuinely breakthrough idea about event-driven architectures while shampooing my hair. By the time I found my phone, I could only remember it involved "events" and "something clever." Very helpful.

I joke that it might be undiagnosed ADHD. My browser currently has 47 tabs open across 3 windows, which feels like strong supporting evidence.

What actually kept me up at night: I kept having ideas that I *knew* connected to something I had thought about weeks ago. I could feel the connection. I just could never find it, never trace it back, never close the loop. The insight would die in the gap between my scattered notes, half-finished journals, and browser bookmarks I would never revisit.

So I did what any engineer would do. I built a system.

---

## The Problem Was Never Willpower

Let me tell you about my journaling graveyard. Day One? Lasted three days. Notion journal template? Two entries. Physical Moleskine? The first page has a motivational quote and the second page is blank. Obsidian daily notes? Actually stuck for a while, but only because I was more interested in configuring plugins than writing.

Every system failed for the same reasons. You have to remember to open it. You're greeted by a blank page that silently judges you. There's no immediate payoff — you write something and get... nothing back. And organizing entries? That's a whole second job that nobody signed up for.

I didn't need more willpower. I didn't need a better template or a fancier app. I needed a system that removed every single point of friction between having a thought and capturing it. And then I needed that system to do something *useful* with the thought — automatically, immediately, without me lifting a finger.

---

## The Spark: From Enterprise Knowledge Graphs to a Personal Life OS

A few months ago, I published an article here on LinkedIn called "Why I Stopped Letting LLMs Build My Knowledge Graphs." It introduced an architecture I called Fixed Entity Architecture (FEA) — a pattern for enterprise code migration where you pre-define a fixed ontology of known entities (services, APIs, data stores) and let new documents connect to that ontology automatically via embedding similarity. No manual tagging. No graph rebuilds. Just cosine similarity against a stable set of reference nodes.

That article was about microservices. But the core insight kept nagging at me: if a fixed ontology works for organizing thousands of code files, why wouldn't it work for organizing a life?

Your life already has a fixed structure. You have your health. Your finances. Your relationships. Your personal growth. Your sense of purpose. Your daily systems. These don't change week to week. What changes is the *content* — the thoughts, ideas, tasks, and connections that flow through these categories every day.

I call this the ICOR Framework — Input, Control, Output, Refine — adapted into six life dimensions that form the stable backbone of everything.

- **Health & Vitality** — fitness, nutrition, sleep, mental health
- **Wealth & Finance** — income, investments, career growth, side projects
- **Relationships** — family, friends, professional network, romance
- **Mind & Growth** — reading, skill acquisition, education, creativity
- **Purpose & Impact** — personal brand, content creation, mentoring, giving back
- **Systems & Environment** — productivity systems, home, digital tools

These six dimensions are the fishbone — the fixed layer that never changes. Every thought, every idea, every late-night realization connects to one or more of them. If you read the FEA article, this is where it comes full circle — the same fixed-ontology-plus-cosine-similarity pattern, applied to a life instead of a codebase. The question was just: how do you make that connection happen without thinking about it?

---

## What I Actually Built

A Second Brain — in the form of a Telegram bot. You text it like you would text a friend, and it does the rest.

Waiting in line at the grocery store and remember you need to rebalance your portfolio? Text the bot. 3am idea about a side project? Text the bot. Overheard something interesting at a meeting? Text the bot. No app to open, no template to fill out, no blank page staring back at you.

The engineering under the hood is what I'm most proud of.

**The 5-tier classification pipeline.** Every message you send hits a cascading classifier that tries to categorize it with the cheapest method first. Tier 0 is a regex noise filter — greetings, "lol," one-word replies get caught and discarded. Tier 1 is keyword matching against a dynamically expanding dictionary. Tier 1.5 is zero-shot classification using cosine similarity against 5 reference sentences per dimension. Tier 2 is full embedding similarity using bge-small-en-v1.5. And Tier 3, the expensive one, is Claude Haiku — but by the time you get there, the pipeline is designed so that roughly 95% of messages resolve before reaching this tier. The average classification takes single-digit milliseconds. The entire pipeline is designed so that you almost never need to call an LLM for something as routine as "where does this thought go?"

**The knowledge graph.** Every piece of content becomes a node in a graph backed by SQLite with four types of edges: wikilinks (explicit references you write), tag-shared edges (documents sharing the same tags), semantic similarity edges (computed via vector KNN with a 0.5 similarity threshold), and ICOR affinity edges (cosine similarity between document embeddings and dimension reference embeddings). New content connects to existing nodes automatically. No manual linking required.

**Event-driven updates.** There's no nightly batch job rebuilding the graph. Every time you text the bot, a post-write hook fires: the vault index updates, the FTS5 index updates, the embedding gets computed, ICOR affinity edges recalculate, tag-shared and semantic similarity edges update, and community detection reruns. The graph is always current.

**Hybrid search.** When you search with `/find`, four channels run simultaneously — vector similarity, FTS5 full-text search, and graph traversal — and the results are fused using Reciprocal Rank Fusion. Response time targets sub-second latency.

The bot runs on an Obsidian vault (plain markdown files), a SQLite database, and syncs bidirectionally with Notion. It supports 23 slash commands, each designed to surface a different kind of insight:

- `/today` generates a morning briefing from your active projects, pending actions, and dimension signals
- `/close` runs an evening review that extracts action items from the day and re-indexes your journal
- `/drift` compares where you *say* your priorities are versus where your actual attention has been going
- `/emerge` surfaces unnamed patterns — recurring themes that span multiple entries but you never explicitly labeled
- `/connect` is my favorite: give it two unrelated domains and it finds serendipitous connections between them via graph intersection

Here's how `/connect` is designed to work. You give it two domains — say, "fitness" and "side projects" — and it finds intersection nodes in the knowledge graph. If your daily notes mention both morning workouts and evening coding sessions, the graph surfaces that bridge. The insight you would never assemble manually across weeks of scattered entries — energy management IS project management — becomes visible through structure.

- `/ghost` answers a question the way *you* would answer it, based on your documented values and thinking patterns — a digital twin
- `/find` runs the hybrid search across all four channels for any query you throw at it

Each command loads context through a graph-aware pipeline. For example, `/trace` seeds from files mentioning your topic, then expands two hops outward through the graph. `/ghost` seeds from your identity files — your ICOR hierarchy and stated values — and traverses two hops to gather evidence of how you actually think. The context is always scoped, never the whole vault.

---

## Why Telegram Changed Everything

Why does this one actually stick?

**It's already on your phone.** You don't need to download an app, create an account, or remember a URL. Telegram is just there, sitting next to your other messaging apps. The intelligence lives in the backend — the classifier, the graph, the search engine. Telegram is just the interface with the least friction. You could wire this to WhatsApp, iMessage, or email. I picked the one I already had open.

**Texting is frictionless.** The cognitive gap between "I had a thought" and "I captured it" is exactly the same as the gap between "I had a thought" and "I texted a friend about it." Which is to say: zero.

**Instant feedback.** This is the one that surprised me most. When you text the bot, it immediately responds with the classification, any connections it found to existing content, and where it routed the thought. You get a little dopamine hit every time. "Oh, this connected to that idea from last Tuesday? Interesting." That loop — capture, classify, connect, reward — is what keeps you coming back. It turns journaling from a chore into a curiosity engine.

**No organizing required.** The 5-tier classifier does it automatically. Forum Topics in the Telegram group keep everything visually organized — one topic for daily notes, one for actions, one for each dimension, one for insights. You never manually file anything.

**Free and self-hostable.** Telegram's bot API is free. The whole stack is Python, SQLite, and long-polling. No webhook, no public endpoint, no cloud deployment, no subscription. It runs on my laptop with a launchd service. The estimated AI cost is roughly $0.15 per day based on the escalating classifier design.

For the first time, I'm actually motivated to keep journaling. Not because I should, but because every time I use it, the system gives me something back I didn't expect.

---

## What Comes Next

This system is a working prototype. I finished the current version yesterday, and I'm already planning the next iteration.

Coming soon: Google Calendar integration for passive signal acquisition — your calendar events are data about your life dimensions too, and right now that signal is being ignored. Progressive complexity rollout, so the system starts with just capture and classification and gradually reveals the graph, the analytics, and the alerts as you build the habit. And deeper cross-dimensional pattern analysis, because the most interesting insights live at the intersection of dimensions — a fitness routine that affects your productivity, a relationship that shapes your career thinking.

I built this entire system — the bot, the graph, the classifier, the sync engine — using Claude Code with parallel agent swarms. Six agents migrated the codebase from Slack to Telegram simultaneously, each owning a different module. The agents coordinated through a shared task list and handoff files.

It wasn't all clean. My first knowledge graph had 180 meaningless edges — everything connected to everything because my similarity threshold was too generous. A meal prep note connected to "Mind & Growth" because learning recipes technically counts as "growth." Technically true. Practically useless. I had to raise the threshold from 0.3 to 0.52 and limit each file to its top 2 dimensions before the connections actually meant something.

That swarm-based development workflow — task isolation, shared context, parallel agents — deserves its own post.

---

## The Takeaway

If you have ever lost a great idea, forgotten a name five seconds after hearing it, or abandoned a journal on day one — you don't have a discipline problem. You have a tooling problem.

What I actually learned building this: the hard part of a second brain isn't the capture mechanism or the classification pipeline. It's designing for trust. The system has to be reliable enough that when it says "this thought connects to that idea from two weeks ago," you believe it and follow the thread. That's the bar I'm building toward.

I'll be sharing updates as this project evolves. If you have built something similar, or if you would approach this differently, I would love to hear about it in the comments.

And if the Fixed Entity Architecture angle interests you, check out my previous article on applying it to enterprise knowledge graphs — the same pattern scales from microservices to life management.

---

*Bala Adithya Malaraju is an AI Engineer at Infinite Computer Solutions. He builds systems that think about thinking. Find more at bala-adithya-malaraju.vercel.app*
