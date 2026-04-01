"""Pure entity transforms between local and Notion property formats."""


# ---------------------------------------------------------------------------
# Status mapping
# ---------------------------------------------------------------------------

_STATUS_TO_NOTION = {"pending": "To Do", "in_progress": "Doing", "completed": "Done"}
_STATUS_FROM_NOTION = {v: k for k, v in _STATUS_TO_NOTION.items()}


# ---------------------------------------------------------------------------
# Utility extractors (read Notion page properties)
# ---------------------------------------------------------------------------

def extract_title(properties: dict, key: str = "Name") -> str:
    """Extract title text from Notion properties."""
    # Handle both "title" and "Name" as possible title property names
    title_prop = properties.get(key, {})
    title_list = title_prop.get("title", [])
    if title_list:
        return title_list[0].get("text", {}).get("content", "")
    return ""


def extract_rich_text(properties: dict, key: str) -> str:
    """Extract rich text content from a property."""
    prop = properties.get(key, {})
    rt = prop.get("rich_text", [])
    if rt:
        return rt[0].get("text", {}).get("content", "")
    return ""


def extract_select(properties: dict, key: str) -> str | None:
    """Extract select value name."""
    prop = properties.get(key, {})
    sel = prop.get("select")
    if sel:
        return sel.get("name")
    return None


def extract_status(properties: dict, key: str) -> str | None:
    """Extract status value name (Notion status property type)."""
    prop = properties.get(key, {})
    status = prop.get("status")
    if status:
        return status.get("name")
    return None


def extract_multi_select(properties: dict, key: str) -> list[str]:
    """Extract multi-select value names."""
    prop = properties.get(key, {})
    ms = prop.get("multi_select", [])
    return [item.get("name", "") for item in ms]


def extract_relation(properties: dict, key: str) -> list[str]:
    """Extract relation page IDs."""
    prop = properties.get(key, {})
    rels = prop.get("relation", [])
    return [r.get("id", "") for r in rels]


def extract_date(properties: dict, key: str) -> str | None:
    """Extract date start string (ISO format)."""
    prop = properties.get(key, {})
    date_obj = prop.get("date")
    if date_obj:
        return date_obj.get("start")
    return None


def extract_checkbox(properties: dict, key: str) -> bool:
    """Extract checkbox value."""
    prop = properties.get(key, {})
    return prop.get("checkbox", False)


def extract_number(properties: dict, key: str) -> float | None:
    """Extract number value."""
    prop = properties.get(key, {})
    return prop.get("number")


# ---------------------------------------------------------------------------
# Utility builders (build Notion property values)
# ---------------------------------------------------------------------------

def build_title_property(text: str) -> dict:
    """Build a Notion title property value."""
    return {"title": [{"text": {"content": text}}]}


def build_rich_text_property(text: str) -> dict:
    """Build a Notion rich_text property value."""
    return {"rich_text": [{"text": {"content": text}}]}


def build_select_property(value: str) -> dict:
    """Build a Notion select property value."""
    return {"select": {"name": value}}


def build_status_property(value: str) -> dict:
    """Build a Notion status property value."""
    return {"status": {"name": value}}


def build_multi_select_property(values: list[str]) -> dict:
    """Build a Notion multi_select property value."""
    return {"multi_select": [{"name": v} for v in values]}


def build_relation_property(page_ids: list[str]) -> dict:
    """Build a Notion relation property value."""
    return {"relation": [{"id": pid} for pid in page_ids]}


def build_date_property(iso_date: str) -> dict:
    """Build a Notion date property value."""
    return {"date": {"start": iso_date}}


def build_checkbox_property(value: bool) -> dict:
    """Build a Notion checkbox property value."""
    return {"checkbox": value}


def build_number_property(value: float) -> dict:
    """Build a Notion number property value."""
    return {"number": value}


# ---------------------------------------------------------------------------
# Action Items <-> Tasks
# ---------------------------------------------------------------------------

