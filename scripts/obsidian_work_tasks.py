#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).resolve()
SKILL_DIR = SCRIPT_PATH.parent.parent
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from obsidian_work import core

SKILL_CONFIG_PATH = SKILL_DIR / "config.json"
PROJECT_CONFIG_RELATIVE_PATHS = [
    Path(".codex") / "obsidian-work-tasks.json",
    Path(".agents") / "obsidian-work-tasks.json",
    Path(".claude") / "obsidian-work-tasks.json",
]
DEFAULT_CONFIG = {
    "tasks_dir": "Work Tasks",
    "index_file": "Index.md",
    "default_tags": ["work-task"],
    "redaction": {
        "enabled": True,
        "patterns": ["API_KEY", "SECRET", "TOKEN", "PASSWORD"],
    },
}
VALID_STATUSES = ["todo", "doing", "blocked", "done"]
STATUS_ORDER = ["doing", "blocked", "todo", "done"]
ARCHIVE_DIRNAME = "_archive"
OMITTED_FRONTMATTER_KEYS = {"title", "slug", "priority", "planned_for", "due"}


class WorkTaskError(Exception):
    pass


@dataclass
class Config:
    vault_path: Path
    tasks_dir: str
    index_file: str
    default_tags: list[str]
    redaction_enabled: bool
    redaction_patterns: list[str]


@dataclass
class Task:
    path: Path
    relative_path: str
    title: str
    slug: str
    status: str
    priority: str
    project: str
    jira_id: str
    planned_for: str
    due: str
    tags: list[str]
    created: str | None
    updated: str | None
    archived: bool
    body: str
    frontmatter: dict[str, Any]


def load_json(path: Path) -> dict[str, Any]:
    return core.load_json(path, WorkTaskError)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    return core.deep_merge(base, override)


def discover_project_root(start: Path | None = None) -> Path:
    return core.discover_project_root(PROJECT_CONFIG_RELATIVE_PATHS, start)


def project_config_paths(project_root: Path) -> list[Path]:
    return core.project_config_paths(project_root, PROJECT_CONFIG_RELATIVE_PATHS)


def config_source_paths(project_root: Path) -> list[Path]:
    return core.config_source_paths(SKILL_CONFIG_PATH, project_root, PROJECT_CONFIG_RELATIVE_PATHS)


def resolve_config(project_root: Path) -> Config:
    merged: dict[str, Any] = deep_merge(DEFAULT_CONFIG, load_json(SKILL_CONFIG_PATH))
    for config_path in reversed(project_config_paths(project_root)):
        merged = deep_merge(merged, load_json(config_path))

    env_vault = os.getenv("OBSIDIAN_VAULT_PATH")
    if env_vault:
        merged["vault_path"] = env_vault

    vault_path = merged.get("vault_path")
    if not vault_path:
        raise WorkTaskError(
            "Missing vault_path. Set OBSIDIAN_VAULT_PATH, add it to "
            ".codex/obsidian-work-tasks.json, or add it to the skill config."
        )

    redaction = merged.get("redaction") or {}
    return Config(
        vault_path=Path(vault_path).expanduser().resolve(),
        tasks_dir=str(merged.get("tasks_dir") or DEFAULT_CONFIG["tasks_dir"]).strip("/") or DEFAULT_CONFIG["tasks_dir"],
        index_file=str(merged.get("index_file") or DEFAULT_CONFIG["index_file"]).strip("/") or DEFAULT_CONFIG["index_file"],
        default_tags=list(merged.get("default_tags") or DEFAULT_CONFIG["default_tags"]),
        redaction_enabled=bool(redaction.get("enabled", True)),
        redaction_patterns=list(redaction.get("patterns") or DEFAULT_CONFIG["redaction"]["patterns"]),
    )


def now_iso() -> str:
    return core.now_iso()


def slugify(value: str) -> str:
    return core.slugify(value, "Task slug", WorkTaskError)


def detect_project_name(project_root: Path) -> str:
    return core.detect_project_name(project_root)


def ensure_within(root: Path, target: Path) -> Path:
    return core.ensure_within(root, target, WorkTaskError)


def tasks_root_dir(config: Config) -> Path:
    return ensure_within(config.vault_path, config.vault_path / config.tasks_dir)


