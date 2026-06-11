#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).resolve()
SKILL_DIR = SCRIPT_PATH.parent.parent
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from obsidian_work import core

SKILL_CONFIG_PATH = SKILL_DIR / "config.json"
PROJECT_CONFIG_RELATIVE_PATHS = [
    Path(".codex") / "obsidian-wiki.json",
    Path(".agents") / "obsidian-wiki.json",
    Path(".claude") / "obsidian-wiki.json",
]
DEFAULT_CONFIG = {
    "wiki_dir": "Wiki",
    "default_tags": ["wiki"],
    "redaction": {
        "enabled": True,
        "patterns": ["API_KEY", "SECRET", "TOKEN", "PASSWORD"],
    },
}
INDEX_FILENAME = ".obsidian-wiki-index.json"
INDEX_VERSION = 1
MAX_INDEX_EXCERPT_CHARS = 600
MAX_SCAN_RESULTS = 20
ARCHIVE_DIRNAME = "_archive"
ARCHIVE_DURABLE_TAGS = {"project-overview", "architecture", "runbook", "glossary"}
ARCHIVE_BOOST_TAGS = {"ticket", "review", "investigation", "refinement"}


class WikiError(Exception):
    pass


@dataclass
class Config:
    vault_path: Path
    wiki_dir: str
    default_tags: list[str]
    redaction_enabled: bool
    redaction_patterns: list[str]


@dataclass
class Document:
    path: Path
    relative_path: str
    title: str
    project: str
    tags: list[str]
    created: str | None
    updated: str | None
    body: str
    frontmatter: dict[str, Any]


@dataclass(frozen=True)
class IndexSearchText:
    title_tokens: frozenset[str]
    tag_tokens: frozenset[str]
    filename_tokens: frozenset[str]
    heading_tokens: frozenset[str]
    body_tokens: frozenset[str]
    ticket_ids: frozenset[str]


def load_json(path: Path) -> dict[str, Any]:
    return core.load_json(path, WikiError)

def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    return core.deep_merge(base, override)

def discover_project_root(start: Path | None = None) -> Path:
    return core.discover_project_root(PROJECT_CONFIG_RELATIVE_PATHS, start)

def project_config_paths(project_root: Path) -> list[Path]:
    return core.project_config_paths(project_root, PROJECT_CONFIG_RELATIVE_PATHS)

def resolve_config(project_root: Path) -> Config:
    merged: dict[str, Any] = deep_merge(DEFAULT_CONFIG, load_json(SKILL_CONFIG_PATH))
    for config_path in reversed(project_config_paths(project_root)):
        merged = deep_merge(merged, load_json(config_path))

    env_vault = os.getenv("OBSIDIAN_VAULT_PATH")
    if env_vault:
        merged["vault_path"] = env_vault

    vault_path = merged.get("vault_path")
    if not vault_path:
        raise WikiError(
            "Missing vault_path. Set OBSIDIAN_VAULT_PATH, add it to "
            ".codex/obsidian-wiki.json, or add it to the skill config."
        )

    wiki_dir = merged.get("wiki_dir") or DEFAULT_CONFIG["wiki_dir"]
    default_tags = merged.get("default_tags") or list(DEFAULT_CONFIG["default_tags"])
    redaction = merged.get("redaction") or {}

    return Config(
        vault_path=Path(vault_path).expanduser().resolve(),
        wiki_dir=str(wiki_dir).strip("/") or DEFAULT_CONFIG["wiki_dir"],
        default_tags=list(default_tags),
        redaction_enabled=bool(redaction.get("enabled", True)),
        redaction_patterns=list(redaction.get("patterns") or DEFAULT_CONFIG["redaction"]["patterns"]),
    )


def now_iso() -> str:
    return core.now_iso()

def slugify(value: str) -> str:
    return core.slugify(value, "Title", WikiError)

def detect_project_name(project_root: Path) -> str:
    return core.detect_project_name(project_root)

def ensure_within(root: Path, target: Path) -> Path:
    return core.ensure_within(root, target, WikiError)

def wiki_project_dir(config: Config, project_name: str) -> Path:
    project_dir = config.vault_path / config.wiki_dir / project_name
    return ensure_within(config.vault_path, project_dir)


def wiki_archive_dir(config: Config) -> Path:
    return ensure_within(config.vault_path, wiki_root_dir(config) / ARCHIVE_DIRNAME)


def wiki_archive_project_dir(config: Config, project_name: str) -> Path:
    return ensure_within(config.vault_path, wiki_archive_dir(config) / project_name)


def wiki_root_dir(config: Config) -> Path:
    return ensure_within(config.vault_path, config.vault_path / config.wiki_dir)


