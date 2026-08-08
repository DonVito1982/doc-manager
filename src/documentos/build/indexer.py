"""Index generation for the build pipeline.

Creates ``output/html/index.html`` — a navigation page listing all documents
with links to their HTML output.  Respects ``content/.index.yml`` ordering
when present; otherwise sorts alphabetically by frontmatter title.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from documentos.build.collector import SourceFile
from documentos.build.converter import _make_output_path
from documentos.config import ProjectConfig

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_index(
    sources: list[SourceFile],
    config: ProjectConfig,
) -> Path:
    """Generate the project navigation index at ``output/html/index.html``.

    If ``content/.index.yml`` exists the document order and section grouping
    declared there are respected.  Otherwise documents are listed
    alphabetically by their frontmatter title (falling back to the filename
    stem if no title exists).

    Args:
        sources: Collected source files to include in the index.
        config: The project configuration.

    Returns:
        Absolute path to the generated ``index.html`` file.
    """
    index_yml = config.root / "content" / ".index.yml"

    if index_yml.is_file():
        sections = _parse_index_yml(index_yml)
        html = _render_sectioned_index(sections, sources, config)
    else:
        html = _render_flat_index(sources, config)

    output_dir = config.root / config.output.dir / "html"
    output_dir.mkdir(parents=True, exist_ok=True)
    index_path = output_dir / "index.html"
    index_path.write_text(html, encoding="utf-8")
    return index_path


# ---------------------------------------------------------------------------
# Internal — index.yml parsing
# ---------------------------------------------------------------------------


def _parse_index_yml(path: Path) -> list[dict]:
    """Parse the ``.index.yml`` file into a list of section dicts.

    Each section has ``title`` and ``files`` keys.  Missing or empty
    sections are filtered out.
    """
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        return []

    if not isinstance(data, dict):
        return []

    raw_sections = data.get("sections", [])
    if not isinstance(raw_sections, list):
        return []

    result: list[dict] = []
    for sec in raw_sections:
        if not isinstance(sec, dict):
            continue
        title = sec.get("title", "")
        files = sec.get("files", [])
        if not isinstance(files, list):
            files = []
        if title and files:
            result.append({"title": str(title), "files": [str(f) for f in files]})
    return result


# ---------------------------------------------------------------------------
# Internal — document info helpers
# ---------------------------------------------------------------------------


def _build_doc_info(source: SourceFile, config: ProjectConfig) -> dict[str, str]:
    """Extract title and HTML link from a source file.

    Returns:
        Dict with ``title`` and ``href`` keys.
    """
    title = source.frontmatter.get("title", source.path.stem)
    html_path = _make_output_path(source, config, "html")
    prefix = Path(config.output.dir) / "html"
    href = str(html_path.relative_to(prefix))
    return {"title": str(title), "href": href}


def _sort_by_title(docs: list[dict[str, str]]) -> list[dict[str, str]]:
    """Sort a list of doc info dicts alphabetically by title (case-insensitive)."""
    return sorted(docs, key=lambda d: d["title"].casefold())


# ---------------------------------------------------------------------------
# Internal — HTML rendering
# ---------------------------------------------------------------------------


_CSS = """\
    body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        max-width: 800px; margin: 2rem auto; padding: 0 1rem;
        color: #333; line-height: 1.6;
    }
    h1 { border-bottom: 2px solid #e0e0e0; padding-bottom: 0.5rem; }
    h2 { color: #555; margin-top: 2rem; }
    ul { padding-left: 1.5rem; }
    li { margin: 0.3rem 0; }
    a { color: #0366d6; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .footer {
        margin-top: 3rem; padding-top: 1rem;
        border-top: 1px solid #e0e0e0; color: #888; font-size: 0.9rem;
    }
"""

_HTML_HEADER = """\
<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
{css}</style>
</head>
<body>
"""

_HTML_FOOTER = """\
<div class="footer">
<p>Generado por documentos — gestor de documentación para firmas de ingeniería.</p>
</div>
</body>
</html>
"""


def _render_flat_index(
    sources: list[SourceFile],
    config: ProjectConfig,
) -> str:
    """Render an index with documents sorted alphabetically by title."""
    docs = _sort_by_title([_build_doc_info(s, config) for s in sources])
    lines: list[str] = []
    lines.append(
        _HTML_HEADER.format(
            lang=config.project.language,
            title=f"{config.project.title} — Índice",
            css=_CSS,
        )
    )
    lines.append(f"<h1>{_escape_html(config.project.title)}</h1>")

    if docs:
        lines.append("<ul>")
        for doc in docs:
            lines.append(
                f'<li><a href="{_escape_attr(doc["href"])}">'
                f"{_escape_html(doc['title'])}</a></li>"
            )
        lines.append("</ul>")
    else:
        lines.append("<p>No hay documentos.</p>")

    lines.append(_HTML_FOOTER)
    return "\n".join(lines)


def _render_sectioned_index(
    sections: list[dict],
    sources: list[SourceFile],
    config: ProjectConfig,
) -> str:
    """Render an index respecting explicit ``.index.yml`` sections."""
    source_map: dict[str, SourceFile] = {str(s.path): s for s in sources}

    lines: list[str] = []
    lines.append(
        _HTML_HEADER.format(
            lang=config.project.language,
            title=f"{config.project.title} — Índice",
            css=_CSS,
        )
    )
    lines.append(f"<h1>{_escape_html(config.project.title)}</h1>")

    for section in sections:
        lines.append(f"<h2>{_escape_html(section['title'])}</h2>")
        lines.append("<ul>")
        for file_ref in section["files"]:
            source = source_map.get(file_ref)
            if source is None:
                continue
            doc = _build_doc_info(source, config)
            lines.append(
                f'<li><a href="{_escape_attr(doc["href"])}">'
                f"{_escape_html(doc['title'])}</a></li>"
            )
        lines.append("</ul>")

    lines.append(_HTML_FOOTER)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal — HTML escaping
# ---------------------------------------------------------------------------


def _escape_html(text: str) -> str:
    """Escape reserved HTML characters in *text*."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _escape_attr(text: str) -> str:
    """Escape a string for use in an HTML attribute value."""
    return _escape_html(text)
