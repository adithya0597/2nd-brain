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
    ai_calls: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = ["Notion Sync Complete:"]
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
        if self.ai_calls:
            lines.append(f"  AI decisions: {self.ai_calls}")
        if self.errors:
            lines.append(f"  Errors: {len(self.errors)}")
        if self.warnings:
            lines.append(f"  Warnings: {len(self.warnings)}")
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

    def set_project(self, name: str, notion_page_id: str, tag: str = None):
        entry: dict = {"notion_page_id": notion_page_id}
        if tag:
            entry["tag"] = tag
        self._data.setdefault("projects", {})[name] = entry

    def set_goal(self, name: str, notion_page_id: str, tag: str = None):
        entry: dict = {"notion_page_id": notion_page_id}
        if tag:
            entry["tag"] = tag
        self._data.setdefault("goals", {})[name] = entry


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

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    async def run_full_sync(self) -> SyncResult:
        """Execute the complete sync pipeline."""
        self._result = SyncResult()
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
                self._registry.set_project(
                    project["name"], project["notion_id"], tag=tag_name
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
                    goal["name"], goal["notion_id"], tag=tag_name
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
        state = await db_ops.get_sync_state("notes", db_path=self._db_path)
        since = state["last_synced_at"] if state else None
        entries = await db_ops.get_unsynced_journal_entries(
            since=since, db_path=self._db_path
        )
        if not entries:
            return

        notes_db_id = _strip_collection(self._collections["notes"])

        for entry in entries:
            try:
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
                notion_person_to_local(page)
                # No local people table yet -- just count for reporting
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

    async def _update_vault_files(self):
        """Regenerate vault/Identity/Active-Projects.md from registry data."""
        projects = self._registry.data.get("projects", {})
        if not projects:
            return

        now_str = datetime.utcnow().strftime("%Y-%m-%d")
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
