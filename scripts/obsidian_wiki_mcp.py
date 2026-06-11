#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import obsidian_wiki as wiki


@dataclass(frozen=True)
class WikiContext:
    project_root: Path
    config: wiki.Config
    project_name: str


def resolve_context(project: str | None = None, project_root: str | None = None) -> WikiContext:
    start = Path(project_root).expanduser().resolve() if project_root else Path.cwd()
    resolved_root = wiki.discover_project_root(start)
    config = wiki.resolve_config(resolved_root)
    project_name = project or wiki.detect_project_name(resolved_root)
    return WikiContext(project_root=resolved_root, config=config, project_name=project_name)


def scan_wiki(
    query: str | None = None,
    limit: int = wiki.MAX_SCAN_RESULTS,
    include_snippet: bool = False,
    include_archived: bool = False,
    project: str | None = None,
    project_root: str | None = None,
) -> dict[str, Any]:
    context = resolve_context(project, project_root)
    return {
        "project": context.project_name,
        "documents": wiki.scan_documents(
            context.config,
            context.project_name,
            query,
            limit,
            include_snippet,
            include_archived,
        ),
    }


def read_note(path: str, project_root: str | None = None) -> str:
    context = resolve_context(project_root=project_root)
    return wiki.read_document(context.config, path)


def create_note(
    title: str,
    content: str,
    tags: list[str] | None = None,
    project: str | None = None,
    project_root: str | None = None,
) -> dict[str, Any]:
    context = resolve_context(project, project_root)
    return wiki.create_document(context.config, context.project_name, title, content, tags)


def update_note(
    path: str,
    mode: Literal["append", "replace", "rewrite"],
    content: str,
    section: str | None = None,
    project: str | None = None,
    project_root: str | None = None,
) -> dict[str, Any]:
    context = resolve_context(project, project_root)
    return wiki.update_document(context.config, context.project_name, path, mode, content, section)


def add_frontmatter(
    path: str,
    title: str | None = None,
    tags: list[str] | None = None,
    project: str | None = None,
    project_root: str | None = None,
) -> dict[str, Any]:
    context = resolve_context(project, project_root)
    return wiki.add_frontmatter_to_document(context.config, context.project_name, path, title, tags)


def index_status(project_root: str | None = None) -> dict[str, Any]:
    context = resolve_context(project_root=project_root)
    return wiki.index_status(context.config)


def index_rebuild(project_root: str | None = None) -> dict[str, Any]:
    context = resolve_context(project_root=project_root)
    payload = wiki.rebuild_index(context.config)
    return {
        "path": str(wiki.index_path(context.config).relative_to(context.config.vault_path)),
        "documents": len(payload["documents"]),
        "generated": payload["generated"],
    }


def archive_candidates(
    older_than_days: int = 90,
    limit: int = wiki.MAX_SCAN_RESULTS,
    force: bool = False,
    global_scope: bool = False,
    project: str | None = None,
    project_root: str | None = None,
) -> dict[str, Any]:
    context = resolve_context(project, project_root)
    candidates = (
        wiki.archive_candidates_global(context.config, older_than_days, limit, force)
        if global_scope
        else wiki.archive_candidates(context.config, context.project_name, older_than_days, limit, force)
    )
    return {
        "scope": "global" if global_scope else "project",
        "project": None if global_scope else context.project_name,
        "candidates": candidates,
    }


def archive_apply(path: str, reason: str | None = None, project_root: str | None = None) -> dict[str, Any]:
    context = resolve_context(project_root=project_root)
    return wiki.archive_document(context.config, path, reason)


def archive_restore(path: str, project_root: str | None = None) -> dict[str, Any]:
    context = resolve_context(project_root=project_root)
    return wiki.restore_document(context.config, path)


def archive_cleanup(
    global_scope: bool = False,
    project: str | None = None,
    project_root: str | None = None,
) -> dict[str, Any]:
    context = resolve_context(project, project_root)
    return wiki.cleanup_empty_directories(context.config, context.project_name, global_scope)


def archive_status(project: str | None = None, project_root: str | None = None) -> dict[str, Any]:
    context = resolve_context(project, project_root)
    return wiki.archive_status(context.config, context.project_name)


def doctor(project: str | None = None, project_root: str | None = None) -> dict[str, Any]:
    context = resolve_context(project, project_root)
    return wiki.doctor_report(context.config, context.project_root, context.project_name)


def build_server() -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
    except ModuleNotFoundError as exc:
        raise RuntimeError("Missing dependency: install the Python MCP SDK with `pip install -r requirements.txt`.") from exc

    server = FastMCP("obsidian-wiki")
    server.tool()(scan_wiki)
    server.tool()(read_note)
    server.tool()(create_note)
    server.tool()(update_note)
    server.tool()(add_frontmatter)
    server.tool()(index_status)
    server.tool()(index_rebuild)
    server.tool()(archive_candidates)
    server.tool()(archive_apply)
    server.tool()(archive_restore)
    server.tool()(archive_cleanup)
    server.tool()(archive_status)
    server.tool()(doctor)
    return server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Obsidian Wiki MCP stdio server.")
    parser.add_argument("--check", action="store_true", help="Validate that the server can be constructed, then exit.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        server = build_server()
        if args.check:
            print(json.dumps({"ok": True, "server": "obsidian-wiki"}))
            return 0
        server.run()
        return 0
    except (RuntimeError, wiki.WikiError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
