from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


class ObsidianWorkError(Exception):
    pass


def load_json(path: Path, error_cls: type[Exception] = ObsidianWorkError) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise error_cls(f"Invalid JSON config at {path}: {exc}") from exc


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def discover_project_root(
    project_config_relative_paths: list[Path],
    start: Path | None = None,
) -> Path:
    candidate = (start or Path.cwd()).expanduser().resolve()

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=candidate,
            check=True,
            capture_output=True,
            text=True,
        )
        git_root = result.stdout.strip()
        if git_root:
            return Path(git_root).expanduser().resolve()
    except Exception:
        pass

    for path in [candidate, *candidate.parents]:
        has_project_config = any((path / config_path).exists() for config_path in project_config_relative_paths)
        if has_project_config or (path / ".git").exists():
            return path

    return candidate


def project_config_paths(project_root: Path, project_config_relative_paths: list[Path]) -> list[Path]:
    return [project_root / config_path for config_path in project_config_relative_paths]


def config_source_paths(
    skill_config_path: Path,
    project_root: Path,
    project_config_relative_paths: list[Path],
) -> list[Path]:
    sources = [skill_config_path]
    sources.extend(path for path in reversed(project_config_paths(project_root, project_config_relative_paths)) if path.exists())
    return sources


def now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def slugify(value: str, noun: str = "Value", error_cls: type[Exception] = ObsidianWorkError) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not slug:
        raise error_cls(f"{noun} must contain at least one alphanumeric character.")
    return slug


def detect_project_name(project_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        )
        remote = result.stdout.strip()
        if remote:
            remote = remote.rstrip("/")
            name = remote.rsplit("/", 1)[-1]
            if ":" in name:
                name = name.rsplit(":", 1)[-1]
            if name.endswith(".git"):
                name = name[:-4]
            name = name.strip()
            if name:
                return name
    except Exception:
        pass
    return project_root.name


def ensure_within(root: Path, target: Path, error_cls: type[Exception] = ObsidianWorkError) -> Path:
    root = root.expanduser().resolve()
    target = target.expanduser().resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise error_cls(f"Path {target} escapes the vault root {root}") from exc
    return target


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text

    parts = text.split("\n---\n", 1)
    if len(parts) != 2:
        return {}, text

    raw_frontmatter = parts[0][4:]
    body = parts[1]
    frontmatter: dict[str, Any] = {}
    current_key: str | None = None

    for line in raw_frontmatter.splitlines():
        if not line.strip():
            continue
        if line.startswith("  - ") and current_key:
            frontmatter.setdefault(current_key, []).append(line[4:].strip())
            continue
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        current_key = key
        if value == "":
            frontmatter[key] = []
        elif value.startswith("[") and value.endswith("]"):
            frontmatter[key] = [item.strip().strip('"').strip("'") for item in value[1:-1].split(",") if item.strip()]
        else:
            frontmatter[key] = value.strip('"').strip("'")

    return frontmatter, body


def format_frontmatter(data: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        elif isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def read_content_arg(
    content: str | None,
    content_file: str | None,
    error_cls: type[Exception] = ObsidianWorkError,
) -> str:
    if bool(content) == bool(content_file):
        raise error_cls("Provide exactly one of --content or --content-file.")
    if content_file:
        return Path(content_file).expanduser().read_text()
    return content or ""


def normalize_tags(default_tags: list[str], project_name: str, extra_tags: list[str] | None) -> list[str]:
    tags: list[str] = []
    for tag in [*default_tags, f"project/{project_name}", *(extra_tags or [])]:
        normalized = str(tag).strip().lstrip("#")
        if normalized and normalized not in tags:
            tags.append(normalized)
    return tags


def normalize_list(values: list[str] | str | None) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        return [values]
    return list(values)


def redact_secrets(text: str, enabled: bool, patterns: list[str]) -> str:
    if not enabled:
        return text

    redacted = text
    for key in patterns:
        escaped = re.escape(key)
        redacted = re.sub(
            rf"(?im)\b({escaped})\s*=\s*([^\s\n]+)",
            rf"\1=[REDACTED]",
            redacted,
        )

    redacted = re.sub(r"(?i)\b(Bearer)\s+[A-Za-z0-9._~+/=-]{12,}", r"\1 [REDACTED]", redacted)
    redacted = re.sub(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key)\b\s*[:=]\s*([^\s\n]+)", r"\1: [REDACTED]", redacted)
    redacted = re.sub(r"\b[a-f0-9]{32,}\b", "[REDACTED_HEX]", redacted)
    redacted = re.sub(r"\b[A-Za-z0-9+/]{40,}={0,2}\b", "[REDACTED_TOKEN]", redacted)
    return redacted


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, encoding="utf-8") as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def append_body(existing_body: str, new_content: str) -> str:
    existing = existing_body.rstrip()
    addition = new_content.strip()
    if not existing:
        return addition + "\n"
    if not addition:
        return existing + "\n"
    return existing + "\n\n" + addition + "\n"


def replace_section(
    existing_body: str,
    section: str,
    new_content: str,
    error_cls: type[Exception] = ObsidianWorkError,
) -> str:
    if not section:
        raise error_cls("--section is required for replace mode.")

    heading_pattern = re.compile(rf"^(?P<level>#+)\s+{re.escape(section)}\s*$", re.MULTILINE)
    match = heading_pattern.search(existing_body)
    normalized_content = new_content.strip()

    if not match:
        return append_body(existing_body, f"## {section}\n\n{normalized_content}")

    start = match.start()
    level = len(match.group("level"))
    next_heading_pattern = re.compile(rf"^#{{1,{level}}}\s+", re.MULTILINE)
    next_match = next_heading_pattern.search(existing_body, match.end())
    end = next_match.start() if next_match else len(existing_body)

    replacement = f"{match.group('level')} {section}\n\n{normalized_content}\n"
    return existing_body[:start].rstrip() + "\n\n" + replacement + existing_body[end:].lstrip("\n")