def action_to_notion_task(action: dict, registry: dict) -> dict:
    """Convert a local action_item dict to Notion Task properties.

    Args:
        action: Dict with keys from action_items table (id, description, icor_element, icor_project, status)
        registry: The notion-registry.json data for resolving project relations

    Returns:
        Dict of Notion properties ready for create_page or update_page
    """
    props = {
        "Name": build_title_property(action.get("description", "")),
        "Status": build_status_property(_STATUS_TO_NOTION.get(action.get("status", "pending"), "To Do")),
    }

    # Link to project if we can resolve it
    project_name = action.get("icor_project", "")
    if project_name and project_name in registry.get("projects", {}):
        project_notion_id = registry["projects"][project_name].get("notion_page_id")
        if project_notion_id:
            props["Project"] = build_relation_property([project_notion_id])

    # Set priority based on action source (default Medium)
    props["Priority"] = build_status_property("Medium")

    # Add description with ICOR element context
    icor_element = action.get("icor_element", "")
    if icor_element:
        props["Description"] = build_rich_text_property(f"ICOR: {icor_element}")

    return props


def notion_task_to_action(page: dict) -> dict:
    """Convert a Notion Task page to local action_item format.

    Args:
        page: Notion page object from query_database

    Returns:
        Dict with local action_item fields
    """
    props = page.get("properties", {})
    status_notion = extract_status(props, "Status") or "To Do"

    return {
        "notion_id": page.get("id", ""),
        "description": extract_title(props, "Name"),
        "status": _STATUS_FROM_NOTION.get(status_notion, "pending"),
        "priority": extract_status(props, "Priority"),
        "due_date": extract_date(props, "Due"),
        "last_edited": page.get("last_edited_time", ""),
    }


# ---------------------------------------------------------------------------
# Projects (pull-only)
# ---------------------------------------------------------------------------

def notion_project_to_local(page: dict) -> dict:
    """Convert a Notion Project page to local format.

    Returns dict with: notion_id, name, status, tag_ids, goal_ids, deadline, archived
    """
    props = page.get("properties", {})
    return {
        "notion_id": page.get("id", ""),
        "name": extract_title(props, "Name"),
        "status": extract_status(props, "Status"),
        "tag_ids": extract_relation(props, "Tag"),
        "goal_ids": extract_relation(props, "Goal"),
        "deadline": extract_date(props, "Target Deadline"),
        "archived": extract_checkbox(props, "Archived"),
        "last_edited": page.get("last_edited_time", ""),
    }


# ---------------------------------------------------------------------------
# Goals (pull-only)
# ---------------------------------------------------------------------------

def notion_goal_to_local(page: dict) -> dict:
    """Convert a Notion Goal page to local format.

    Returns dict with: notion_id, name, status, tag_ids, deadline, archived
    """
    props = page.get("properties", {})
    return {
        "notion_id": page.get("id", ""),
        "name": extract_title(props, "Name"),
        "status": extract_status(props, "Status"),
        "tag_ids": extract_relation(props, "Tag"),
        "deadline": extract_date(props, "Target Deadline"),
        "archived": extract_checkbox(props, "Archived"),
        "last_edited": page.get("last_edited_time", ""),
    }


# ---------------------------------------------------------------------------
# ICOR Tags (bidirectional)
# ---------------------------------------------------------------------------

def icor_element_to_notion_tag(element: dict, parent_notion_id: str = None) -> dict:
    """Convert a local ICOR hierarchy element to Notion Tag properties.

    Args:
        element: Dict from icor_hierarchy (id, level, name, parent_name, etc.)
        parent_notion_id: Notion page ID of the parent tag (for key_elements)

    Returns:
        Notion properties dict
    """
    props = {
        "Name": build_title_property(element.get("name", "")),
        "Type": build_select_property("Area"),  # All ICOR elements are Areas
    }

    if parent_notion_id:
        props["Parent Tag"] = build_relation_property([parent_notion_id])

    return props


def notion_tag_to_icor(page: dict) -> dict:
    """Convert a Notion Tag page to local ICOR format.

    Returns dict with: notion_id, name, type, parent_tag_ids, archived
    """
    props = page.get("properties", {})
    return {
        "notion_id": page.get("id", ""),
        "name": extract_title(props, "Name"),
        "type": extract_select(props, "Type"),
        "parent_tag_ids": extract_relation(props, "Parent Tag"),
        "sub_tag_ids": extract_relation(props, "Sub-Tags"),
        "archived": extract_checkbox(props, "Archived"),
        "last_edited": page.get("last_edited_time", ""),
    }


# ---------------------------------------------------------------------------
# Journal Entries -> Notes (push, summary-only)
# ---------------------------------------------------------------------------