def archive_dir(config: Config) -> Path:
    return ensure_within(config.vault_path, tasks_root_dir(config) / ARCHIVE_DIRNAME)


def index_path(config: Config) -> Path:
    return ensure_within(config.vault_path, tasks_root_dir(config) / config.index_file)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    return core.parse_frontmatter(text)


def format_frontmatter(data: dict[str, Any]) -> str:
    return core.format_frontmatter(data)


def normalize_list(values: list[str] | str | None) -> list[str]:
    return core.normalize_list(values)


def normalize_tags(config: Config, project_name: str, extra_tags: list[str] | None) -> list[str]:
    return core.normalize_tags(config.default_tags, project_name, extra_tags)


def redact_secrets(text: str, config: Config) -> str:
    return core.redact_secrets(text, config.redaction_enabled, config.redaction_patterns)


def atomic_write(path: Path, content: str) -> None:
    core.atomic_write(path, content)


def normalize_status(status: str | None) -> str:
    normalized = (status or "todo").strip().lower()
    if normalized not in VALID_STATUSES:
        raise WorkTaskError(f"Unsupported status {status!r}. Expected one of: {', '.join(VALID_STATUSES)}")
    return normalized


def extract_jira_id(value: str) -> str:
    match = re.search(r"\b[A-Z][A-Z0-9]+-\d+\b", value.upper())
    return match.group(0) if match else ""


def resolve_doc_path(config: Config, path_arg: str) -> Path:
    raw_path = Path(path_arg).expanduser()
    if raw_path.is_absolute():
        return ensure_within(config.vault_path, raw_path)
    return ensure_within(config.vault_path, config.vault_path / raw_path)


def frontmatter_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.casefold() in {"true", "yes", "1"}
    return False


def load_task(path: Path, vault_root: Path) -> Task:
    safe_path = ensure_within(vault_root, path)
    text = safe_path.read_text()
    frontmatter, body = parse_frontmatter(text)
    relative_path = str(safe_path.relative_to(vault_root))
    title = str(frontmatter.get("title") or extract_title_from_body(body) or safe_path.stem.replace("-", " ").title())
    slug = str(frontmatter.get("slug") or safe_path.stem)
    status = normalize_status(str(frontmatter.get("status") or "todo"))
    return Task(
        path=safe_path,
        relative_path=relative_path,
        title=title,
        slug=slug,
        status=status,
        priority=str(frontmatter.get("priority") or ""),
        project=str(frontmatter.get("project") or ""),
        jira_id=str(frontmatter.get("jira_id") or extract_jira_id(f"{slug} {title}")),
        planned_for=str(frontmatter.get("planned_for") or ""),
        due=str(frontmatter.get("due") or ""),
        tags=normalize_list(frontmatter.get("tags")),
        created=frontmatter.get("created"),
        updated=frontmatter.get("updated"),
        archived=frontmatter_bool(frontmatter.get("archived")) or ARCHIVE_DIRNAME in safe_path.relative_to(vault_root).parts,
        body=body,
        frontmatter=frontmatter,
    )


def iter_task_paths(config: Config, include_archived: bool = False) -> list[Path]:
    root = tasks_root_dir(config)
    if not root.exists():
        return []
    paths = [
        path
        for path in root.glob("*.md")
        if path.resolve() != index_path(config).resolve()
    ]
    if include_archived and archive_dir(config).exists():
        paths.extend(sorted(archive_dir(config).glob("*.md")))
    return sorted(paths)


def list_tasks(config: Config, include_archived: bool = False) -> list[Task]:
    tasks = [load_task(path, config.vault_path) for path in iter_task_paths(config, include_archived)]
    default_tags = set(config.default_tags)
    if not default_tags:
        return tasks
    return [task for task in tasks if default_tags.intersection(set(task.tags))]


def task_payload(task: Task) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "path": task.relative_path,
        "title": task.title,
        "slug": task.slug,
        "status": task.status,
        "priority": task.priority,
        "project": task.project,
        "jira_id": task.jira_id,
        "planned_for": task.planned_for,
        "due": task.due,
        "tags": task.tags,
        "updated": task.updated,
    }
    if task.archived:
        payload["archived"] = True
        payload["archived_at"] = task.frontmatter.get("archived_at")
        payload["archived_reason"] = task.frontmatter.get("archived_reason")
    return payload


