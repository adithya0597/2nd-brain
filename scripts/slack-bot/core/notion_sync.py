"""Notion sync orchestrator -- bidirectional sync between local data and Notion."""
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from core import db_ops
from core.notion_client import NotionClientWrapper
from core.notion_mappers import (
    action_to_notion_task,
    concept_to_notion_note,
    icor_element_to_notion_tag,
    journal_to_notion_note,
    notion_goal_to_local,
    notion_person_to_local,
    notion_project_to_local,
    notion_tag_to_icor,
    notion_task_to_action,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class SyncResult:
    """Aggregate result of a sync run."""

    tasks_pushed: int = 0
    tasks_status_synced: int = 0
    projects_pulled: int = 0
    goals_pulled: int = 0
    tags_synced: int = 0
    notes_pushed: int = 0
    concepts_pushed: int = 0
    people_synced: int = 0
    vault_files_written: int = 0
    ai_calls: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dry_run: bool = False
    dry_run_actions: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = ["DRY RUN — Notion Sync Complete:" if self.dry_run else "Notion Sync Complete:"]
        if self.tasks_pushed:
            lines.append(f"  Tasks pushed: {self.tasks_pushed}")
        if self.tasks_status_synced:
            lines.append(f"  Task statuses synced: {self.tasks_status_synced}")
        if self.projects_pulled:
            lines.append(f"  Projects pulled: {self.projects_pulled}")
        if self.goals_pulled:
            lines.append(f"  Goals pulled: {self.goals_pulled}")
        if self.tags_synced:
            lines.append(f"  Tags synced: {self.tags_synced}")
        if self.notes_pushed:
            lines.append(f"  Journal notes pushed: {self.notes_pushed}")
        if self.concepts_pushed:
            lines.append(f"  Concepts pushed: {self.concepts_pushed}")
        if self.people_synced:
            lines.append(f"  People synced: {self.people_synced}")
        if self.vault_files_written:
            lines.append(f"  Vault files written: {self.vault_files_written}")
        if self.ai_calls:
            lines.append(f"  AI decisions: {self.ai_calls}")
        if self.errors:
            lines.append(f"  Errors: {len(self.errors)}")
        if self.warnings:
            lines.append(f"  Warnings: {len(self.warnings)}")
        if self.dry_run_actions:
            lines.append(f"  Simulated actions: {len(self.dry_run_actions)}")
        # If nothing happened
        if len(lines) == 1:
            lines.append("  No changes needed")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Registry manager
# ---------------------------------------------------------------------------


class RegistryManager:
    """Manages the notion-registry.json file with atomic saves."""

    def __init__(self, path: Path):
        self._path = path
        self._data: dict = {}

    def load(self) -> dict:
        if self._path.exists():
            self._data = json.loads(self._path.read_text(encoding="utf-8"))
        else:
            self._data = {
                "_description": "Maps local ICOR hierarchy IDs to Notion page IDs.",
                "_last_synced": None,
                "dimensions": {},
                "key_elements": {},
                "goals": {},
                "projects": {},
                "dashboard_page_id": None,
            }
        return self._data

    def save(self):
        """Atomic save: write to .tmp then rename."""
        self._data["_last_synced"] = datetime.utcnow().isoformat() + "Z"
        tmp_path = self._path.with_suffix(".json.tmp")
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(json.dumps(self._data, indent=2) + "\n", encoding="utf-8")
        tmp_path.rename(self._path)

    @property
    def data(self) -> dict:
        return self._data

    def get_tag_notion_id(self, name: str) -> str | None:
        """Look up a Notion page ID for an ICOR tag by name (dimension or key_element)."""
        dim = self._data.get("dimensions", {}).get(name)
        if dim:
            return dim.get("notion_page_id")
        elem = self._data.get("key_elements", {}).get(name)
        if elem:
            return elem.get("notion_page_id")
        return None

    def get_project_notion_id(self, name: str) -> str | None:
        proj = self._data.get("projects", {}).get(name)
        if proj:
            return proj.get("notion_page_id")
        return None

    def get_goal_notion_id(self, name: str) -> str | None:
        goal = self._data.get("goals", {}).get(name)
        if goal:
            return goal.get("notion_page_id")
        return None

    def set_tag(
        self, name: str, notion_page_id: str, level: str, dimension: str = None
    ):
        if level == "dimension":
            self._data.setdefault("dimensions", {})[name] = {
                "notion_page_id": notion_page_id,
            }
        else:
            entry: dict = {"notion_page_id": notion_page_id}
            if dimension:
                entry["dimension"] = dimension
            self._data.setdefault("key_elements", {})[name] = entry

    def set_project(self, name: str, notion_page_id: str, tag: str = None, goal: str = None, status: str = None):
        entry: dict = {"notion_page_id": notion_page_id}
        if tag:
            entry["tag"] = tag
        if goal:
            entry["goal"] = goal
        if status:
            entry["status"] = status
        self._data.setdefault("projects", {})[name] = entry

    def set_goal(self, name: str, notion_page_id: str, tag: str = None, status: str = None):
        entry: dict = {"notion_page_id": notion_page_id}
        if tag:
            entry["tag"] = tag
        if status:
            entry["status"] = status
        self._data.setdefault("goals", {})[name] = entry

    def set_person(self, name: str, notion_page_id: str, **fields):
        """Store a person entry in the registry."""
        entry: dict = {"notion_page_id": notion_page_id}
        for key, val in fields.items():
            if val is not None:
                entry[key] = val
        self._data.setdefault("people", {})[name] = entry


# ---------------------------------------------------------------------------
# Sync orchestrator
# ---------------------------------------------------------------------------


def _strip_collection(collection_uri: str) -> str:
    """Strip the ``collection://`` prefix to get a bare database ID."""
    return collection_uri.replace("collection://", "")


class NotionSync:
    """Orchestrates bidirectional sync between local data and Notion."""

    def __init__(
        self,
        client: NotionClientWrapper,
        registry_path: Path,
        db_path: Path,
        vault_path: Path,
        collection_ids: dict[str, str],
        ai_client=None,
        ai_model: str = None,
        dry_run: bool = False,
    ):
        self._client = client
        self._registry = RegistryManager(registry_path)
        self._db_path = db_path
        self._vault_path = vault_path
        self._collections = collection_ids
        self._ai_client = ai_client
        self._ai_model = ai_model or "claude-sonnet-4-20250514"
        self._result = SyncResult()
        self._now = datetime.utcnow().isoformat()
        self._dry_run = dry_run

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    async def run_full_sync(self) -> SyncResult:
        """Execute the complete sync pipeline."""
        self._result = SyncResult()
        self._result.dry_run = self._dry_run
        self._registry.load()

        steps = [
            ("tags", self._sync_icor_tags),
            ("tasks_push", self._push_action_items),
            ("tasks_pull", self._pull_task_status),
            ("projects", self._pull_projects),
            ("goals", self._pull_goals),
            ("notes", self._push_journal_entries),
            ("concepts", self._push_concepts),
            ("people", self._sync_people),
        ]

        for name, step in steps:
            try:
                await step()
            except Exception as e:
                msg = f"Step '{name}' failed: {e}"
                logger.exception(msg)
                self._result.errors.append(msg)

        # Post-sync housekeeping
        if not self._dry_run:
            try:
                await self._update_vault_files()
            except Exception as e:
                self._result.errors.append(f"Vault update failed: {e}")
            self._registry.save()
        await self._log_sync_operations()

        return self._result

    async def run_selective_sync(self, entity_types: list[str]) -> SyncResult:
        """Run sync for specific entity types only."""
        self._result = SyncResult()
        self._result.dry_run = self._dry_run
        self._registry.load()

        type_to_step = {
            "tags": self._sync_icor_tags,
            "tasks": self._push_action_items,
            "tasks_pull": self._pull_task_status,
            "projects": self._pull_projects,
            "goals": self._pull_goals,
            "notes": self._push_journal_entries,
            "concepts": self._push_concepts,
            "people": self._sync_people,
        }

        for et in entity_types:
            step = type_to_step.get(et)
            if step:
                try:
                    await step()
                except Exception as e:
                    self._result.errors.append(f"Step '{et}' failed: {e}")

        if not self._dry_run:
            self._registry.save()
        return self._result

    # ------------------------------------------------------------------
    # Step 1: ICOR Tags (push unsynced local elements to Notion Tags DB)
    # ------------------------------------------------------------------

    async def _sync_icor_tags(self):
        unsynced = await db_ops.get_icor_without_notion_id(db_path=self._db_path)
        if not unsynced:
            return

        hierarchy = await db_ops.get_icor_hierarchy(db_path=self._db_path)
        parent_lookup = {row["id"]: row for row in hierarchy}

        tags_db_id = _strip_collection(self._collections["tags"])

        for element in unsynced:
            try:
                # Resolve parent Notion page ID
                parent_notion_id = None
                parent_id = element.get("parent_id")
                if parent_id:
                    parent_row = parent_lookup.get(parent_id)
                    if parent_row and parent_row.get("notion_page_id"):
                        parent_notion_id = parent_row["notion_page_id"]
                    else:
                        # Fall back to registry
                        parent_name = parent_row["name"] if parent_row else None
                        if parent_name:
                            parent_notion_id = self._registry.get_tag_notion_id(
                                parent_name
                            )

                props = icor_element_to_notion_tag(element, parent_notion_id)
                if self._dry_run:
                    self._result.dry_run_actions.append(f"Would push tag: {element['name']}")
                    self._result.tags_synced += 1
                    continue
                page = await self._client.create_page(
                    parent={"data_source_id": tags_db_id},
                    properties=props,
                )
                notion_page_id = page["id"]

                await db_ops.update_icor_notion_page_id(
                    element["id"], notion_page_id, db_path=self._db_path
                )

                # Determine dimension name for key_elements
                dimension_name = None
                if element["level"] == "key_element" and parent_id:
                    parent_row = parent_lookup.get(parent_id)
                    if parent_row:
                        dimension_name = parent_row.get("name")

                self._registry.set_tag(
                    element["name"],
                    notion_page_id,
                    element["level"],
                    dimension=dimension_name,
                )
                self._result.tags_synced += 1

            except Exception as e:
                msg = f"Tag sync failed for '{element.get('name', '?')}': {e}"
                logger.warning(msg)
                self._result.warnings.append(msg)

        await db_ops.update_sync_state(
            "tags",
            self._now,
            self._result.tags_synced,
            "bidirectional",
            db_path=self._db_path,
        )

    # ------------------------------------------------------------------
    # Step 2: Push action items -> Notion Tasks
    # ------------------------------------------------------------------

    async def _push_action_items(self):
        actions = await db_ops.get_unpushed_actions(db_path=self._db_path)
        if not actions:
            return

        tasks_db_id = _strip_collection(self._collections["tasks"])

        for action in actions:
            try:
                # Mark push attempt before calling Notion to prevent duplicates on crash
                await db_ops.execute(
                    "UPDATE action_items SET push_attempted_at = datetime('now') WHERE id = ?",
                    (action["id"],),
                    db_path=self._db_path,
                )
                if self._dry_run:
                    self._result.dry_run_actions.append(f"Would push action: {action.get('description', '')[:50]}")
                    self._result.tasks_pushed += 1
                    # Reset push_attempted_at since we didn't actually push
                    await db_ops.execute(
                        "UPDATE action_items SET push_attempted_at = NULL WHERE id = ?",
                        (action["id"],),
                        db_path=self._db_path,
                    )
                    continue
                props = action_to_notion_task(action, self._registry.data)
                page = await self._client.create_page(
                    parent={"data_source_id": tasks_db_id},
                    properties=props,
                )
                await db_ops.update_action_external(
                    action["id"], page["id"], db_path=self._db_path
                )
                await db_ops.log_sync_operation(
                    "push_task",
                    str(action["id"]),
                    "notion_tasks",
                    "success",
                    action.get("description", "")[:100],
                    db_path=self._db_path,
                )
                self._result.tasks_pushed += 1

            except Exception as e:
                msg = f"Push task failed for action {action.get('id', '?')}: {e}"
                logger.warning(msg)
                self._result.warnings.append(msg)
                # Reset push_attempted_at so the item retries on next sync
                try:
                    await db_ops.execute(
                        "UPDATE action_items SET push_attempted_at = NULL WHERE id = ?",
                        (action["id"],),
                        db_path=self._db_path,
                    )
                except Exception:
                    logger.warning("Could not reset push_attempted_at for action %s", action.get("id"))

        await db_ops.update_sync_state(
            "tasks",
            self._now,
            self._result.tasks_pushed,
            "push",
            db_path=self._db_path,
        )

    # ------------------------------------------------------------------
    # Step 3: Pull task status <- Notion Tasks
    # ------------------------------------------------------------------

    async def _pull_task_status(self):
        pushed = await db_ops.get_pushed_actions(db_path=self._db_path)
        if not pushed:
            return

        synced_count = 0
        for action in pushed:
            try:
                page = await self._client.get_page(action["external_id"])
                remote = notion_task_to_action(page)

                if remote["status"] != action["status"]:
                    await db_ops.update_action_status_from_notion(
                        action["id"], remote["status"], db_path=self._db_path
                    )
                    synced_count += 1

            except Exception as e:
                msg = f"Pull task status failed for action {action.get('id', '?')}: {e}"
                logger.warning(msg)
                self._result.warnings.append(msg)

        self._result.tasks_status_synced = synced_count
        await db_ops.update_sync_state(
            "tasks_pull",
            self._now,
            synced_count,
            "pull",
            db_path=self._db_path,
        )

    # ------------------------------------------------------------------
    # Step 4: Pull projects <- Notion Projects DB
    # ------------------------------------------------------------------

    async def _pull_projects(self):
        filter_obj = {
            "and": [
                {"property": "Status", "status": {"does_not_equal": "Done"}},
                {"property": "Archived", "checkbox": {"equals": False}},
            ]
        }
        pages = await self._client.query_database(
            self._collections["projects"], filter=filter_obj
        )

        for page in pages:
            try:
                project = notion_project_to_local(page)
                # Resolve tag name from tag relation IDs
                tag_name = self._resolve_tag_name(project.get("tag_ids", []))
                # Resolve goal name from goal relation IDs
                goal_name = self._resolve_goal_name(project.get("goal_ids", []))
                self._registry.set_project(
                    project["name"],
                    project["notion_id"],
                    tag=tag_name,
                    goal=goal_name,
                    status=project.get("status"),
                )
                self._result.projects_pulled += 1

            except Exception as e:
                msg = f"Pull project failed for page {page.get('id', '?')}: {e}"
                logger.warning(msg)
                self._result.warnings.append(msg)

        await db_ops.update_sync_state(
            "projects",
            self._now,
            self._result.projects_pulled,
            "pull",
            db_path=self._db_path,
        )

    # ------------------------------------------------------------------
    # Step 5: Pull goals <- Notion Goals DB
    # ------------------------------------------------------------------

    async def _pull_goals(self):
        filter_obj = {
            "and": [
                {"property": "Status", "status": {"does_not_equal": "Achieved"}},
                {"property": "Archived", "checkbox": {"equals": False}},
            ]
        }
        pages = await self._client.query_database(
            self._collections["goals"], filter=filter_obj
        )

        for page in pages:
            try:
                goal = notion_goal_to_local(page)
                tag_name = self._resolve_tag_name(goal.get("tag_ids", []))
                self._registry.set_goal(
                    goal["name"],
                    goal["notion_id"],
                    tag=tag_name,
                    status=goal.get("status"),
                )
                self._result.goals_pulled += 1

            except Exception as e:
                msg = f"Pull goal failed for page {page.get('id', '?')}: {e}"
                logger.warning(msg)
                self._result.warnings.append(msg)

        await db_ops.update_sync_state(
            "goals",
            self._now,
            self._result.goals_pulled,
            "pull",
            db_path=self._db_path,
        )

    # ------------------------------------------------------------------
    # Step 6: Push journal entries -> Notion Notes DB
    # ------------------------------------------------------------------

    async def _push_journal_entries(self):
        entries = await db_ops.get_unsynced_journal_entries(db_path=self._db_path)
        if not entries:
            return

        notes_db_id = _strip_collection(self._collections["notes"])

        for entry in entries:
            try:
                # Mark push attempt before calling Notion to prevent duplicates on crash
                await db_ops.execute(
                    "UPDATE journal_entries SET push_attempted_at = datetime('now') WHERE date = ?",
                    (entry["date"],),
                    db_path=self._db_path,
                )
                if self._dry_run:
                    self._result.dry_run_actions.append(f"Would push journal: {entry['date']}")
                    self._result.notes_pushed += 1
                    # Reset push_attempted_at since we didn't actually push
                    await db_ops.execute(
                        "UPDATE journal_entries SET push_attempted_at = NULL WHERE date = ?",
                        (entry["date"],),
                        db_path=self._db_path,
                    )
                    continue
                props = journal_to_notion_note(entry, self._registry.data)
                await self._client.create_page(
                    parent={"data_source_id": notes_db_id},
                    properties=props,
                )
                await db_ops.log_sync_operation(
                    "push_journal",
                    entry.get("date", "unknown"),
                    "notion_notes",
                    "success",
                    entry.get("summary", "")[:100],
                    db_path=self._db_path,
                )
                self._result.notes_pushed += 1

            except Exception as e:
                msg = f"Push journal failed for date {entry.get('date', '?')}: {e}"
                logger.warning(msg)
                self._result.warnings.append(msg)
                # Reset push_attempted_at so the entry retries on next sync
                try:
                    await db_ops.execute(
                        "UPDATE journal_entries SET push_attempted_at = NULL WHERE date = ?",
                        (entry["date"],),
                        db_path=self._db_path,
                    )
                except Exception:
                    logger.warning("Could not reset push_attempted_at for journal %s", entry.get("date"))

        if self._result.notes_pushed > 0:
            await db_ops.update_sync_state(
                "notes",
                self._now,
                self._result.notes_pushed,
                "push",
                db_path=self._db_path,
            )

    # ------------------------------------------------------------------
    # Step 7: Push concepts -> Notion Notes DB
    # ------------------------------------------------------------------

    async def _push_concepts(self):
        concepts = await db_ops.get_unsynced_concepts(db_path=self._db_path)
        if not concepts:
            return

        notes_db_id = _strip_collection(self._collections["notes"])

        for concept in concepts:
            try:
                if self._dry_run:
                    self._result.dry_run_actions.append(f"Would push concept: {concept.get('name', '')}")
                    self._result.concepts_pushed += 1
                    continue
                props = concept_to_notion_note(concept, self._registry.data)
                page = await self._client.create_page(
                    parent={"data_source_id": notes_db_id},
                    properties=props,
                )
                await db_ops.update_concept_notion_id(
                    concept["id"], page["id"], db_path=self._db_path
                )
                await db_ops.log_sync_operation(
                    "push_concept",
                    concept.get("name", "unknown"),
                    "notion_notes",
                    "success",
                    f"Status: {concept.get('status', '')}",
                    db_path=self._db_path,
                )
                self._result.concepts_pushed += 1

            except Exception as e:
                msg = f"Push concept failed for '{concept.get('name', '?')}': {e}"
                logger.warning(msg)
                self._result.warnings.append(msg)

        await db_ops.update_sync_state(
            "concepts",
            self._now,
            self._result.concepts_pushed,
            "push",
            db_path=self._db_path,
        )

    # ------------------------------------------------------------------
    # Step 8: Sync people (pull-primary)
    # ------------------------------------------------------------------

    async def _sync_people(self):
        state = await db_ops.get_sync_state("people", db_path=self._db_path)
        last_synced = state["last_synced_at"] if state else None

        # Build filter: only recently edited entries
        filter_obj: dict | None = None
        if last_synced:
            filter_obj = {
                "timestamp": "last_edited_time",
                "last_edited_time": {"after": last_synced},
            }

        pages = await self._client.query_database(
            self._collections["people"], filter=filter_obj
        )

        for page in pages:
            try:
                person = notion_person_to_local(page)
                # Resolve tag names from tag relation IDs
                tag_names = self._resolve_tag_names(person.get("tag_ids", []))
                self._registry.set_person(
                    person["name"],
                    person["notion_id"],
                    relationship=person.get("relationship"),
                    email=person.get("email"),
                    phone=person.get("phone"),
                    company=person.get("company"),
                    birthday=person.get("birthday"),
                    last_checkin=person.get("last_checkin"),
                    tags=tag_names if tag_names else None,
                )
                self._result.people_synced += 1
            except Exception as e:
                msg = f"People sync failed for page {page.get('id', '?')}: {e}"
                logger.warning(msg)
                self._result.warnings.append(msg)

        await db_ops.update_sync_state(
            "people",
            self._now,
            self._result.people_synced,
            "pull",
            db_path=self._db_path,
        )

    # ------------------------------------------------------------------
    # Post-sync: update vault files
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """Convert a project/goal name to a safe filename."""
        # Replace characters not allowed in filenames
        sanitized = name.replace("/", "-").replace("\\", "-").replace(":", "-")
        sanitized = sanitized.replace('"', "").replace("'", "").replace("?", "")
        sanitized = sanitized.replace("<", "").replace(">", "").replace("|", "")
        # Convert spaces to hyphens, collapse multiples
        import re
        sanitized = re.sub(r"\s+", "-", sanitized.strip())
        sanitized = re.sub(r"-+", "-", sanitized)
        return sanitized or "Untitled"

    @staticmethod
    def _yaml_safe(val: str) -> str:
        """Quote a YAML value if it contains characters that need escaping."""
        if not val:
            return '""'
        # Quote if value contains YAML-sensitive characters
        needs_quoting = any(c in val for c in (':', '#', '{', '}', '[', ']', ',', '&', '*', '?', '|', '-', '<', '>', '=', '!', '%', '@', '`', '"', "'"))
        if needs_quoting or val.strip() != val:
            # Use double quotes with escaped internal double quotes
            escaped = val.replace('\\', '\\\\').replace('"', '\\"')
            return f'"{escaped}"'
        return val

    def _build_frontmatter(self, meta: dict) -> str:
        """Build YAML frontmatter from a dict of fields."""
        lines = ["---"]
        for key, val in meta.items():
            if isinstance(val, list):
                quoted = [self._yaml_safe(str(v)) for v in val]
                lines.append(f"{key}: [{', '.join(quoted)}]")
            elif isinstance(val, bool):
                lines.append(f"{key}: {'true' if val else 'false'}")
            elif val is not None:
                lines.append(f"{key}: {self._yaml_safe(str(val)) if isinstance(val, str) else val}")
        lines.append("---")
        return "\n".join(lines)

    def _update_file_frontmatter(self, path: Path, new_meta: dict, template_body: str):
        """Write or update a vault file, preserving manual content below frontmatter.

        If file exists, only the frontmatter is replaced; body content is preserved.
        If file does not exist, create it with frontmatter + template_body.
        """
        if path.exists():
            content = path.read_text(encoding="utf-8")
            # Split on frontmatter boundaries
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    # parts[0] is empty, parts[1] is frontmatter, parts[2] is body
                    existing_body = parts[2]
                    new_content = self._build_frontmatter(new_meta) + existing_body
                    path.write_text(new_content, encoding="utf-8")
                    return
            # File exists but no frontmatter — prepend frontmatter
            new_content = self._build_frontmatter(new_meta) + "\n\n" + content
            path.write_text(new_content, encoding="utf-8")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            new_content = self._build_frontmatter(new_meta) + "\n\n" + template_body
            path.write_text(new_content, encoding="utf-8")

    def _render_project_template(self, name: str, info: dict, goals: dict) -> str:
        """Render the body template for a new project vault file."""
        lines = [f"# {name}", ""]

        # Link to Notion
        notion_id = info.get("notion_page_id", "")
        if notion_id:
            lines.append(f"[Open in Notion](https://notion.so/{notion_id.replace('-', '')})")
            lines.append("")

        # Link to goal: prefer direct goal link, fall back to tag-based matching
        tag = info.get("tag", "")
        linked_goals = []
        direct_goal = info.get("goal")
        if direct_goal:
            linked_goals.append(direct_goal)
        else:
            for goal_name, goal_info in goals.items():
                if goal_info.get("tag") == tag and tag:
                    linked_goals.append(goal_name)
        if linked_goals:
            lines.append("## Linked Goals")
            for g in linked_goals:
                filename = self._sanitize_filename(g)
                lines.append(f"- [[{filename}|{g}]]")
            lines.append("")

        if tag:
            tag_filename = self._sanitize_filename(tag)
            lines.append(f"**ICOR Tag:** [[{tag_filename}|{tag}]]")
            lines.append("")

        lines.append("## Notes")
        lines.append("")
        lines.append("<!-- Add your project notes below this line -->")
        lines.append("")
        return "\n".join(lines)

    def _render_goal_template(self, name: str, info: dict, projects: dict) -> str:
        """Render the body template for a new goal vault file."""
        lines = [f"# {name}", ""]

        notion_id = info.get("notion_page_id", "")
        if notion_id:
            lines.append(f"[Open in Notion](https://notion.so/{notion_id.replace('-', '')})")
            lines.append("")

        # Find linked projects: prefer direct goal link, fall back to tag-based
        tag = info.get("tag", "")
        linked_projects = []
        for proj_name, proj_info in projects.items():
            # Direct link: project explicitly references this goal
            if proj_info.get("goal") == name:
                linked_projects.append(proj_name)
            # Tag-based fallback: same ICOR tag
            elif proj_info.get("tag") == tag and tag and proj_name not in linked_projects:
                linked_projects.append(proj_name)
        if linked_projects:
            lines.append("## Linked Projects")
            for p in linked_projects:
                filename = self._sanitize_filename(p)
                lines.append(f"- [[{filename}|{p}]]")
            lines.append("")

        if tag:
            tag_filename = self._sanitize_filename(tag)
            lines.append(f"**ICOR Tag:** [[{tag_filename}|{tag}]]")
            lines.append("")

        lines.append("## Notes")
        lines.append("")
        lines.append("<!-- Add your goal notes below this line -->")
        lines.append("")
        return "\n".join(lines)

    def _render_person_template(self, name: str, info: dict) -> str:
        """Render the body template for a new person vault file."""
        lines = [f"# {name}", ""]

        # Link to Notion
        notion_id = info.get("notion_page_id", "")
        if notion_id:
            lines.append(f"[Open in Notion](https://notion.so/{notion_id.replace('-', '')})")
            lines.append("")

        # Contact details section
        lines.append("## Contact")
        lines.append("")
        email = info.get("email", "")
        phone = info.get("phone", "")
        company = info.get("company", "")
        if email:
            lines.append(f"- **Email:** {email}")
        if phone:
            lines.append(f"- **Phone:** {phone}")
        if company:
            lines.append(f"- **Company:** {company}")
        birthday = info.get("birthday", "")
        if birthday:
            lines.append(f"- **Birthday:** {birthday}")
        if not any([email, phone, company, birthday]):
            lines.append("<!-- Add contact details here -->")
        lines.append("")

        # Tags as wikilinks
        tags = info.get("tags", [])
        if tags:
            lines.append("## Tags")
            lines.append("")
            for t in tags:
                tag_filename = self._sanitize_filename(t)
                lines.append(f"- [[{tag_filename}|{t}]]")
            lines.append("")

        lines.append("## Notes")
        lines.append("")
        lines.append("<!-- Add your notes about this person below this line -->")
        lines.append("")
        return "\n".join(lines)

    async def _update_vault_files(self):
        """Generate vault files from registry data: index + individual entity files.

        Writes:
        1. vault/Identity/Active-Projects.md -- project index table
        2. vault/Projects/{name}.md -- per-project with frontmatter + wikilinks
        3. vault/Goals/{name}.md -- per-goal with frontmatter + wikilinks
        4. vault/People/{name}.md -- per-person with frontmatter
        """
        projects = self._registry.data.get("projects", {})
        goals = self._registry.data.get("goals", {})
        people = self._registry.data.get("people", {})
        now_str = datetime.utcnow().strftime("%Y-%m-%d")
        files_written = 0

        # --- 1. Active-Projects.md index (existing behavior) ---
        if projects:
            lines = [
                "---",
                "type: identity",
                f"last_updated: {now_str}",
                "auto_generated: true",
                "---",
                "",
                "# Active Projects Index",
                "",
                "This file is automatically updated by `/brain:sync-notion` and `/brain:close-day` commands.",
                "",
                "## Projects",
                "",
                "| Project | ICOR Tag | Notion Link |",
                "|---|---|---|",
            ]

            for name, info in sorted(projects.items()):
                tag = info.get("tag", "--")
                notion_id = info.get("notion_page_id", "")
                link = f"[Open](https://notion.so/{notion_id.replace('-', '')})" if notion_id else "--"
                lines.append(f"| {name} | {tag} | {link} |")

            lines.append("")
            lines.append("---")
            lines.append(f"*Last synced: {now_str}*")
            lines.append("")

            path = self._vault_path / "Identity" / "Active-Projects.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(lines), encoding="utf-8")
            logger.info("Updated %s with %d projects", path, len(projects))
            files_written += 1

        # --- 2. Individual project files ---
        projects_dir = self._vault_path / "Projects"
        for name, info in projects.items():
            filename = self._sanitize_filename(name) + ".md"
            filepath = projects_dir / filename

            # Build tags list: ICOR tag + goal name for wikilink indexing
            tags = []
            tag = info.get("tag", "")
            if tag:
                tags.append(tag)
            goal_name = info.get("goal", "")
            if goal_name:
                tags.append(goal_name)

            meta = {
                "type": "project",
                "date": now_str,
                "notion_id": info.get("notion_page_id", ""),
                "status": info.get("status", ""),
                "tags": tags if tags else None,
                "icor_tag": tag,
                "auto_generated": True,
            }
            # Remove None values
            meta = {k: v for k, v in meta.items() if v is not None}

            template = self._render_project_template(name, info, goals)
            self._update_file_frontmatter(filepath, meta, template)
            files_written += 1

        # --- 3. Individual goal files ---
        goals_dir = self._vault_path / "Goals"
        for name, info in goals.items():
            filename = self._sanitize_filename(name) + ".md"
            filepath = goals_dir / filename

            tags = []
            tag = info.get("tag", "")
            if tag:
                tags.append(tag)

            meta = {
                "type": "goal",
                "date": now_str,
                "notion_id": info.get("notion_page_id", ""),
                "status": info.get("status", ""),
                "tags": tags if tags else None,
                "icor_tag": tag,
                "auto_generated": True,
            }
            meta = {k: v for k, v in meta.items() if v is not None}

            template = self._render_goal_template(name, info, projects)
            self._update_file_frontmatter(filepath, meta, template)
            files_written += 1

        # --- 4. Individual people files ---
        people_dir = self._vault_path / "People"
        for name, info in people.items():
            if not name:
                continue
            filename = self._sanitize_filename(name) + ".md"
            filepath = people_dir / filename

            person_tags = info.get("tags", []) or []

            meta = {
                "type": "person",
                "date": now_str,
                "notion_id": info.get("notion_page_id", ""),
                "status": info.get("relationship", ""),
                "tags": person_tags if person_tags else None,
                "auto_generated": True,
            }
            meta = {k: v for k, v in meta.items() if v is not None}

            template = self._render_person_template(name, info)
            self._update_file_frontmatter(filepath, meta, template)
            files_written += 1

        self._result.vault_files_written = files_written
        logger.info(
            "Vault files written: %d (projects: %d, goals: %d, people: %d)",
            files_written, len(projects), len(goals), len(people),
        )

    # ------------------------------------------------------------------
    # Post-sync: log operations
    # ------------------------------------------------------------------

    async def _log_sync_operations(self):
        status = "success" if not self._result.errors else "partial"
        await db_ops.log_sync_operation(
            "full_sync",
            "all",
            "notion",
            status,
            self._result.summary()[:500],
            db_path=self._db_path,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_tag_name(self, tag_ids: list[str]) -> str | None:
        """Reverse-lookup a tag name from Notion page IDs using the registry."""
        if not tag_ids:
            return None
        target_id = tag_ids[0]  # Tags DB relations are limit-1
        # Search dimensions
        for name, info in self._registry.data.get("dimensions", {}).items():
            if info.get("notion_page_id") == target_id:
                return name
        # Search key_elements
        for name, info in self._registry.data.get("key_elements", {}).items():
            if info.get("notion_page_id") == target_id:
                return name
        return None

    def _resolve_tag_names(self, tag_ids: list[str]) -> list[str]:
        """Reverse-lookup multiple tag names from Notion page IDs."""
        names = []
        for tid in tag_ids:
            for name, info in self._registry.data.get("dimensions", {}).items():
                if info.get("notion_page_id") == tid:
                    names.append(name)
                    break
            else:
                for name, info in self._registry.data.get("key_elements", {}).items():
                    if info.get("notion_page_id") == tid:
                        names.append(name)
                        break
        return names

    def _resolve_goal_name(self, goal_ids: list[str]) -> str | None:
        """Reverse-lookup a goal name from Notion page IDs using the registry."""
        if not goal_ids:
            return None
        target_id = goal_ids[0]  # Goal relation is limit-1
        for name, info in self._registry.data.get("goals", {}).items():
            if info.get("notion_page_id") == target_id:
                return name
        return None

    # ------------------------------------------------------------------
    # Hybrid AI helpers
    # ------------------------------------------------------------------

    async def _ai_classify_tag(self, name: str, candidates: list[str]) -> str:
        """Ask Claude to classify which ICOR tag best matches a name."""
        if not self._ai_client:
            return candidates[0] if candidates else name

        self._result.ai_calls += 1
        response = self._ai_client.messages.create(
            model=self._ai_model,
            max_tokens=100,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Which ICOR tag best matches '{name}'? "
                        f"Options: {', '.join(candidates)}. "
                        "Reply with just the tag name."
                    ),
                }
            ],
        )
        return response.content[0].text.strip()

    async def _ai_resolve_conflict(
        self, local: dict, remote: dict, entity_type: str
    ) -> str:
        """Ask Claude to decide merge strategy for bidirectional conflicts."""
        if not self._ai_client:
            # Fallback: last-write-wins
            if remote.get("last_edited", "") > local.get("updated_at", ""):
                return "remote"
            return "local"

        self._result.ai_calls += 1
        response = self._ai_client.messages.create(
            model=self._ai_model,
            max_tokens=50,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Conflict in {entity_type}.\n"
                        f"Local: {json.dumps(local, default=str)[:500]}\n"
                        f"Remote: {json.dumps(remote, default=str)[:500]}\n"
                        "Which version should win? Reply 'local' or 'remote'."
                    ),
                }
            ],
        )
        answer = response.content[0].text.strip().lower()
        return "remote" if "remote" in answer else "local"

    async def _ai_infer_project_goal(
        self, project_name: str, goals: list[dict]
    ) -> str | None:
        """Ask Claude to infer which goal a project belongs to."""
        if not self._ai_client or not goals:
            return None

        self._result.ai_calls += 1
        goal_names = [g.get("name", "") for g in goals]
        response = self._ai_client.messages.create(
            model=self._ai_model,
            max_tokens=100,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Project: '{project_name}'\n"
                        f"Available goals: {', '.join(goal_names)}\n"
                        "Which goal does this project most likely belong to? "
                        "Reply with just the goal name, or 'none' if no match."
                    ),
                }
            ],
        )
        answer = response.content[0].text.strip()
        if answer.lower() != "none" and answer in goal_names:
            return answer
        return None
