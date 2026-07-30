"""Source file collection for the build pipeline.

Discovers all source files inside the ``content/`` directory and extracts
their metadata, leaving them ready for downstream processing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import frontmatter

from documentos.config import ProjectConfig

RECOGNIZED_SUFFIXES: dict[str, str] = {
    ".md.j2": "md.j2",
    ".md": "md",
    ".ipynb": "ipynb",
    ".adoc": "adoc",
}


@dataclass
class SourceFile:
    """Represents a source file discovered in the project.

    Attributes:
        path: Relative path from the project root.
        format: Detected file type (``"md"``, ``"md.j2"``, ``"ipynb"``,
            ``"adoc"``).
        frontmatter: Metadata extracted from the file (empty dict if none).
    """

    path: Path
    format: str
    frontmatter: dict


def _detect_format(file_path: Path) -> str | None:
    name = file_path.name
    for suffix, fmt in RECOGNIZED_SUFFIXES.items():
        if name.endswith(suffix):
            return fmt
    return None


def _parse_frontmatter_md(file_path: Path) -> dict:
    try:
        post = frontmatter.load(str(file_path))
        return dict(post.metadata) if post.metadata else {}
    except Exception:
        return {}


def _parse_frontmatter_ipynb(file_path: Path) -> dict:
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    result: dict = {}

    cells = data.get("cells", [])
    for cell in cells:
        if cell.get("cell_type") == "markdown":
            source = cell.get("source", [])
            if isinstance(source, list):
                text = "".join(source).strip()
            else:
                text = str(source).strip()
            if text:
                for line in text.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("# "):
                        result["title"] = stripped[2:].strip()
                        break
                if "title" not in result:
                    result["title"] = text.splitlines()[0].lstrip("#").strip()
                break

    metadata = data.get("metadata", {})
    author = metadata.get("author")
    if author:
        result["author"] = author

    return result


def _should_skip(name: str) -> bool:
    return name.startswith(".") or name.startswith("_")


def collect(config: ProjectConfig) -> list[SourceFile]:
    """Recursively collect source files from the ``content/`` directory.

    Recognised extensions: ``.md``, ``.md.j2``, ``.ipynb``, ``.adoc``.
    Files and directories whose name starts with ``.`` or ``_`` are ignored.

    Args:
        config: The project configuration (provides the project root).

    Returns:
        A list of ``SourceFile`` instances, sorted alphabetically by
        relative path.
    """
    content_dir = config.root / "content"
    if not content_dir.is_dir():
        return []

    result: list[SourceFile] = []

    for item_path in content_dir.rglob("*"):
        if not item_path.is_file():
            continue

        relative = item_path.relative_to(config.root)
        if any(_should_skip(part) for part in relative.parts):
            continue

        fmt = _detect_format(item_path)
        if fmt is None:
            continue

        if fmt in ("md", "md.j2"):
            fm = _parse_frontmatter_md(item_path)
        elif fmt == "ipynb":
            fm = _parse_frontmatter_ipynb(item_path)
        else:
            fm = {}

        result.append(SourceFile(path=relative, format=fmt, frontmatter=fm))

    result.sort(key=lambda sf: sf.path)
    return result
