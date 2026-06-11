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
    Path(".codex") / "obsidian-glossary.json",
    Path(".agents") / "obsidian-glossary.json",
    Path(".claude") / "obsidian-glossary.json",
]
DEFAULT_CONFIG = {
    "glossary_dir": "Glossary",
    "index_file": "Index.md",
    "default_tags": ["glossary"],
    "redaction": {
        "enabled": True,
        "patterns": ["API_KEY", "SECRET", "TOKEN", "PASSWORD"],
    },
}


class GlossaryError(Exception):
    pass


@dataclass
class Config:
    vault_path: Path
    glossary_dir: str
    index_file: str
    default_tags: list[str]
    redaction_enabled: bool
    redaction_patterns: list[str]


@dataclass
class Entry:
    path: Path
    relative_path: str
    title: str
    canonical_term: str
    summary: str
    aliases: list[str]
    source_projects: list[str]
    tags: list[str]
    created: str | None
    updated: str | None
    body: str


def load_json(path: Path) -> dict[str, Any]:
    return core.load_json(path, GlossaryError)

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
        raise GlossaryError(
            "Missing vault_path. Set OBSIDIAN_VAULT_PATH, add it to "
            ".codex/obsidian-glossary.json, or add it to the skill config."
        )

    glossary_dir = merged.get("glossary_dir") or DEFAULT_CONFIG["glossary_dir"]
    index_file = merged.get("index_file") or DEFAULT_CONFIG["index_file"]
    default_tags = merged.get("default_tags") or list(DEFAULT_CONFIG["default_tags"])
    redaction = merged.get("redaction") or {}

    return Config(
        vault_path=Path(vault_path).expanduser().resolve(),
        glossary_dir=str(glossary_dir).strip("/") or DEFAULT_CONFIG["glossary_dir"],
        index_file=str(index_file).strip("/") or DEFAULT_CONFIG["index_file"],
        default_tags=list(default_tags),
        redaction_enabled=bool(redaction.get("enabled", True)),
        redaction_patterns=list(redaction.get("patterns") or DEFAULT_CONFIG["redaction"]["patterns"]),
    )


def now_iso() -> str:
    return core.now_iso()

def slugify(value: str) -> str:
    return core.slugify(value, "Term", GlossaryError)

def detect_project_name(project_root: Path) -> str:
    return core.detect_project_name(project_root)

def ensure_within(root: Path, target: Path) -> Path:
    return core.ensure_within(root, target, GlossaryError)

def glossary_dir(config: Config) -> Path:
    return ensure_within(config.vault_path, config.vault_path / config.glossary_dir)


def index_path(config: Config) -> Path:
    return ensure_within(config.vault_path, glossary_dir(config) / config.index_file)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    return core.parse_frontmatter(text)

def format_frontmatter(data: dict[str, Any]) -> str:
    return core.format_frontmatter(data)

def read_content_arg(content: str | None, content_file: str | None) -> str:
    return core.read_content_arg(content, content_file, GlossaryError)

def normalize_tags(config: Config, project_name: str, extra_tags: list[str] | None) -> list[str]:
    return core.normalize_tags(config.default_tags, project_name, extra_tags)

def normalize_list(values: list[str] | str | None) -> list[str]:
    return core.normalize_list(values)

def redact_secrets(text: str, config: Config) -> str:
    return core.redact_secrets(text, config.redaction_enabled, config.redaction_patterns)

def atomic_write(path: Path, content: str) -> None:
    core.atomic_write(path, content)

def resolve_doc_path(config: Config, path_arg: str) -> Path:
    raw_path = Path(path_arg).expanduser()
    if raw_path.is_absolute():
        return ensure_within(config.vault_path, raw_path)
    return ensure_within(config.vault_path, config.vault_path / raw_path)


