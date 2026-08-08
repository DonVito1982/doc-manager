"""Source file collection for the build pipeline.

Discovers all source files inside the ``content/`` directory and extracts
their metadata, leaving them ready for downstream processing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
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
    frontmatter: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def section(self) -> str:
        """Return the section name derived from the source path.

        Files directly in ``content/`` belong to the root section (empty
        string).  Files in a first-level subdirectory of ``content/`` return
        that subdirectory name.  Deeply nested files still return only the
        first-level subdirectory name (Hugo-style sections).

        Examples:
            ``content/index.md`` → ``""``
            ``content/guias/instalacion.md`` → ``"guias"``
            ``content/guias/sub/deep.md`` → ``"guias"``
        """
        parts = self.path.parts
        if parts and parts[0] == "content" and len(parts) > 2:
            return parts[1]
        return ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def should_skip(name: str) -> bool:
        """Check whether a file or directory name should be ignored.

        Files and directories whose name starts with ``.`` or ``_`` are
        considered drafts or hidden and are excluded from collection.
        """
        return name.startswith(".") or name.startswith("_")

    @classmethod
    def detect_format(cls, file_path: Path) -> str | None:
        """Detect the source format of a file based on its extension.

        Args:
            file_path: Filesystem path whose name is inspected.

        Returns:
            One of ``"md"``, ``"md.j2"``, ``"ipynb"``, ``"adoc"``, or
            ``None`` for unrecognised extensions.
        """
        name = file_path.name
        for suffix, fmt in RECOGNIZED_SUFFIXES.items():
            if name.endswith(suffix):
                return fmt
        return None

    def parse_frontmatter(self, root: Path) -> None:
        """Parse frontmatter from the filesystem and update
        ``self.frontmatter``.

        Parsing strategy depends on ``self.format``:

        - ``"md"`` / ``"md.j2"``: YAML frontmatter via ``python-frontmatter``.
        - ``"ipynb"``: title from the first markdown cell, author from
          notebook metadata.
        - ``"adoc"``: empty dict (AsciiDoc attribute parsing deferred).

        Args:
            root: Absolute path to the project root directory.  The
                concrete file path is resolved as ``root / self.path``.
        """
        file_path = root / self.path
        if self.format in ("md", "md.j2"):
            self.frontmatter = _parse_frontmatter_md(file_path)
        elif self.format == "ipynb":
            self.frontmatter = _parse_frontmatter_ipynb(file_path)
        else:
            self.frontmatter = {}


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


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


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


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
        if any(SourceFile.should_skip(part) for part in relative.parts):
            continue

        fmt = SourceFile.detect_format(item_path)
        if fmt is None:
            continue

        sf = SourceFile(path=relative, format=fmt)
        sf.parse_frontmatter(config.root)
        result.append(sf)

    result.sort(key=lambda sf: sf.path)
    return result
