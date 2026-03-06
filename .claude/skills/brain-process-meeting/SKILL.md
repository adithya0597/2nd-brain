---
name: brain-process-meeting
description: >
  Use this skill when the user has a meeting transcript, recording summary, or raw
  meeting notes they want processed — extracting participants, decisions, action items,
  and follow-ups, then routing everything to the right systems. This covers any request
  to parse meeting content, create structured meeting notes from a transcript, update
  the CRM with attendee check-ins, or push meeting action items to Notion Tasks. Also
  use when the user drops a transcript and wants it fully processed end-to-end.
  Distinguished from brain-process-inbox (which handles freeform captures like quick
  thoughts and web clips, not structured meetings with attendees and agendas).
---

# brain-process-meeting — Process Meeting Transcript

Parse a meeting transcript, extract structured information, and distribute to the appropriate systems.

## Steps

### 1. Resolve Date

Resolve today's date using `date +%Y-%m-%d`.

### 2. Load the Transcript

Extract the meeting file path from the user's message, if provided. Otherwise:
- Check `vault/Inbox/` for recent meeting-like files
- Check `vault/Meetings/` for the most recently modified file
- Ask the user which file to process

### 3. Parse the Transcript

Analyze the meeting content to extract:

a. **Participants:** Names mentioned, attendees listed
b. **Key Discussion Points:** Main topics covered
c. **Decisions Made:** Statements of agreement, commitments, conclusions
d. **Action Items:** Tasks assigned with owners where identified
   - Look for: "will do", "action:", "TODO", "[name] to [verb]", "follow up", "next steps"
e. **Follow-ups:** Items to revisit, pending questions
f. **ICOR Elements:** Match discussion topics to Key Elements from `vault/Identity/ICOR.md`

### 4. Create Formatted Meeting Note

Read the template from `vault/Templates/Meeting.md` and create a structured note:
- File: `vault/Meetings/YYYY-MM-DD-[Topic].md`
- Fill in all template sections with extracted data
- Set frontmatter: type, date, participants, icor_elements, crm_synced: false

### 5. Update People in Notion

For each participant identified:
a. Use `notion-search` to find them in the People DB (`collection://231fda46-1a19-811c-ac4d-000b87d02a66`)
b. If found, use `notion-update-page` to update their "Last Check-In" date to today
c. If not found, offer to create a new People entry with `notion-create-pages`:
   - Properties: Full Name, Relationship (default: "Colleague")
d. Read `data/notion-registry.json` for any existing people mappings

### 6. Push Action Items to Notion Tasks

For each action item extracted:
a. Create in Notion Tasks DB (`collection://231fda46-1a19-8125-95f4-000ba3e22ea6`):
   - Properties: Name (description), Status: "To Do"
   - If participant identified as owner, set People relation
b. Insert into local SQLite. Run against `data/brain.db` using `sqlite3`:
```sql
INSERT INTO action_items (description, source_file, source_date, status, icor_element, external_system)
VALUES ('<action>', '<meeting_file>', date('now'), 'pushed_to_notion', '<element>', 'notion_tasks');
```

### 7. Insert Journal Entry

Run against `data/brain.db` using `sqlite3`:
```sql
INSERT INTO journal_entries (date, content, icor_elements, summary, file_path)
VALUES (date('now'), '<meeting summary>', '<json elements>', '<brief summary>', '<meeting_file_path>');
```

### 8. Update Meeting Note Frontmatter

Set `crm_synced: true` in the meeting note's frontmatter after Notion updates complete.

### 9. Report

```markdown
## Meeting Processed: [Topic]

**Date:** [date]
**Participants:** [list]
**ICOR Elements:** [list]

**Decisions:** [count]
**Action Items:** [count] (pushed to Notion Tasks)
**People Updated:** [count] in Notion CRM
**Follow-ups:** [count]

Meeting note saved: `vault/Meetings/[filename]`
```
