"""Index generation for the build pipeline.

Creates per-section navigation pages under ``output/html/``.  Sections are
detected automatically from the ``content/`` directory structure (Hugo-style)
or defined explicitly via ``content/.index.yml`` for backward compatibility.
"""

from __future__ import annotations

from pathlib import Path

import frontmatter
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
) -> list[Path]:
    """Generate section-based navigation indices.

    If ``content/.index.yml`` exists, the sections and document ordering
    declared there are used (backward compatibility).  Otherwise sections
    are discovered automatically from the ``content/`` directory structure
    and per-section ``_index.md`` metadata.

    Args:
        sources: Collected source files to include in the indices.
        config: The project configuration.

    Returns:
        List of absolute paths to all generated ``index.html`` files.
    """
    index_yml = config.root / "content" / ".index.yml"

    if index_yml.is_file():
        return _generate_from_index_yml(sources, config, index_yml)

    sections = build_section_index(config, sources)
    return generate_section_pages(config, sections)


def build_section_index(
    config: ProjectConfig,
    sources: list[SourceFile],
) -> list[dict]:
    """Group source files by their ``section`` property and extract metadata.

    For each section the optional ``_index.md`` file is read to obtain a
    display ``title`` and ordering ``weight``.  When ``_index.md`` is missing
    the directory name is used as title and sections are ordered
    alphabetically.

    Args:
        config: The project configuration.
        sources: Collected source files.

    Returns:
        A list of dicts, each with keys ``key`` (str), ``title`` (str),
        ``weight`` (int), and ``documents`` (list of ``SourceFile``).
    """
    # ------------------------------------------------------------
    # Group sources by section
    # ------------------------------------------------------------
    sections_map: dict[str, list[SourceFile]] = {}
    for src in sources:
        sec = src.section
        sections_map.setdefault(sec, []).append(src)

    # When there are no sources, still return the root section with no docs
    if not sections_map:
        sections_map[""] = []

    # ------------------------------------------------------------
    # Read _index.md metadata for each section
    # ------------------------------------------------------------
    result: list[dict] = []
    for sec_key, docs in sections_map.items():
        meta = _parse_section_meta(config, sec_key)
        title = meta.get("title", sec_key if sec_key else config.project.title)
        weight = meta.get("weight")
        if weight is not None:
            try:
                weight = int(weight)
            except (ValueError, TypeError):
                weight = 999
        else:
            weight = 0 if sec_key == "" else 999

        result.append(
            {
                "key": sec_key,
                "title": str(title),
                "weight": weight,
                "documents": docs,
            }
        )

    # ------------------------------------------------------------
    # Sort sections by weight, then alphabetically by title
    # ------------------------------------------------------------
    result.sort(key=lambda s: (s["weight"], s["title"].casefold()))
    return result


def generate_section_pages(
    config: ProjectConfig,
    sections: list[dict],
) -> list[Path]:
    """Generate per-section ``index.html`` files.

    The root section (``key == ""``) produces ``output/html/index.html``.
    Other sections produce ``output/html/<key>/index.html``.  Documents are
    sorted alphabetically by frontmatter title within each section.

    If ``content/.index.yml`` exists it is consulted for per-document
    ordering within sections.

    Args:
        config: The project configuration.
        sections: Section definitions as returned by ``build_section_index``.

    Returns:
        List of absolute paths to all generated ``index.html`` files.
    """
    # Load .index.yml for ordering — applies to all sections
    index_yml = config.root / "content" / ".index.yml"
    yml_order: dict[str, int] = {}

    if index_yml.is_file():
        yml_sections = _parse_index_yml(index_yml)
        # Flatten all file references with their position
        for yml_sec in yml_sections:
            for idx, file_ref in enumerate(yml_sec.get("files", [])):
                yml_order[file_ref] = idx

    output_dir = config.root / config.output.dir / "html"
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []

    for section in sections:
        sec_key: str = section["key"]
        sec_title: str = section["title"]
        docs: list[SourceFile] = section["documents"]

        # Sort documents by .index.yml order or alphabetically by title
        if yml_order:
            docs = _sort_by_yml_order(docs, yml_order)
        else:
            docs = sorted(
                docs,
                key=lambda s: str(s.frontmatter.get("title", s.path.stem)).casefold(),
            )

        html = _render_section_page(
            section_title=sec_title,
            section_key=sec_key,
            documents=docs,
            config=config,
        )

        if sec_key == "":
            page_path = output_dir / "index.html"
        else:
            section_dir = output_dir / sec_key
            section_dir.mkdir(parents=True, exist_ok=True)
            page_path = section_dir / "index.html"

        page_path.write_text(html, encoding="utf-8")
        generated.append(page_path)

    return generated