def compact_frontmatter(frontmatter: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in frontmatter.items() if key not in OMITTED_FRONTMATTER_KEYS}


def tokenize(value: str) -> list[str]:
    return [term.casefold() for term in re.findall(r"[A-Za-z0-9_-]+", value)]


def scan_tasks(config: Config, query: str | None, status: str | None, limit: int | None, include_archived: bool = False) -> list[dict[str, Any]]:
    query_terms = tokenize(query or "")
    status_filter = normalize_status(status) if status else None
    matches: list[Task] = []
    for task in list_tasks(config, include_archived):
        if status_filter and task.status != status_filter:
            continue
        haystack = " ".join(
            [
                task.title,
                task.slug,
                task.status,
                task.priority,
                task.project,
                task.jira_id,
                task.relative_path,
                *task.tags,
                task.body,
            ]
        ).casefold()
        if query_terms and not all(term in haystack for term in query_terms):
            continue
        matches.append(task)

    matches.sort(key=lambda task: (STATUS_ORDER.index(task.status), task.due or "9999-99-99", task.title.casefold()))
    payloads = [task_payload(task) for task in matches]
    return payloads[:limit] if limit is not None else payloads


def remove_duplicate_title_heading(body: str, title: str) -> str:
    lines = body.strip().splitlines()
    if not lines:
        return ""
    match = re.match(r"^#\s+(.+?)\s*$", lines[0])
    if not match or match.group(1).strip().casefold() != title.strip().casefold():
        return body.strip()
    remaining = lines[1:]
    while remaining and not remaining[0].strip():
        remaining = remaining[1:]
    return "\n".join(remaining).strip()


def extract_title_from_body(body: str) -> str:
    for line in body.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1).strip()
    return ""


def render_task(frontmatter: dict[str, Any], body: str, title: str | None = None) -> str:
    heading = title or extract_title_from_body(body)
    if not heading:
        raise WorkTaskError("Task title is required in the body heading or create command.")
    frontmatter = compact_frontmatter(frontmatter)
    title = heading
    cleaned_body = remove_duplicate_title_heading(body, title)
    return f"{format_frontmatter(frontmatter)}\n\n# {title}\n\n{cleaned_body.strip()}\n"


def render_default_body(body: str) -> str:
    if body.strip():
        return body
    return """## Checklist
- [ ] Define the next concrete step.

## Notes

## Links

## Log
"""


def read_optional_content(content: str | None, content_file: str | None) -> str | None:
    if content and content_file:
        raise WorkTaskError("Provide at most one of --content or --content-file.")
    if content_file:
        return Path(content_file).expanduser().read_text()
    return content


def create_task(
    config: Config,
    project_name: str,
    title: str,
    slug: str | None,
    status: str | None,
    priority: str | None,
    jira_id: str | None,
    planned_for: str | None,
    due: str | None,
    body: str | None,
    extra_tags: list[str] | None,
) -> dict[str, Any]:
    display_slug = (slug or title).strip()
    file_slug = slugify(display_slug)
    path = ensure_within(config.vault_path, tasks_root_dir(config) / f"{file_slug}.md")
    if path.exists():
        raise WorkTaskError(f"Work task already exists: {path.relative_to(config.vault_path)}")

    timestamp = now_iso()
    rendered_body = render_default_body(redact_secrets(body or "", config))
    frontmatter = {
        "status": normalize_status(status),
        "project": project_name,
        "jira_id": (jira_id or extract_jira_id(f"{display_slug} {title}")).strip(),
        "created": timestamp,
        "updated": timestamp,
        "tags": normalize_tags(config, project_name, extra_tags),
    }
    atomic_write(path, render_task(frontmatter, rendered_body, title.strip()))
    regenerate_index(config)
    return {
        "path": str(path.relative_to(config.vault_path)),
        "title": title.strip(),
        "slug": display_slug,
        "status": frontmatter["status"],
        "created": timestamp,
        "updated": timestamp,
        "index": str(index_path(config).relative_to(config.vault_path)),
    }


def append_body(existing_body: str, new_content: str) -> str:
    return core.append_body(existing_body, new_content)


