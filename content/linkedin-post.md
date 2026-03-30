---
type: linkedin-post
format: plain text (no markdown rendering on LinkedIn)
character_count: ~2967
target: 1500-2000 chars
linkedin_limit: 3000 chars
status: review
date: 2026-03-08
---

<!-- markdownlint-disable MD041 MD018 -->

I built a system that makes me want to journal. Not because it made me disciplined. Because it made journaling disappear.

I have the memory of a goldfish. Names? Gone in 30 seconds. That brilliant shower idea? Evaporated before I could find my phone.

Pretty sure it's ADHD. My 47 open browser tabs agree.

What really bothered me though — I'd have an idea about, say, a product architecture while reading about fitness routines. And I KNEW it connected to something I'd thought about 3 weeks ago. But I could never find it. Never connect it. The insight just... died.

And journaling? Please. I've started and quit more journals than I can count. Usually on day 1. The friction of opening an app, staring at a blank page, trying to be "reflective" — it killed it every time.

So I built a Second Brain. Literally — a Telegram bot I text like a friend. Zero friction. Waiting in line? Text a thought. 3am idea? Text it. No app to open, no template to fill, no blank page judging me.

The bot automatically classifies every thought into 6 life dimensions (Health, Wealth, Relationships, Growth, Purpose, Systems) using a 5-tier AI pipeline. the pipeline is designed so that ~95% of classification resolves locally with keywords and embeddings before ever touching an LLM.

It builds a knowledge graph that connects ideas across domains automatically. That shower thought about product architecture? It gets linked to the fitness insight from 3 weeks ago because they share structural patterns.

Every morning it tells me what actually deserves my attention — not everything, just the stuff that connects to what I'm already working on. At night, it pulls action items out of whatever I rambled about that day. And I can search anything I've ever captured in under a second.

Under the hood it's Telegram, SQLite, Obsidian, and Notion sync — event-driven graph updates, 673 tests across 6 sprints. Estimated daily AI cost: ~$0.15.

In my last article, I introduced Fixed Entity Architecture — the idea that knowledge graphs work better when YOU define the structure, not the LLM. This is that same principle, applied to my own brain.

The fixed structure is ICOR — Input, Control, Output, Refine (a framework I adapted into those same 6 life dimensions). Every new thought instantly connects to it via cosine similarity. No manual tagging. Just text the bot and the graph grows.

I finished the prototype yesterday. I'll be sharing the full architecture breakdown, what worked, what didn't, and what I'd do differently.

But the result that surprised me most? My Second Brain makes me actually want to journal. Because it's not journaling. It's just texting.

This is day one. Follow along — I'll share what breaks, what surprises me, and whether I'm still using this in 6 months.

What kills your note-taking habit? For me it was always the blank page.

#SecondBrain #AIEngineering #KnowledgeGraph #PersonalKnowledgeManagement #TelegramBot #BuildInPublic #FixedEntityArchitecture
