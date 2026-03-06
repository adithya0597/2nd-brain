---
name: brain-process-inbox
description: >
  Use this skill when the user wants to triage, categorize, or clean up their inbox —
  any request to process unorganized captures, sort new notes into the right vault
  locations, or extract action items from freeform inbox entries. This covers voice
  transcripts, reading highlights, raw thought captures, web clips, and any other
  unprocessed material sitting in the inbox folder. Also use when the user says they
  have a backlog of unsorted notes or want to clear their capture queue. Distinguished
  from brain-today (which reviews the day's priorities, not inbox triage) and
  brain-process-meeting (which handles structured meeting transcripts with attendees
  and agendas, not freeform captures).
---

# brain-process-inbox — Process Inbox Captures

Scan the vault inbox for new/unprocessed files, categorize them, and route to appropriate locations.

## Steps

### 1. Resolve Date

Resolve today's date using `date +%Y-%m-%d`.

### 2. Scan Inbox

Use Glob to find all files in `vault/Inbox/`:
- List all `.md`, `.txt`, and other text files
- Check each file's frontmatter for a `processed: true` flag (skip those)

If inbox is empty, inform the user and exit.

### 3. Categorize Each File

For each unprocessed file, read its content and categorize:

**Voice Transcript:** Contains transcription markers, spoken language patterns, or was captured from a voice tool
- Route to: `vault/Meetings/` if it's a meeting, or process inline into a daily note

**Reading Highlight:** Contains quotes, annotations, book/article references
- Route to: `vault/Concepts/` as a new concept note, or append to existing concept

**Raw Capture:** Short thoughts, ideas, reminders
- Route to: Today's daily note (`vault/Daily Notes/YYYY-MM-DD.md`) as log entries

**Web Clip:** Contains URLs, web content
- Route to: `vault/Concepts/` or create a Notion note (Type: Web Clip)

**Meeting Notes:** Contains attendees, agenda, action items
- Route to: `vault/Meetings/YYYY-MM-DD-Topic.md` using Meeting template

### 4. Process Each File

For each categorized file:

a. **Create the destination file** using the appropriate template from `vault/Templates/`

b. **Tag with ICOR elements** by matching content against Key Elements from `vault/Identity/ICOR.md`

c. **Create backlinks** — add `[[source]]` references in the destination file

d. **Extract action items** and insert into SQLite. Run against `data/brain.db` using `sqlite3`:
```sql
INSERT INTO action_items (description, source_file, source_date, status, icor_element)
VALUES ('<action>', '<destination_file>', date('now'), 'pending', '<element>');
```

e. **Mark as processed** — either move the file out of Inbox or add `processed: true` to its frontmatter

### 5. Log Operations

Run against `data/brain.db` using `sqlite3`:

For each processed file:
```sql
INSERT INTO vault_sync_log (operation, source_file, target, status, details)
VALUES ('process_inbox', '<inbox_file>', '<destination>', 'success', '<category>');
```

### 6. Report

```markdown
## Inbox Processing Summary

| File | Category | Routed To | ICOR Elements | Actions Extracted |
|---|---|---|---|---|
| [filename] | [category] | [destination] | [elements] | [count] |

**Processed:** [X] files
**Actions extracted:** [Y] total
**Remaining in inbox:** [Z] files
```