def replace_section(existing_body: str, section: str, new_content: str) -> str:
    return core.replace_section(existing_body, section, new_content, WorkTaskError)


def merge_tags(existing_tags: list[str], new_tags: list[str]) -> list[str]:
    tags = list(existing_tags)
    for tag in new_tags:
        if tag not in tags:
            tags.append(tag)
    return tags


def update_task(
    config: Config,
    project_name: str,
    path_arg: str,
    mode: str,
    new_content: str | None,
    section: str | None,
    status: str | None,
    priority: str | None,
    planned_for: str | None,
    due: str | None,
    extra_tags: list[str] | None,
) -> dict[str, Any]:
    path = resolve_doc_path(config, path_arg)
    if not path.exists():
        raise WorkTaskError(f"Work task does not exist: {path_arg}")

    text = path.read_text()
    frontmatter, body = parse_frontmatter(text)
    if not frontmatter:
        raise WorkTaskError(f"Work task is missing expected frontmatter: {path}")

    updated_body = body
    if new_content is not None:
        redacted_content = redact_secrets(new_content, config)
        if mode == "append":
            updated_body = append_body(body, redacted_content)
        elif mode == "replace":
            if not section:
                raise WorkTaskError("--section is required when mode is replace.")
            updated_body = replace_section(body, section, redacted_content)
        elif mode == "rewrite":
            updated_body = redacted_content.strip()
        else:
            raise WorkTaskError(f"Unknown update mode: {mode}")
    elif mode in {"replace", "rewrite"}:
        raise WorkTaskError("--content or --content-file is required for replace and rewrite modes.")

    if status is not None:
        frontmatter["status"] = normalize_status(status)
    else:
        frontmatter["status"] = normalize_status(str(frontmatter.get("status") or "todo"))
    if priority is not None:
        frontmatter["priority"] = priority.strip()
    if planned_for is not None:
        frontmatter["planned_for"] = planned_for.strip()
    if due is not None:
        frontmatter["due"] = due.strip()
    if not frontmatter.get("project"):
        frontmatter["project"] = project_name
    if not frontmatter.get("jira_id"):
        frontmatter["jira_id"] = extract_jira_id(f"{frontmatter.get('slug', '')} {frontmatter.get('title', '')} {path.stem}")
    frontmatter["tags"] = merge_tags(normalize_list(frontmatter.get("tags")), normalize_tags(config, project_name, extra_tags))
    frontmatter["updated"] = now_iso()
    for key in OMITTED_FRONTMATTER_KEYS:
        frontmatter.pop(key, None)

    atomic_write(path, render_task(frontmatter, updated_body, extract_title_from_body(body) or path.stem.replace("-", " ").title()))
    regenerate_index(config)
    return {
        "path": str(path.relative_to(config.vault_path)),
        "title": frontmatter.get("title"),
        "status": frontmatter.get("status"),
        "updated": frontmatter.get("updated"),
        "mode": mode,
        "section": section,
        "index": str(index_path(config).relative_to(config.vault_path)),
    }


def read_task(config: Config, path_arg: str) -> str:
    path = resolve_doc_path(config, path_arg)
    if not path.exists():
        raise WorkTaskError(f"Work task does not exist: {path_arg}")
    return path.read_text()


def archive_destination(config: Config, path: Path) -> Path:
    destination = ensure_within(config.vault_path, archive_dir(config) / path.name)
    if not destination.exists():
        return destination
    suffix = datetime.now().astimezone().strftime("%Y%m%d%H%M%S")
    return ensure_within(config.vault_path, archive_dir(config) / f"{path.stem}-{suffix}{path.suffix}")