def load_entry(path: Path, vault_root: Path) -> Entry:
    safe_path = ensure_within(vault_root, path)
    text = safe_path.read_text()
    frontmatter, body = parse_frontmatter(text)
    try:
        relative_path = str(safe_path.relative_to(vault_root))
    except ValueError:
        relative_path = str(safe_path)

    fallback_title = safe_path.stem.replace("-", " ")
    title = str(frontmatter.get("title") or fallback_title)
    canonical_term = str(frontmatter.get("canonical_term") or title)
    return Entry(
        path=safe_path,
        relative_path=relative_path,
        title=title,
        canonical_term=canonical_term,
        summary=str(frontmatter.get("summary") or first_meaning_sentence(body)),
        aliases=normalize_list(frontmatter.get("aliases")),
        source_projects=normalize_list(frontmatter.get("source_projects")),
        tags=normalize_list(frontmatter.get("tags")),
        created=frontmatter.get("created"),
        updated=frontmatter.get("updated"),
        body=body,
    )


def first_meaning_sentence(body: str) -> str:
    match = re.search(r"^## Meaning\s+(.*?)(?:^## |\Z)", body, flags=re.MULTILINE | re.DOTALL)
    text = match.group(1).strip() if match else body.strip()
    text = re.sub(r"\s+", " ", re.sub(r"^#.*$", "", text, flags=re.MULTILINE)).strip()
    if not text:
        return ""
    sentence = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
    return sentence[:180]


def list_entries(config: Config) -> list[Entry]:
    directory = glossary_dir(config)
    if not directory.exists():
        return []
    entries: list[Entry] = []
    idx_path = index_path(config)
    for path in sorted(directory.glob("*.md")):
        if path.resolve() == idx_path.resolve():
            continue
        entries.append(load_entry(path, config.vault_path))
    return entries


def scan_entries(config: Config, query: str | None, limit: int | None = None) -> list[dict[str, Any]]:
    query_terms = [term.lower() for term in re.findall(r"[A-Za-z0-9_-]+", query or "")]
    documents: list[dict[str, Any]] = []

    for entry in list_entries(config):
        haystack = " ".join(
            [
                entry.title,
                entry.canonical_term,
                entry.summary,
                *entry.aliases,
                *entry.tags,
                entry.path.name,
            ]
        ).lower()
        if query_terms and not all(term in haystack for term in query_terms):
            continue
        documents.append(entry_payload(entry))

    if limit is not None:
        documents = documents[:limit]
    return documents


def entry_payload(entry: Entry) -> dict[str, Any]:
    return {
        "path": entry.relative_path,
        "title": entry.title,
        "canonical_term": entry.canonical_term,
        "summary": entry.summary,
        "aliases": entry.aliases,
        "source_projects": entry.source_projects,
        "tags": entry.tags,
        "updated": entry.updated,
    }


def render_entry(frontmatter: dict[str, Any], body: str) -> str:
    cleaned_body = body.strip()
    title = frontmatter["title"]
    if not cleaned_body.startswith(f"# {title}"):
        cleaned_body = f"# {title}\n\n{cleaned_body}".strip()
    return f"{format_frontmatter(frontmatter)}\n\n{cleaned_body}\n"


def render_default_body(term: str, body: str) -> str:
    if body.strip():
        return body
    return f"""## Meaning
Document what `{term}` means at Hypatos.

## Product Context
Document how `{term}` fits into the product, workflows, users, or business domain.

## Source Code Evidence
Document repository-backed findings with file references.

## Related Terms

## Open Questions
"""


def create_entry(
    config: Config,
    project_name: str,
    term: str,
    body: str,
    summary: str | None,
    aliases: list[str] | None,
    extra_tags: list[str] | None,
) -> dict[str, Any]:
    directory = glossary_dir(config)
    slug = slugify(term)
    path = ensure_within(config.vault_path, directory / f"{slug}.md")
    if path.exists():
        raise GlossaryError(f"Glossary entry already exists: {path.relative_to(config.vault_path)}")

    timestamp = now_iso()
    rendered_body = render_default_body(term, redact_secrets(body, config))
    frontmatter = {
        "title": term.strip(),
        "canonical_term": term.strip(),
        "summary": (summary or first_meaning_sentence(rendered_body)).strip(),
        "aliases": aliases or [],
        "created": timestamp,
        "updated": timestamp,
        "source_projects": [project_name],
        "tags": normalize_tags(config, project_name, extra_tags),
    }
    atomic_write(path, render_entry(frontmatter, rendered_body))
    regenerate_index(config)
    return {
        "path": str(path.relative_to(config.vault_path)),
        "title": term.strip(),
        "created": timestamp,
        "updated": timestamp,
        "index": str(index_path(config).relative_to(config.vault_path)),
    }


