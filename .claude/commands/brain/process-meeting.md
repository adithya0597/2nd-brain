# /brain:process-meeting — Process Meeting Transcript

Parse a meeting transcript, extract structured information, and distribute to the appropriate systems.

**Input:** `$ARGUMENTS` — optional path to meeting file. If empty, process the most recent file in `vault/Meetings/` or `vault/Inbox/`.

## Steps

### 1. Load the Transcript
If `$ARGUMENTS` provided, read that file. Otherwise:
- Check `vault/Inbox/` for recent meeting-like files
- Check `vault/Meetings/` for the most recently modified file
- Ask the user which file to process

### 2. Parse the Transcript
Analyze the meeting content to extract:

a. **Participants:** Names mentioned, attendees listed
b. **Key Discussion Points:** Main topics covered
c. **Decisions Made:** Statements of agreement, commitments, conclusions
d. **Action Items:** Tasks assigned with owners where identified
   - Look for: "will do", "action:", "TODO", "[name] to [verb]", "follow up", "next steps"
e. **Follow-ups:** Items to revisit, pending questions
f. **ICOR Elements:** Match discussion topics to Key Elements

### 3. Create Formatted Meeting Note
Read the template from `vault/Templates/Meeting.md` and create a structured note:
- File: `vault/Meetings/YYYY-MM-DD-[Topic].md`
- Fill in all template sections with extracted data
- Set frontmatter: type, date, participants, icor_elements, crm_synced: false

### 4. Update People in CRM
For each participant identified:
a. Check the Context Data section and `data/notion-registry.json` for existing people mappings
b. List mentioned attendees with suggested CRM updates for the user to apply manually or via `/brain:sync-notion`:
   - Existing contacts: suggest updating "Last Check-In" date to today
   - New contacts: suggest creating a People entry with Full Name, Relationship (default: "Colleague")

### 5. Prepare Action Items for Notion Tasks
For each action item extracted:
a. List the action items formatted for Notion Tasks DB (`collection://231fda46-1a19-8125-95f4-000ba3e22ea6`):
   - Properties: Name (description), Status: "To Do"
   - If participant identified as owner, note the People relation
b. Insert into local SQLite:
```sql
INSERT INTO action_items (description, source_file, source_date, status, icor_element, external_system)
VALUES ('<action>', '<meeting_file>', date('now'), 'pushed_to_notion', '<element>', 'notion_tasks');
```

### 6. Insert Journal Entry
```sql
INSERT INTO journal_entries (date, content, icor_elements, summary, file_path)
VALUES (date('now'), '<meeting summary>', '<json elements>', '<brief summary>', '<meeting_file_path>');
```

### 7. Update Meeting Note Frontmatter
Set `crm_synced: true` in the meeting note's frontmatter after Notion updates complete.

### 8. Report
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