def archive_task(config: Config, path_arg: str, reason: str | None) -> dict[str, Any]:
    path = resolve_doc_path(config, path_arg)
    if not path.exists():
        raise WorkTaskError(f"Work task does not exist: {path_arg}")
    if ARCHIVE_DIRNAME in path.relative_to(config.vault_path).parts:
        raise WorkTaskError(f"Work task is already archived: {path_arg}")

    text = path.read_text()
    frontmatter, body = parse_frontmatter(text)
    if not frontmatter:
        raise WorkTaskError(f"Work task is missing expected frontmatter: {path}")

    timestamp = now_iso()
    frontmatter["archived"] = True
    frontmatter["archived_at"] = timestamp
    frontmatter["archived_reason"] = (reason or "").strip()
    frontmatter["original_path"] = str(path.relative_to(config.vault_path))
    frontmatter["updated"] = timestamp
    for key in OMITTED_FRONTMATTER_KEYS:
        frontmatter.pop(key, None)

    destination = archive_destination(config, path)
    atomic_write(destination, render_task(frontmatter, body, extract_title_from_body(body) or path.stem.replace("-", " ").title()))
    path.unlink()
    regenerate_index(config)
    return {
        "path": str(destination.relative_to(config.vault_path)),
        "original_path": frontmatter["original_path"],
        "archived_at": timestamp,
        "reason": frontmatter["archived_reason"],
        "index": str(index_path(config).relative_to(config.vault_path)),
    }


def compact_task_metadata(config: Config, include_archived: bool = False) -> dict[str, Any]:
    compacted: list[str] = []
    for task in list_tasks(config, include_archived):
        removed_keys = [key for key in OMITTED_FRONTMATTER_KEYS if key in task.frontmatter]
        if not removed_keys:
            continue
        frontmatter = compact_frontmatter(task.frontmatter)
        atomic_write(task.path, render_task(frontmatter, task.body, task.title))
        compacted.append(task.relative_path)

    regenerate_index(config)
    return {
        "compacted": compacted,
        "count": len(compacted),
        "index": str(index_path(config).relative_to(config.vault_path)),
    }


def escape_table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def format_date(value: str | None) -> str:
    if not value:
        return ""
    return str(value).split("T", 1)[0]


def task_sort_key(task: Task) -> tuple[str, str, str]:
    return (task.status, task.project, task.title.casefold())


def regenerate_index(config: Config) -> dict[str, Any]:
    active_tasks = [task for task in list_tasks(config) if not task.archived]
    archived_count = len(list_tasks(config, include_archived=True)) - len(active_tasks)
    lines = ["# Work Tasks Index", ""]
    for status in STATUS_ORDER:
        status_tasks = sorted([task for task in active_tasks if task.status == status], key=task_sort_key)
        lines.extend(
            [
                f"## {status.title()}",
                "",
                "| Task | Status | Project | Jira | Updated |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        if status_tasks:
            for task in status_tasks:
                link = f"[[{task.path.stem}|{task.title}]]"
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            escape_table_cell(link),
                            escape_table_cell(task.status),
                            escape_table_cell(task.project),
                            escape_table_cell(task.jira_id),
                            escape_table_cell(format_date(task.updated)),
                        ]
                    )
                    + " |"
                )
        else:
            lines.append("|  |  |  |  |  |")
        lines.append("")
    lines.extend(["## Archive", "", f"Archived tasks: {archived_count}", ""])
    atomic_write(index_path(config), "\n".join(lines))
    return {
        "path": str(index_path(config).relative_to(config.vault_path)),
        "tasks": len(active_tasks),
        "archived_tasks": archived_count,
    }


def can_write_directory(path: Path) -> bool:
    candidate = path if path.exists() else path.parent
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate.exists() and os.access(candidate, os.W_OK)