def append_body(existing_body: str, new_content: str) -> str:
    return core.append_body(existing_body, new_content)

def replace_section(existing_body: str, section: str, new_content: str) -> str:
    return core.replace_section(existing_body, section, new_content, GlossaryError)

def update_entry(
    config: Config,
    project_name: str,
    path_arg: str,
    mode: str,
    new_content: str,
    section: str | None,
    summary: str | None,
    aliases: list[str] | None,
    extra_tags: list[str] | None,
) -> dict[str, Any]:
    path = resolve_doc_path(config, path_arg)
    if not path.exists():
        raise GlossaryError(f"Glossary entry does not exist: {path_arg}")

    text = path.read_text()
    frontmatter, body = parse_frontmatter(text)
    if not frontmatter:
        raise GlossaryError(f"Glossary entry is missing expected frontmatter: {path}")

    redacted_content = redact_secrets(new_content, config)
    if mode == "append":
        updated_body = append_body(body, redacted_content)
    elif mode == "replace":
        if not section:
            raise GlossaryError("--section is required when mode is replace.")
        updated_body = replace_section(body, section, redacted_content)
    elif mode == "rewrite":
        updated_body = redacted_content
    else:
        raise GlossaryError(f"Unknown update mode: {mode}")

    existing_projects = normalize_list(frontmatter.get("source_projects"))
    if project_name not in existing_projects:
        existing_projects.append(project_name)
    existing_tags = normalize_list(frontmatter.get("tags"))
    for tag in normalize_tags(config, project_name, extra_tags):
        if tag not in existing_tags:
            existing_tags.append(tag)
    existing_aliases = normalize_list(frontmatter.get("aliases"))
    for alias in aliases or []:
        if alias and alias not in existing_aliases:
            existing_aliases.append(alias)

    frontmatter["updated"] = now_iso()
    frontmatter["summary"] = (summary or frontmatter.get("summary") or first_meaning_sentence(updated_body)).strip()
    frontmatter["aliases"] = existing_aliases
    frontmatter["source_projects"] = existing_projects
    frontmatter["tags"] = existing_tags
    if not frontmatter.get("canonical_term"):
        frontmatter["canonical_term"] = frontmatter.get("title") or path.stem.replace("-", " ")
    if not frontmatter.get("title"):
        frontmatter["title"] = frontmatter["canonical_term"]

    atomic_write(path, render_entry(frontmatter, updated_body))
    regenerate_index(config)
    return {
        "path": str(path.relative_to(config.vault_path)),
        "title": frontmatter.get("title"),
        "canonical_term": frontmatter.get("canonical_term"),
        "updated": frontmatter.get("updated"),
        "mode": mode,
        "section": section,
        "index": str(index_path(config).relative_to(config.vault_path)),
    }


def read_entry(config: Config, path_arg: str) -> str:
    path = resolve_doc_path(config, path_arg)
    if not path.exists():
        raise GlossaryError(f"Glossary entry does not exist: {path_arg}")
    return path.read_text()


def escape_table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def regenerate_index(config: Config) -> dict[str, Any]:
    entries = sorted(list_entries(config), key=lambda entry: entry.canonical_term.lower())
    lines = [
        "# Glossary Index",
        "",
        "| Term | Aliases | Summary | Updated |",
        "| --- | --- | --- | --- |",
    ]
    for entry in entries:
        link = f"[[{entry.path.stem}|{entry.canonical_term}]]"
        aliases = ", ".join(entry.aliases)
        updated = (entry.updated or "").split("T", 1)[0]
        lines.append(
            "| "
            + " | ".join(
                [
                    escape_table_cell(link),
                    escape_table_cell(aliases),
                    escape_table_cell(entry.summary),
                    escape_table_cell(updated),
                ]
            )
            + " |"
        )
    lines.append("")
    path = index_path(config)
    atomic_write(path, "\n".join(lines))
    return {
        "path": str(path.relative_to(config.vault_path)),
        "entries": len(entries),
    }


