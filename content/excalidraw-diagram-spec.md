# Excalidraw Diagram Spec: Before/After Knowledge Graph

## Layout: Split Screen (Left vs Right)

### LEFT SIDE: "Before — Flat Search"
**Header text:** "Week 1: Keyword + Vector Search"

- 8-10 document boxes (rounded rectangles) scattered randomly
- Each box has a short label: "Morning Jog", "Product Idea", "Book Notes", "Meeting 3/12", "Fitness Goal", "AI Architecture", "Weekly Review", "Sleep Tracker"
- Boxes are **disconnected** — no lines between them
- A search bar at top with query: "what connects fitness to creativity?"
- Arrow from search → 2 highlighted boxes ("Morning Jog", "Fitness Goal")
- Dimmed result indicator: "2 results — both obvious"
- Color: all boxes same gray/muted blue
- Mood: isolated, static, dead

### RIGHT SIDE: "After — Knowledge Graph"
**Header text:** "Week 3: Graph + 4-Channel Search"

- Same 8-10 document boxes but now CONNECTED with colored edges:
  - **Blue solid lines** = wikilink edges (2-3 explicit links)
  - **Purple dashed lines** = semantic_similarity edges (3-4 computed connections)
  - **Green dotted lines** = tag_shared edges (2-3 tag connections)
  - **Orange lines to center** = icor_affinity edges connecting to 3 ICOR dimension circles

- 3 small colored circles at center-bottom representing ICOR dimensions:
  - Red circle: "Health"
  - Green circle: "Growth"
  - Blue circle: "Purpose"

- Same search query: "what connects fitness to creativity?"
- Arrow from search → graph traversal highlights a PATH:
  "Morning Jog" → (semantic_similarity) → "Sleep Tracker" → (wikilink) → "Weekly Review" → (tag_shared) → "Product Idea"
- Result indicator: "4 results — 2 you never connected yourself"
- The path edges glow/thicken to show traversal
- Color: vibrant, connected, alive

### BOTTOM CENTER: Stats Bar
A thin horizontal bar spanning both sides:

```
Before:  2 channels | 0 edges | keyword match only
After:   4 channels | 293 edges | graph traversal + RRF fusion
```

## Design Notes

- **Canvas size:** ~1200x675 (LinkedIn image optimal 1200x627)
- **Font:** Hand-drawn Excalidraw default (gives it the "built by a builder" feel)
- **Background:** White or very light gray
- **Divider:** Vertical dashed line between left and right
- **Arrow style:** Excalidraw hand-drawn arrows
- **Key insight:** The visual contrast between "disconnected islands" and "connected graph" is the entire story. The left side should feel empty and lonely. The right side should feel alive and buzzing.

## Alternative: Simpler Version

If the split screen is too complex, do a single graph visualization:

- Center: "Weekly Review" note (large box)
- Radiating outward: 6-8 connected notes with colored edges
- Edge labels visible: "wikilink", "similar", "shared tag", "ICOR: Health"
- 3 ICOR dimension nodes at the periphery (small colored circles)
- Title: "58 nodes. 293 edges. 4 relationship types."
- Subtitle: "Your notes already have a graph. You just haven't built it yet."

## How to Create

1. Open https://excalidraw.com
2. Use the rectangle tool for document boxes
3. Use the ellipse tool for ICOR dimension nodes
4. Use the arrow/line tool for edges (change style: solid/dashed/dotted per edge type)
5. Color edges by type (blue/purple/green/orange)
6. Add text labels
7. Export as PNG at 2x resolution (2400x1350) for crisp LinkedIn display