def doctor_payload(project_root: Path, project_name: str, config: Config) -> dict[str, Any]:
    root = tasks_root_dir(config)
    idx_path = index_path(config)
    return {
        "project_root": str(project_root),
        "project": project_name,
        "config_sources": [str(path) for path in config_source_paths(project_root) if path.exists()],
        "vault_path": str(config.vault_path),
        "tasks_dir": config.tasks_dir,
        "tasks_path": str(root),
        "tasks_exists": root.exists(),
        "index_file": config.index_file,
        "index_path": str(idx_path),
        "index_exists": idx_path.exists(),
        "writes_possible": can_write_directory(root),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage lightweight work task notes in Obsidian.")
    parser.add_argument("--project", help="Override the auto-detected source project name.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="List work tasks.")
    scan_parser.add_argument("--query", help="Optional keywords to filter by task metadata or body.")
    scan_parser.add_argument("--status", choices=VALID_STATUSES, help="Filter by task status.")
    scan_parser.add_argument("--limit", type=int, help="Maximum number of tasks to return.")
    scan_parser.add_argument("--include-archived", action="store_true", help="Include archived tasks.")

    read_parser = subparsers.add_parser("read", help="Read a work task.")
    read_parser.add_argument("--path", required=True, help="Task path relative to the vault root.")

    create_parser = subparsers.add_parser("create", help="Create a new work task.")
    create_parser.add_argument("--title", required=True, help="Task title.")
    create_parser.add_argument("--slug", help="Readable slug or Jira ID. Filename is normalized from this value.")
    create_parser.add_argument("--status", choices=VALID_STATUSES, help="Initial task status.")
    create_parser.add_argument("--priority", help="Task priority.")
    create_parser.add_argument("--jira-id", help="Jira issue ID.")
    create_parser.add_argument("--planned-for", help="Planned work date.")
    create_parser.add_argument("--due", help="Due date.")
    create_parser.add_argument("--content", help="Inline markdown body.")
    create_parser.add_argument("--content-file", help="Path to a markdown file containing the body content.")
    create_parser.add_argument("--tag", action="append", dest="tags", help="Additional tag to add.")

    update_parser = subparsers.add_parser("update", help="Update task content or metadata.")
    update_parser.add_argument("--path", required=True, help="Task path relative to the vault root.")
    update_parser.add_argument("--mode", default="append", choices=["append", "replace", "rewrite"], help="Content update mode.")
    update_parser.add_argument("--section", help="Section heading to replace when using replace mode.")
    update_parser.add_argument("--status", choices=VALID_STATUSES, help="Updated task status.")
    update_parser.add_argument("--priority", help="Updated priority.")
    update_parser.add_argument("--planned-for", help="Updated planned work date.")
    update_parser.add_argument("--due", help="Updated due date.")
    update_parser.add_argument("--content", help="Inline markdown content.")
    update_parser.add_argument("--content-file", help="Path to a markdown file containing the new content.")
    update_parser.add_argument("--tag", action="append", dest="tags", help="Additional tag to add.")

    archive_parser = subparsers.add_parser("archive", help="Archive a work task.")
    archive_parser.add_argument("--path", required=True, help="Task path relative to the vault root.")
    archive_parser.add_argument("--reason", help="Reason for archiving.")

    compact_parser = subparsers.add_parser("compact", help="Remove non-essential task metadata from work tasks.")
    compact_parser.add_argument("--include-archived", action="store_true", help="Also compact archived tasks.")

    subparsers.add_parser("index", help="Regenerate the work task index.")
    subparsers.add_parser("doctor", help="Print resolved configuration and filesystem diagnostics.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        project_root = discover_project_root()
        config = resolve_config(project_root)
        project_name = args.project or detect_project_name(project_root)

        if args.command == "scan":
            payload = {
                "tasks_dir": config.tasks_dir,
                "tasks": scan_tasks(config, args.query, args.status, args.limit, args.include_archived),
            }
            print(json.dumps(payload, indent=2))
            return 0

        if args.command == "read":
            print(read_task(config, args.path))
            return 0

        if args.command == "create":
            content = read_optional_content(args.content, args.content_file)
            payload = create_task(
                config,
                project_name,
                args.title,
                args.slug,
                args.status,
                args.priority,
                args.jira_id,
                args.planned_for,
                args.due,
                content,
                args.tags,
            )
            print(json.dumps(payload, indent=2))
            return 0

        if args.command == "update":
            content = read_optional_content(args.content, args.content_file)
            payload = update_task(
                config,
                project_name,
                args.path,
                args.mode,
                content,
                args.section,
                args.status,
                args.priority,
                args.planned_for,
                args.due,
                args.tags,
            )
            print(json.dumps(payload, indent=2))
            return 0

        if args.command == "archive":
            print(json.dumps(archive_task(config, args.path, args.reason), indent=2))
            return 0

        if args.command == "compact":
            print(json.dumps(compact_task_metadata(config, args.include_archived), indent=2))
            return 0

        if args.command == "index":
            print(json.dumps(regenerate_index(config), indent=2))
            return 0

        if args.command == "doctor":
            print(json.dumps(doctor_payload(project_root, project_name, config), indent=2))
            return 0

        raise WorkTaskError(f"Unknown command: {args.command}")
    except WorkTaskError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