def journal_to_notion_note(entry: dict, registry: dict) -> dict:
    """Convert a journal entry to Notion Notes DB properties (summary-only).

    Only pushes metadata: date, mood, energy, ICOR elements, summary.
    Full content stays in Obsidian.

    Args:
        entry: Dict from journal_entries table
        registry: notion-registry.json data

    Returns:
        Notion properties dict for Notes DB
    """
    date_str = entry.get("date", "")
    mood = entry.get("mood", "")
    energy = entry.get("energy", "")
    icor_elements_str = entry.get("icor_elements", "")

    # Build title: "Daily — YYYY-MM-DD"
    title = f"Daily — {date_str}" if date_str else "Daily Note"

    props = {
        "Name": build_title_property(title),
        "Type": build_select_property("Daily"),
        "Note Date": build_date_property(date_str) if date_str else {},
    }

    # Remove empty Note Date if no date
    if not date_str:
        props.pop("Note Date", None)

    # Append metadata to title (Notes DB has no Description property)
    meta_parts = []
    if mood:
        meta_parts.append(mood)
    if energy:
        meta_parts.append(energy)
    if meta_parts:
        props["Name"] = build_title_property(f"{title} ({' / '.join(meta_parts)})")

    # Link to ICOR tags via relation
    if icor_elements_str:
        elements = [e.strip() for e in icor_elements_str.split(",") if e.strip()]
        tag_ids = []
        for el in elements:
            # Check key_elements first, then dimensions
            if el in registry.get("key_elements", {}):
                nid = registry["key_elements"][el].get("notion_page_id")
                if nid:
                    tag_ids.append(nid)
            elif el in registry.get("dimensions", {}):
                nid = registry["dimensions"][el].get("notion_page_id")
                if nid:
                    tag_ids.append(nid)
        if tag_ids:
            props["Tag"] = build_relation_property(tag_ids)

    return props


# ---------------------------------------------------------------------------
# Concepts -> Notes (push)
# ---------------------------------------------------------------------------

def concept_to_notion_note(concept: dict, registry: dict) -> dict:
    """Convert a concept to Notion Notes DB properties.

    Args:
        concept: Dict from concept_metadata table
        registry: notion-registry.json data

    Returns:
        Notion properties dict for Notes DB
    """
    name = concept.get("name", "")
    status = concept.get("status", "seedling")
    icor_elements_str = concept.get("icor_elements", "")

    # Map concept status to Note type
    note_type = "Idea" if status == "seedling" else "Reference"

    props = {
        "Name": build_title_property(name),
        "Type": build_select_property(note_type),
    }

    # Append metadata to title (Notes DB has no Description property)
    mention_count = concept.get("mention_count", 0)
    last_mentioned = concept.get("last_mentioned", "")
    meta_parts = [status]
    if mention_count:
        meta_parts.append(f"{mention_count} mentions")
    if meta_parts:
        props["Name"] = build_title_property(f"{name} ({', '.join(meta_parts)})")

    # Set note date to last_mentioned
    if last_mentioned:
        props["Note Date"] = build_date_property(last_mentioned)

    # Link to ICOR tags
    if icor_elements_str:
        elements = [e.strip() for e in icor_elements_str.split(",") if e.strip()]
        tag_ids = []
        for el in elements:
            if el in registry.get("key_elements", {}):
                nid = registry["key_elements"][el].get("notion_page_id")
                if nid:
                    tag_ids.append(nid)
        if tag_ids:
            props["Tag"] = build_relation_property(tag_ids)

    return props


# ---------------------------------------------------------------------------
# People (pull-primary)
# ---------------------------------------------------------------------------

def notion_person_to_local(page: dict) -> dict:
    """Convert a Notion People page to local format.

    Returns dict with: notion_id, name, relationship, email, phone, company,
                       tag_ids, last_edited
    """
    props = page.get("properties", {})
    return {
        "notion_id": page.get("id", ""),
        "name": extract_title(props, "Full Name"),
        "relationship": extract_select(props, "Relationship"),
        "email": extract_rich_text(props, "Email"),
        "phone": extract_rich_text(props, "Phone"),
        "company": extract_rich_text(props, "Company"),
        "tag_ids": extract_relation(props, "Tags"),
        "birthday": extract_date(props, "Birthday"),
        "last_checkin": extract_date(props, "Last Check-In"),
        "last_edited": page.get("last_edited_time", ""),
    }