def can_write_directory(path: Path) -> bool:
    candidate = path if path.exists() else path.parent
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate.exists() and os.access(candidate, os.W_OK)


def doctor_payload(project_root: Path, project_name: str, config: Config) -> dict[str, Any]:
    directory = glossary_dir(config)
    idx_path = index_path(config)
    return {
        "project_root": str(project_root),
        "project": project_name,
        "config_sources": [str(path) for path in config_source_paths(project_root) if path.exists()],
        "vault_path": str(config.vault_path),
        "glossary_dir": config.glossary_dir,
        "glossary_path": str(directory),
        "glossary_exists": directory.exists(),
        "index_file": config.index_file,
        "index_path": str(idx_path),
        "index_exists": idx_path.exists(),
        "writes_possible": can_write_directory(directory),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage Hypatos glossary entries in Obsidian.")
    parser.add_argument("--project", help="Override the auto-detected source project name.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="List glossary entries.")
    scan_parser.add_argument("--query", help="Optional keywords to filter by title, term, alias, tag, or filename.")
    scan_parser.add_argument("--limit", type=int, help="Maximum number of entries to return.")

    read_parser = subparsers.add_parser("read", help="Read a glossary entry.")
    read_parser.add_argument("--path", required=True, help="Glossary entry path relative to the vault root.")

    create_parser = subparsers.add_parser("create", help="Create a new glossary entry.")
    create_parser.add_argument("--term", required=True, help="Canonical glossary term.")
    create_parser.add_argument("--summary", help="One-line summary used in the index.")
    create_parser.add_argument("--alias", action="append", dest="aliases", help="Alias for the canonical term.")
    create_parser.add_argument("--content", help="Inline markdown content.")
    create_parser.add_argument("--content-file", help="Path to a markdown file containing the body content.")
    create_parser.add_argument("--tag", action="append", dest="tags", help="Additional tag to add.")

    update_parser = subparsers.add_parser("update", help="Append to, replace a section in, or rewrite a glossary entry.")
    update_parser.add_argument("--path", required=True, help="Glossary entry path relative to the vault root.")
    update_parser.add_argument("--mode", required=True, choices=["append", "replace", "rewrite"], help="Update mode.")
    update_parser.add_argument("--section", help="Section heading to replace when using replace mode.")
    update_parser.add_argument("--summary", help="Updated one-line summary used in the index.")
    update_parser.add_argument("--alias", action="append", dest="aliases", help="Alias to add to the entry.")
    update_parser.add_argument("--content", help="Inline markdown content.")
    update_parser.add_argument("--content-file", help="Path to a markdown file containing the new content.")
    update_parser.add_argument("--tag", action="append", dest="tags", help="Additional tag to add.")

    subparsers.add_parser("index", help="Regenerate the glossary index.")
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
                "glossary": config.glossary_dir,
                "entries": scan_entries(config, args.query, args.limit),
            }
            print(json.dumps(payload, indent=2))
            return 0

        if args.command == "read":
            print(read_entry(config, args.path))
            return 0

        if args.command == "create":
            content = read_content_arg(args.content, args.content_file)
            payload = create_entry(config, project_name, args.term, content, args.summary, args.aliases, args.tags)
            print(json.dumps(payload, indent=2))
            return 0

        if args.command == "update":
            content = read_content_arg(args.content, args.content_file)
            payload = update_entry(
                config,
                project_name,
                args.path,
                args.mode,
                content,
                args.section,
                args.summary,
                args.aliases,
                args.tags,
            )
            print(json.dumps(payload, indent=2))
            return 0

        if args.command == "index":
            print(json.dumps(regenerate_index(config), indent=2))
            return 0

        if args.command == "doctor":
            print(json.dumps(doctor_payload(project_root, project_name, config), indent=2))
            return 0

        raise GlossaryError(f"Unknown command: {args.command}")
    except GlossaryError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
