# LinkedIn Post — Part 2

3 weeks ago I built a Second Brain. I promised I'd share what breaks.

Here's the honest update.

**What broke:**

100 tests passed locally. 100 failed in CI. A shared mock object contaminated tests alphabetically — the first file to import config poisoned every file after it.

My system was thinking but not speaking. INSERT OR IGNORE returned row_id=0 on duplicates, so graduation proposals silently stopped sending.

**What surprised me:**

I added a knowledge graph. 381 edges. 72 nodes. 4 relationship types.

It connected documents I'd never linked myself — across topics, across weeks, through relationship types I didn't manually create.

That's the difference between retrieval and reasoning.

**The growth:**

174 → 980+ tests. 15 → 42 modules. 7K → 35K lines of code. 1 search channel → 4, fused via Reciprocal Rank Fusion.

**Am I still using it?**

Not every day yet. But every time I do, it connects things I didn't.

Part 1 was making journaling disappear. Part 2 is what happens when your notes start thinking for themselves.

Architecture breakdown coming on Medium.

What's the most surprising bug you've shipped?

#SecondBrain #KnowledgeGraph #BuildInPublic #GraphRAG #AIEngineering