def wiki_project_names(config: Config) -> list[str]:
    root = wiki_root_dir(config)
    if not root.exists():
        return []
    return sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir() and path.name != ARCHIVE_DIRNAME
    )


def index_path(config: Config) -> Path:
    return ensure_within(config.vault_path, wiki_root_dir(config) / INDEX_FILENAME)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    return core.parse_frontmatter(text)

def format_frontmatter(data: dict[str, Any]) -> str:
    return core.format_frontmatter(data)

def read_content_arg(content: str | None, content_file: str | None) -> str:
    return core.read_content_arg(content, content_file, WikiError)

def normalize_tags(config: Config, project_name: str, extra_tags: list[str] | None) -> list[str]:
    return core.normalize_tags(config.default_tags, project_name, extra_tags)

def redact_secrets(text: str, config: Config) -> str:
    return core.redact_secrets(text, config.redaction_enabled, config.redaction_patterns)

def atomic_write(path: Path, content: str) -> None:
    core.atomic_write(path, content)

def load_document(path: Path, vault_root: Path) -> Document:
    safe_path = ensure_within(vault_root, path)
    text = safe_path.read_text()
    frontmatter, body = parse_frontmatter(text)
    try:
        relative_path = str(safe_path.relative_to(vault_root))
    except ValueError:
        relative_path = str(safe_path)
    return Document(
        path=safe_path,
        relative_path=relative_path,
        title=str(frontmatter.get("title") or safe_path.stem.replace("-", " ").title()),
        project=str(frontmatter.get("project") or ""),
        tags=list(frontmatter.get("tags") or []),
        created=frontmatter.get("created"),
        updated=frontmatter.get("updated"),
        body=body,
        frontmatter=frontmatter,
    )


def frontmatter_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.casefold() in {"true", "yes", "1"}
    return False


def tokenize(value: str) -> list[str]:
    return [term.casefold() for term in re.findall(r"[A-Za-z0-9]+", value)]


def extract_ticket_ids(value: str) -> list[str]:
    ids: list[str] = []
    for ticket_id in re.findall(r"\b[A-Z][A-Z0-9]+-\d+\b", value.upper()):
        if ticket_id not in ids:
            ids.append(ticket_id)
    return ids


def extract_headings(body: str) -> list[str]:
    headings: list[str] = []
    for line in body.splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if match:
            headings.append(match.group(1).strip())
    return headings


def make_excerpt(body: str) -> str:
    text = re.sub(r"\s+", " ", body).strip()
    return text[:MAX_INDEX_EXCERPT_CHARS]


def index_entry_for_document(doc: Document) -> dict[str, Any]:
    source_text = " ".join([doc.relative_path, doc.title, *doc.tags, *extract_headings(doc.body), doc.body])
    archived = frontmatter_bool(doc.frontmatter.get("archived")) or f"/{ARCHIVE_DIRNAME}/" in f"/{doc.relative_path}"
    return {
        "path": doc.relative_path,
        "project": doc.project,
        "title": doc.title,
        "tags": doc.tags,
        "updated": doc.updated,
        "headings": extract_headings(doc.body)[:20],
        "excerpt": make_excerpt(doc.body),
        "tokens": sorted(set(tokenize(source_text))),
        "ticket_ids": extract_ticket_ids(source_text),
        "mtime_ns": doc.path.stat().st_mtime_ns,
        "archived": archived,
        "original_path": doc.frontmatter.get("original_path"),
        "archived_at": doc.frontmatter.get("archived_at"),
        "archived_reason": doc.frontmatter.get("archived_reason"),
    }


def iter_wiki_markdown_paths(config: Config) -> list[Path]:
    root = wiki_root_dir(config)
    if not root.exists():
        return []
    active_paths = [
        path
        for path in root.glob("*/*.md")
        if path.parent.name != ARCHIVE_DIRNAME and ARCHIVE_DIRNAME not in path.relative_to(root).parts
    ]
    archive_paths = list(wiki_archive_dir(config).glob("*/*.md")) if wiki_archive_dir(config).exists() else []
    return sorted([*active_paths, *archive_paths])


def load_index(config: Config) -> dict[str, Any] | None:
    path = index_path(config)
    if not path.exists():
        return None
    data = load_json(path)
    if data.get("version") != INDEX_VERSION or not isinstance(data.get("documents"), list):
        return None
    return data