# ---------------------------------------------------------------------------
# Internal — section metadata (via _index.md)
# ---------------------------------------------------------------------------


def _parse_section_meta(config: ProjectConfig, section: str) -> dict:
    """Parse ``_index.md`` (or ``_index.md.j2``) for section metadata.

    Args:
        config: The project configuration.
        section: Section key (``""`` for root).

    Returns:
        Dict with ``title`` and ``weight`` keys (both optional).
    """
    content_dir = config.root / "content"
    section_dir = content_dir if section == "" else content_dir / section

    for name in ("_index.md", "_index.md.j2"):
        path = section_dir / name
        if path.is_file():
            try:
                post = frontmatter.load(str(path))
                if post.metadata:
                    return dict(post.metadata)
            except Exception:
                pass
            break

    return {}


# ---------------------------------------------------------------------------
# Internal — .index.yml parsing (backward compatibility)
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
# Internal — .index.yml-based generation (backward compatibility)
# ---------------------------------------------------------------------------


def _generate_from_index_yml(
    sources: list[SourceFile],
    config: ProjectConfig,
    index_yml: Path,
) -> list[Path]:
    """Generate a single ``index.html`` using ``.index.yml`` section
    definitions (backward compatibility path)."""
    yml_sections = _parse_index_yml(index_yml)
    source_map: dict[str, SourceFile] = {str(s.path): s for s in sources}

    html = _render_yml_index(yml_sections, source_map, config)

    output_dir = config.root / config.output.dir / "html"
    output_dir.mkdir(parents=True, exist_ok=True)
    index_path = output_dir / "index.html"
    index_path.write_text(html, encoding="utf-8")
    return [index_path]


# ---------------------------------------------------------------------------
# Internal — document info helpers
# ---------------------------------------------------------------------------


def _build_doc_info(
    source: SourceFile,
    config: ProjectConfig,
    section_key: str = "",
) -> dict[str, str]:
    """Extract title and HTML link from a source file.

    The *section_key* is used to compute a relative ``href`` from the
    section's index page.  For the root section the href is the path
    relative to ``output/html/``.  For a sub-section the href is relative
    to ``output/html/<section>/``.

    Args:
        source: The source file.
        config: The project configuration.
        section_key: The section key (``""`` for root section).

    Returns:
        Dict with ``title`` and ``href`` keys.
    """
    title = source.frontmatter.get("title", source.path.stem)
    html_path = _make_output_path(source, config, "html")
    prefix = Path(config.output.dir) / "html"

    if section_key:
        # For sub-sections, link relative to section directory
        section_prefix = prefix / section_key
        href = str(html_path.relative_to(section_prefix))
    else:
        href = str(html_path.relative_to(prefix))

    return {"title": str(title), "href": href}


def _sort_by_yml_order(
    docs: list[SourceFile], yml_order: dict[str, int]
) -> list[SourceFile]:
    """Sort documents by their position in ``.index.yml``.

    Files not listed in *yml_order* appear at the end, sorted alphabetically.
    """
    return sorted(
        docs,
        key=lambda s: (
            yml_order.get(str(s.path), 999999),
            str(s.frontmatter.get("title", s.path.stem)).casefold(),
        ),
    )


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


def _render_section_page(
    section_title: str,
    section_key: str,
    documents: list[SourceFile],
    config: ProjectConfig,
) -> str:
    """Render a single section index page.

    For the root section the page title includes the project title.
    For sub-sections it includes both the section title and project title.
    """
    doc_infos = [_build_doc_info(d, config, section_key) for d in documents]

    if section_key == "":
        page_title = f"{config.project.title} — Índice"
    else:
        page_title = f"{section_title} — {config.project.title}"

    lines: list[str] = []
    lines.append(
        _HTML_HEADER.format(
            lang=config.project.language,
            title=page_title,
            css=_CSS,
        )
    )

    if section_key == "":
        lines.append(f"<h1>{_escape_html(config.project.title)}</h1>")
    else:
        lines.append(f"<h1>{_escape_html(section_title)}</h1>")
        lines.append(
            f'<p><a href="../index.html">'
            f"← Volver al índice de {_escape_html(config.project.title)}</a></p>"
        )

    if doc_infos:
        lines.append("<ul>")
        for doc in doc_infos:
            lines.append(
                f'<li><a href="{_escape_attr(doc["href"])}">'
                f"{_escape_html(doc['title'])}</a></li>"
            )
        lines.append("</ul>")
    else:
        lines.append("<p>No hay documentos en esta sección.</p>")

    lines.append(_HTML_FOOTER)
    return "\n".join(lines)


def _render_yml_index(
    sections: list[dict],
    source_map: dict[str, SourceFile],
    config: ProjectConfig,
) -> str:
    """Render a single index respecting explicit ``.index.yml`` sections."""
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
