# /brain:sync-notion — Bidirectional Notion Sync

Synchronize data between the local vault/SQLite and the Notion "My assistant" workspace.

## Notion Database References
- Tasks: `collection://231fda46-1a19-8125-95f4-000ba3e22ea6`
- Projects: `collection://231fda46-1a19-8171-9b6d-000b3e3409be`
- Goals: `collection://231fda46-1a19-810f-b0ac-000bbab78a4a`
- Tags: `collection://231fda46-1a19-8195-8338-000b82b65137`
- Notes: `collection://231fda46-1a19-8139-a401-000b477c8cd0`
- People: `collection://231fda46-1a19-811c-ac4d-000b87d02a66`

## Steps

### 1. Load Registry
Read `data/notion-registry.json` to get existing page ID mappings.

### 2. Push: Local → Notion

#### a. Push Pending Actions to Notion Tasks
Query SQLite for actions ready to push:
```sql
SELECT id, description, icor_element, icor_project
FROM action_items
WHERE status = 'pending' AND external_id IS NULL;
```

For each action, use `notion-create-pages` with:
- Parent: `{"data_source_id": "231fda46-1a19-8125-95f4-000ba3e22ea6"}`
- Properties: `{"Name": "<description>", "Status": "To Do"}`
- If icor_project matches a known project in the registry, set the Project relation

After creation, update SQLite:
```sql
UPDATE action_items SET external_id = '<notion_page_id>', external_system = 'notion_tasks', status = 'pushed_to_notion' WHERE id = <local_id>;
```

#### b. Sync ICOR Hierarchy to Tags
For any icor_hierarchy entries without notion_page_id, check if they exist in Notion Tags DB. If not, create them:
- Use `notion-search` to check if a Tag with the same name exists
- If not found, use `notion-create-pages` to create it in the Tags data source
- Set Type to "Area" for dimensions and key_elements
- Set Parent Tag relation for key_elements
- Update icor_hierarchy in SQLite with the notion_page_id
- Update `data/notion-registry.json`

### 3. Pull: Notion → Local

#### a. Pull Active Project Statuses
Use `notion-search` to find projects in the Projects DB with Status "Doing" or "Ongoing":
- Search `collection://231fda46-1a19-8171-9b6d-000b3e3409be` for active projects
- For each project, fetch its details with `notion-fetch`
- Update `vault/Identity/Active-Projects.md` with current statuses

#### b. Pull Goal Progress
Use `notion-search` in the Goals DB for non-archived goals:
- Search `collection://231fda46-1a19-810f-b0ac-000bbab78a4a` for active/dream goals
- Update ICOR.md's goal references if needed

#### c. Pull People Updates
Use `notion-search` in People DB for recently edited contacts:
- Note any new check-ins or relationship updates

### 4. Log Sync Operations
For each operation, insert into SQLite:
```sql
INSERT INTO vault_sync_log (operation, source_file, target, status, details)
VALUES ('<operation>', '<source>', '<target>', 'success', '<details>');
```

### 5. Update Registry
Write updated `data/notion-registry.json` with any new page ID mappings.

### 6. Report
Present sync summary:
- Actions pushed to Notion: [count]
- Projects pulled: [count]
- Goals updated: [count]
- ICOR tags synced: [count]
- Any failures or skips