def write_index(config: Config, documents: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {
        "version": INDEX_VERSION,
        "generated": now_iso(),
        "wiki_dir": config.wiki_dir,
        "documents": sorted(documents, key=lambda doc: str(doc.get("path", ""))),
    }
    atomic_write(index_path(config), json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def rebuild_index(config: Config) -> dict[str, Any]:
    documents: list[dict[str, Any]] = []
    for path in iter_wiki_markdown_paths(config):
        doc = load_document(path, config.vault_path)
        if not doc.project:
            doc.project = path.parent.name
        documents.append(index_entry_for_document(doc))
    return write_index(config, documents)


def refresh_index_entry(config: Config, path: Path) -> None:
    existing_index = load_index(config)
    if existing_index is None:
        return

    safe_path = ensure_within(config.vault_path, path)
    relative_path = str(safe_path.relative_to(config.vault_path))
    documents = [doc for doc in existing_index["documents"] if doc.get("path") != relative_path]
    if safe_path.exists():
        documents.append(index_entry_for_document(load_document(safe_path, config.vault_path)))
    write_index(config, documents)


def index_search_text(entry: dict[str, Any]) -> IndexSearchText:
    return IndexSearchText(
        title_tokens=frozenset(tokenize(str(entry.get("title", "")))),
        tag_tokens=frozenset(tokenize(" ".join(entry.get("tags") or []))),
        filename_tokens=frozenset(tokenize(str(entry.get("path", "")).rsplit("/", 1)[-1])),
        heading_tokens=frozenset(tokenize(" ".join(entry.get("headings") or []))),
        body_tokens=frozenset(entry.get("tokens") or []),
        ticket_ids=frozenset(entry.get("ticket_ids") or []),
    )


def matches_required_query_terms(query_terms: list[str], query_ticket_ids: list[str], body_tokens: frozenset[str]) -> bool:
    if not query_terms or query_ticket_ids:
        return True

    matched_terms = sum(1 for term in query_terms if term in body_tokens)
    if matched_terms == 0:
        return False
    if len(query_terms) > 1 and matched_terms < max(1, len(query_terms) // 2):
        return False
    return True


def score_index_entry(entry: dict[str, Any], query: str | None) -> tuple[int, str]:
    query_terms = tokenize(query or "")
    query_ticket_ids = extract_ticket_ids(query or "")
    if not query_terms and not query_ticket_ids:
        return 1, "listed"

    score = 0
    reasons: list[str] = []
    search_text = index_search_text(entry)

    for ticket_id in query_ticket_ids:
        if ticket_id in search_text.ticket_ids:
            score += 80
            reasons.append(f"ticket:{ticket_id}")

    for term in query_terms:
        if term in search_text.title_tokens:
            score += 20
            reasons.append("title")
        elif term in search_text.tag_tokens:
            score += 14
            reasons.append("tag")
        elif term in search_text.filename_tokens:
            score += 12
            reasons.append("filename")
        elif term in search_text.heading_tokens:
            score += 8
            reasons.append("heading")
        elif term in search_text.body_tokens:
            score += 3
            reasons.append("body")

    if not matches_required_query_terms(query_terms, query_ticket_ids, search_text.body_tokens):
        return 0, ""

    reason = ",".join(dict.fromkeys(reasons)) or "match"
    return score, reason


def present_index_entry(entry: dict[str, Any], score: int | None = None, reason: str | None = None, include_snippet: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "path": entry.get("path"),
        "title": entry.get("title"),
        "tags": entry.get("tags") or [],
        "updated": entry.get("updated"),
    }
    if entry.get("archived"):
        payload["archived"] = True
        payload["original_path"] = entry.get("original_path")
        payload["archived_at"] = entry.get("archived_at")
    if score is not None:
        payload["score"] = score
    if reason:
        payload["reason"] = reason
    if include_snippet:
        payload["snippet"] = entry.get("excerpt") or ""
    return payload


def resolve_doc_path(config: Config, path_arg: str) -> Path:
    raw_path = Path(path_arg).expanduser()
    if raw_path.is_absolute():
        return ensure_within(config.vault_path, raw_path)
    return ensure_within(config.vault_path, config.vault_path / raw_path)


def scan_indexed_documents(
    index_documents: list[dict[str, Any]],
    project_name: str,
    query: str | None,
    limit: int,
    include_snippet: bool,
    include_archived: bool,
) -> list[dict[str, Any]]:
    matches: list[tuple[int, str, dict[str, Any]]] = []
    for entry in index_documents:
        if entry.get("project") != project_name:
            continue
        if entry.get("archived") and not include_archived:
            continue
        score, reason = score_index_entry(entry, query)
        if score <= 0:
            continue
        matches.append((score, reason, entry))

    matches.sort(key=lambda item: (-item[0], str(item[2].get("title", ""))))
    return [present_index_entry(entry, score, reason, include_snippet) for score, reason, entry in matches[:limit]]


def filesystem_scan_paths(config: Config, project_name: str, include_archived: bool) -> list[Path]:
    project_dir = wiki_project_dir(config, project_name)
    archive_project_dir = wiki_archive_project_dir(config, project_name)

    scan_paths = sorted(project_dir.glob("*.md")) if project_dir.exists() else []
    if include_archived and archive_project_dir.exists():
        scan_paths.extend(sorted(archive_project_dir.glob("*.md")))
    return scan_paths


def scan_filesystem_documents(
    config: Config,
    project_name: str,
    query: str | None,
    limit: int,
    include_archived: bool,
) -> list[dict[str, Any]]:
    query_terms = tokenize(query or "")
    documents: list[dict[str, Any]] = []

    for path in filesystem_scan_paths(config, project_name, include_archived):
        doc = load_document(path, config.vault_path)
        haystack = " ".join([doc.title, *doc.tags, path.name]).lower()
        if query_terms and not all(term in haystack for term in query_terms):
            continue
        documents.append(present_index_entry(index_entry_for_document(doc)))

    return documents[:limit]


def scan_documents(
    config: Config,
    project_name: str,
    query: str | None,
    limit: int = MAX_SCAN_RESULTS,
    include_snippet: bool = False,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    existing_index = load_index(config)
    if existing_index is not None:
        return scan_indexed_documents(
            existing_index["documents"],
            project_name,
            query,
            limit,
            include_snippet,
            include_archived,
        )

    return scan_filesystem_documents(config, project_name, query, limit, include_archived)


def remove_duplicate_title_heading(body: str, title: str) -> str:
    lines = body.strip().splitlines()
    if not lines:
        return ""

    match = re.match(r"^#\s+(.+?)\s*$", lines[0])
    if not match or match.group(1).strip().casefold() != title.strip().casefold():
        return body.strip()

    remaining_lines = lines[1:]
    while remaining_lines and not remaining_lines[0].strip():
        remaining_lines = remaining_lines[1:]
    return "\n".join(remaining_lines).strip()


def render_document(frontmatter: dict[str, Any], body: str) -> str:
    cleaned_body = remove_duplicate_title_heading(body, str(frontmatter["title"]))
    return f"{format_frontmatter(frontmatter)}\n\n# {frontmatter['title']}\n\n{cleaned_body}\n"


def create_document(config: Config, project_name: str, title: str, body: str, extra_tags: list[str] | None) -> dict[str, Any]:
    project_dir = wiki_project_dir(config, project_name)
    slug = slugify(title)
    path = ensure_within(config.vault_path, project_dir / f"{slug}.md")
    if path.exists():
        raise WikiError(f"Document already exists: {path.relative_to(config.vault_path)}")

    timestamp = now_iso()
    frontmatter = {
        "title": title.strip(),
        "created": timestamp,
        "updated": timestamp,
        "project": project_name,
        "tags": normalize_tags(config, project_name, extra_tags),
    }
    content = render_document(frontmatter, redact_secrets(body, config))
    atomic_write(path, content)
    refresh_index_entry(config, path)
    return {
        "path": str(path.relative_to(config.vault_path)),
        "title": title.strip(),
        "created": timestamp,
        "updated": timestamp,
    }


def append_body(existing_body: str, new_content: str) -> str:
    return core.append_body(existing_body, new_content)

def replace_section(existing_body: str, section: str, new_content: str) -> str:
    return core.replace_section(existing_body, section, new_content, WikiError)

def update_document(
    config: Config,
    project_name: str,
    path_arg: str,
    mode: str,
    new_content: str,
    section: str | None,
) -> dict[str, Any]:
    path = resolve_doc_path(config, path_arg)
    if not path.exists():
        raise WikiError(f"Document does not exist: {path_arg}")

    text = path.read_text()
    frontmatter, body = parse_frontmatter(text)
    if not frontmatter:
        raise WikiError(f"Document is missing expected frontmatter: {path}")

    redacted_content = redact_secrets(new_content, config)
    if mode == "append":
        updated_body = append_body(body, redacted_content)
    elif mode == "replace":
        if not section:
            raise WikiError("--section is required when mode is replace.")
        updated_body = replace_section(body, section, redacted_content)
    elif mode == "rewrite":
        updated_body = redacted_content.strip()
    else:
        raise WikiError(f"Unknown update mode: {mode}")

    frontmatter["updated"] = now_iso()
    if not frontmatter.get("project"):
        frontmatter["project"] = project_name
    if not frontmatter.get("tags"):
        frontmatter["tags"] = normalize_tags(config, project_name, [])

    rendered = f"{format_frontmatter(frontmatter)}\n\n{updated_body.strip()}\n"
    atomic_write(path, rendered)
    refresh_index_entry(config, path)
    return {
        "path": str(path.relative_to(config.vault_path)),
        "title": frontmatter.get("title"),
        "updated": frontmatter.get("updated"),
        "mode": mode,
        "section": section,
    }


def read_document(config: Config, path_arg: str) -> str:
    path = resolve_doc_path(config, path_arg)
    if not path.exists():
        raise WikiError(f"Document does not exist: {path_arg}")
    return path.read_text()


def filesystem_timestamp(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat()


def add_frontmatter_to_document(
    config: Config,
    project_name: str,
    path_arg: str,
    title: str | None,
    extra_tags: list[str] | None,
) -> dict[str, Any]:
    path = resolve_doc_path(config, path_arg)
    if not path.exists():
        raise WikiError(f"Document does not exist: {path_arg}")

    text = path.read_text()
    existing_frontmatter, body = parse_frontmatter(text)
    if existing_frontmatter:
        raise WikiError(f"Document already has frontmatter: {path.relative_to(config.vault_path)}")

    timestamp = filesystem_timestamp(path)
    frontmatter = {
        "title": (title or path.stem.replace("-", " ").title()).strip(),
        "created": timestamp,
        "updated": timestamp,
        "project": project_name,
        "tags": normalize_tags(config, project_name, extra_tags),
    }

    atomic_write(path, render_existing_document(frontmatter, body))
    refresh_index_entry(config, path)
    return {
        "path": str(path.relative_to(config.vault_path)),
        "title": frontmatter["title"],
        "created": frontmatter["created"],
        "updated": frontmatter["updated"],
        "tags": frontmatter["tags"],
    }


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.astimezone()
    return parsed


def age_days(value: str | None) -> int | None:
    parsed = parse_iso_datetime(value)
    if not parsed:
        return None
    return max(0, (datetime.now().astimezone() - parsed).days)


def archive_destination_for(config: Config, doc: Document) -> Path:
    project_name = doc.project or doc.path.parent.name
    return ensure_within(config.vault_path, wiki_archive_project_dir(config, project_name) / doc.path.name)


def archive_candidates(
    config: Config,
    project_name: str,
    older_than_days: int,
    limit: int,
    force: bool = False,
) -> list[dict[str, Any]]:
    cutoff = datetime.now().astimezone() - timedelta(days=older_than_days)
    candidates: list[dict[str, Any]] = []
    project_dir = wiki_project_dir(config, project_name)
    if not project_dir.exists():
        return []

    for path in sorted(project_dir.glob("*.md")):
        doc = load_document(path, config.vault_path)
        if not doc.frontmatter:
            candidates.append(
                {
                    "path": doc.relative_path,
                    "title": doc.title,
                    "reason": "needs_review",
                    "detail": "missing frontmatter",
                }
            )
            continue
        if frontmatter_bool(doc.frontmatter.get("archived")):
            continue
        has_durable_tag = bool(ARCHIVE_DURABLE_TAGS.intersection(set(doc.tags)))
        if has_durable_tag and not force:
            continue
        updated = parse_iso_datetime(doc.updated or doc.created)
        if not updated or updated > cutoff:
            continue
        recommendation = "old_note"
        if ARCHIVE_BOOST_TAGS.intersection(set(doc.tags)) or extract_ticket_ids(f"{doc.title} {doc.path.name}"):
            recommendation = "old_ticket_or_investigation"
        if has_durable_tag:
            recommendation = "old_durable_note"
        candidates.append(
            {
                "path": doc.relative_path,
                "title": doc.title,
                "tags": doc.tags,
                "updated": doc.updated,
                "age_days": age_days(doc.updated or doc.created),
                "reason": recommendation,
            }
        )

    candidates.sort(key=lambda item: (item.get("updated") or "", item.get("title") or ""))
    return candidates[:limit]


def archive_candidates_global(
    config: Config,
    older_than_days: int,
    limit: int,
    force: bool = False,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for project_name in wiki_project_names(config):
        for candidate in archive_candidates(config, project_name, older_than_days, limit, force):
            candidates.append({"project": project_name, **candidate})

    candidates.sort(key=lambda item: (item.get("updated") or "", item.get("project") or "", item.get("title") or ""))
    return candidates[:limit]


def render_existing_document(frontmatter: dict[str, Any], body: str) -> str:
    return f"{format_frontmatter(frontmatter)}\n\n{body.strip()}\n"


def remove_empty_directory(directory: Path, protected_directories: set[Path]) -> bool:
    resolved_directory = directory.resolve()
    resolved_protected = {path.resolve() for path in protected_directories}
    if resolved_directory in resolved_protected:
        return False
    try:
        resolved_directory.rmdir()
    except OSError:
        return False
    return True


def cleanup_empty_directories(config: Config, project_name: str, global_scope: bool = False) -> dict[str, Any]:
    root = wiki_root_dir(config)
    archive_root = wiki_archive_dir(config)
    protected_directories = {root, archive_root}
    candidate_roots = [root] if global_scope else [wiki_project_dir(config, project_name), wiki_archive_project_dir(config, project_name)]
    candidates: list[Path] = []

    for candidate_root in candidate_roots:
        if not candidate_root.exists() or not candidate_root.is_dir():
            continue
        candidates.extend(path for path in candidate_root.rglob("*") if path.is_dir())
        candidates.append(candidate_root)

    unique_candidates = sorted({path.resolve() for path in candidates}, key=lambda path: len(path.parts), reverse=True)
    removed_paths: list[str] = []
    for candidate in unique_candidates:
        if remove_empty_directory(candidate, protected_directories):
            removed_paths.append(str(candidate.relative_to(config.vault_path)))

    return {
        "scope": "global" if global_scope else "project",
        "project": None if global_scope else project_name,
        "removed_directories": sorted(removed_paths),
        "removed_count": len(removed_paths),
    }


def archive_document(config: Config, path_arg: str, reason: str | None) -> dict[str, Any]:
    source_path = resolve_doc_path(config, path_arg)
    if not source_path.exists():
        raise WikiError(f"Document does not exist: {path_arg}")

    doc = load_document(source_path, config.vault_path)
    if not doc.frontmatter:
        raise WikiError(f"Document is missing expected frontmatter: {source_path}")
    if frontmatter_bool(doc.frontmatter.get("archived")):
        raise WikiError(f"Document is already archived: {doc.relative_path}")

    destination_path = archive_destination_for(config, doc)
    if destination_path.exists():
        raise WikiError(f"Archive destination already exists: {destination_path.relative_to(config.vault_path)}")

    timestamp = now_iso()
    frontmatter = dict(doc.frontmatter)
    frontmatter["updated"] = timestamp
    frontmatter["archived"] = True
    frontmatter["archived_at"] = timestamp
    frontmatter["archived_reason"] = reason or "archived"
    frontmatter["original_path"] = doc.relative_path

    atomic_write(destination_path, render_existing_document(frontmatter, doc.body))
    source_path.unlink()
    active_directory_removed = remove_empty_directory(source_path.parent, {wiki_root_dir(config), wiki_archive_dir(config)})
    refresh_index_entry(config, source_path)
    refresh_index_entry(config, destination_path)
    return {
        "path": str(destination_path.relative_to(config.vault_path)),
        "original_path": doc.relative_path,
        "title": doc.title,
        "archived_at": timestamp,
        "reason": frontmatter["archived_reason"],
        "active_directory_removed": active_directory_removed,
    }


def restore_document(config: Config, path_arg: str) -> dict[str, Any]:
    archive_path = resolve_doc_path(config, path_arg)
    if not archive_path.exists():
        raise WikiError(f"Document does not exist: {path_arg}")

    doc = load_document(archive_path, config.vault_path)
    if not doc.frontmatter:
        raise WikiError(f"Document is missing expected frontmatter: {archive_path}")
    if not frontmatter_bool(doc.frontmatter.get("archived")):
        raise WikiError(f"Document is not archived: {doc.relative_path}")

    original_path = str(doc.frontmatter.get("original_path") or "")
    if not original_path:
        raise WikiError(f"Archived document is missing original_path: {doc.relative_path}")
    destination_path = resolve_doc_path(config, original_path)
    if destination_path.exists():
        raise WikiError(f"Restore destination already exists: {original_path}")

    frontmatter = dict(doc.frontmatter)
    timestamp = now_iso()
    frontmatter["updated"] = timestamp
    for key in ["archived", "archived_at", "archived_reason", "original_path"]:
        frontmatter.pop(key, None)

    atomic_write(destination_path, render_existing_document(frontmatter, doc.body))
    archive_path.unlink()
    archive_directory_removed = remove_empty_directory(archive_path.parent, {wiki_archive_dir(config), wiki_root_dir(config)})
    refresh_index_entry(config, archive_path)
    refresh_index_entry(config, destination_path)
    return {
        "path": str(destination_path.relative_to(config.vault_path)),
        "archived_path": doc.relative_path,
        "title": doc.title,
        "restored_at": timestamp,
        "archive_directory_removed": archive_directory_removed,
    }


def archive_status(config: Config, project_name: str) -> dict[str, Any]:
    active_dir = wiki_project_dir(config, project_name)
    archive_dir = wiki_archive_project_dir(config, project_name)
    active_count = len(list(active_dir.glob("*.md"))) if active_dir.exists() else 0
    archived_count = len(list(archive_dir.glob("*.md"))) if archive_dir.exists() else 0
    return {
        "project": project_name,
        "active_documents": active_count,
        "archived_documents": archived_count,
        "archive_path": str(archive_dir.relative_to(config.vault_path)),
    }


def index_status(config: Config) -> dict[str, Any]:
    path = index_path(config)
    data = load_index(config)
    markdown_paths = iter_wiki_markdown_paths(config)
    markdown_count = len(markdown_paths)
    indexed_count = len(data["documents"]) if data else 0
    indexed_mtimes = {doc.get("path"): doc.get("mtime_ns") for doc in data["documents"]} if data else {}
    stale_paths: list[str] = []
    if data:
        for markdown_path in markdown_paths:
            relative_path = str(markdown_path.relative_to(config.vault_path))
            if indexed_mtimes.get(relative_path) != markdown_path.stat().st_mtime_ns:
                stale_paths.append(relative_path)
        markdown_relative_paths = {str(markdown_path.relative_to(config.vault_path)) for markdown_path in markdown_paths}
        for indexed_path in indexed_mtimes:
            if indexed_path not in markdown_relative_paths:
                stale_paths.append(str(indexed_path))
    return {
        "path": str(path.relative_to(config.vault_path)),
        "exists": path.exists(),
        "valid": data is not None,
        "documents": indexed_count,
        "markdown_documents": markdown_count,
        "generated": data.get("generated") if data else None,
        "stale": data is None or indexed_count != markdown_count or bool(stale_paths),
        "stale_paths": stale_paths[:20],
    }


def doctor_report(config: Config, project_root: Path, project_name: str) -> dict[str, Any]:
    root = wiki_root_dir(config)
    project_dir = wiki_project_dir(config, project_name)
    config_sources = [str(path) for path in project_config_paths(project_root) if path.exists()]
    if SKILL_CONFIG_PATH.exists():
        config_sources.append(str(SKILL_CONFIG_PATH))
    if os.getenv("OBSIDIAN_VAULT_PATH"):
        config_sources.append("OBSIDIAN_VAULT_PATH")

    return {
        "project_root": str(project_root),
        "project": project_name,
        "config_sources": config_sources,
        "vault_path": str(config.vault_path),
        "wiki_dir": config.wiki_dir,
        "wiki_root": str(root),
        "project_wiki_dir": str(project_dir),
        "project_wiki_exists": project_dir.exists(),
        "index": index_status(config),
        "writes_possible": root.exists() or os.access(config.vault_path, os.W_OK),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage persistent Obsidian wiki documents for the active project.")
    parser.add_argument("--project", help="Override the auto-detected project name.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="List wiki documents for the active project.")
    scan_parser.add_argument("--query", help="Optional keywords to filter by indexed title, tags, filename, headings, and excerpt.")
    scan_parser.add_argument("--limit", type=int, default=MAX_SCAN_RESULTS, help=f"Maximum results to return. Default: {MAX_SCAN_RESULTS}.")
    scan_parser.add_argument("--include-snippet", action="store_true", help="Include short indexed snippets in scan results.")
    scan_parser.add_argument("--include-archived", action="store_true", help="Include archived documents in scan results.")

    read_parser = subparsers.add_parser("read", help="Read a wiki document.")
    read_parser.add_argument("--path", required=True, help="Wiki document path relative to the vault root.")

    create_parser = subparsers.add_parser("create", help="Create a new wiki document.")
    create_parser.add_argument("--title", required=True, help="Document title.")
    create_parser.add_argument("--content", help="Inline markdown content.")
    create_parser.add_argument("--content-file", help="Path to a markdown file containing the body content.")
    create_parser.add_argument("--tag", action="append", dest="tags", help="Additional tag to add.")

    update_parser = subparsers.add_parser("update", help="Append to, replace a section in, or rewrite a document.")
    update_parser.add_argument("--path", required=True, help="Wiki document path relative to the vault root.")
    update_parser.add_argument("--mode", required=True, choices=["append", "replace", "rewrite"], help="Update mode.")
    update_parser.add_argument("--section", help="Section heading to replace when using replace mode.")
    update_parser.add_argument("--content", help="Inline markdown content.")
    update_parser.add_argument("--content-file", help="Path to a markdown file containing the new content.")

    frontmatter_parser = subparsers.add_parser("add-frontmatter", help="Add generated frontmatter to an existing plain Markdown note.")
    frontmatter_parser.add_argument("--path", required=True, help="Wiki document path relative to the vault root.")
    frontmatter_parser.add_argument("--title", help="Title to store in frontmatter. Defaults to the filename title.")
    frontmatter_parser.add_argument("--tag", action="append", dest="tags", help="Additional tag to add.")

    index_parser = subparsers.add_parser("index", help="Manage the lightweight wiki search index.")
    index_subparsers = index_parser.add_subparsers(dest="index_command", required=True)
    index_subparsers.add_parser("rebuild", help="Rebuild the wiki search index from Markdown documents.")
    index_subparsers.add_parser("status", help="Report whether the wiki search index exists and is fresh.")

    archive_parser = subparsers.add_parser("archive", help="Archive, restore, and inspect old wiki notes.")
    archive_subparsers = archive_parser.add_subparsers(dest="archive_command", required=True)
    archive_candidates_parser = archive_subparsers.add_parser("candidates", help="List explicit archive candidates without changing files.")
    archive_candidates_parser.add_argument("--older-than-days", type=int, default=90, help="Minimum note age by updated timestamp. Default: 90.")
    archive_candidates_parser.add_argument("--limit", type=int, default=MAX_SCAN_RESULTS, help=f"Maximum candidates to return. Default: {MAX_SCAN_RESULTS}.")
    archive_candidates_parser.add_argument("--force", action="store_true", help="Include durable notes such as project overviews, architecture notes, runbooks, and glossary entries.")
    archive_candidates_parser.add_argument("--global", dest="global_scope", action="store_true", help="List candidates across all active project wiki folders.")
    archive_apply_parser = archive_subparsers.add_parser("apply", help="Archive one explicitly selected wiki note.")
    archive_apply_parser.add_argument("--path", required=True, help="Active wiki document path relative to the vault root.")
    archive_apply_parser.add_argument("--reason", help="Reason stored in archive frontmatter.")
    archive_restore_parser = archive_subparsers.add_parser("restore", help="Restore one archived wiki note to its original path.")
    archive_restore_parser.add_argument("--path", required=True, help="Archived wiki document path relative to the vault root.")
    archive_cleanup_parser = archive_subparsers.add_parser("cleanup", help="Remove empty active and archived wiki folders.")
    archive_cleanup_parser.add_argument("--global", dest="global_scope", action="store_true", help="Remove empty folders across all wiki project folders.")
    archive_subparsers.add_parser("status", help="Show active and archived note counts for the project.")

    subparsers.add_parser("doctor", help="Show resolved project, configuration, vault, and index diagnostics.")

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
                "project": project_name,
                "documents": scan_documents(
                    config,
                    project_name,
                    args.query,
                    args.limit,
                    args.include_snippet,
                    args.include_archived,
                ),
            }
            print(json.dumps(payload, indent=2))
            return 0

        if args.command == "read":
            print(read_document(config, args.path))
            return 0

        if args.command == "create":
            content = read_content_arg(args.content, args.content_file)
            payload = create_document(config, project_name, args.title, content, args.tags)
            print(json.dumps(payload, indent=2))
            return 0

        if args.command == "update":
            content = read_content_arg(args.content, args.content_file)
            payload = update_document(config, project_name, args.path, args.mode, content, args.section)
            print(json.dumps(payload, indent=2))
            return 0

        if args.command == "add-frontmatter":
            payload = add_frontmatter_to_document(config, project_name, args.path, args.title, args.tags)
            print(json.dumps(payload, indent=2))
            return 0

        if args.command == "index":
            if args.index_command == "rebuild":
                payload = rebuild_index(config)
                print(
                    json.dumps(
                        {
                            "path": str(index_path(config).relative_to(config.vault_path)),
                            "documents": len(payload["documents"]),
                            "generated": payload["generated"],
                        },
                        indent=2,
                    )
                )
                return 0
            if args.index_command == "status":
                print(json.dumps(index_status(config), indent=2))
                return 0

        if args.command == "archive":
            if args.archive_command == "candidates":
                candidates = (
                    archive_candidates_global(config, args.older_than_days, args.limit, args.force)
                    if args.global_scope
                    else archive_candidates(config, project_name, args.older_than_days, args.limit, args.force)
                )
                payload = {
                    "scope": "global" if args.global_scope else "project",
                    "project": None if args.global_scope else project_name,
                    "candidates": candidates,
                }
                print(json.dumps(payload, indent=2))
                return 0
            if args.archive_command == "apply":
                print(json.dumps(archive_document(config, args.path, args.reason), indent=2))
                return 0
            if args.archive_command == "restore":
                print(json.dumps(restore_document(config, args.path), indent=2))
                return 0
            if args.archive_command == "cleanup":
                print(json.dumps(cleanup_empty_directories(config, project_name, args.global_scope), indent=2))
                return 0
            if args.archive_command == "status":
                print(json.dumps(archive_status(config, project_name), indent=2))
                return 0

        if args.command == "doctor":
            print(json.dumps(doctor_report(config, project_root, project_name), indent=2))
            return 0

        raise WikiError(f"Unknown command: {args.command}")
    except WikiError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
