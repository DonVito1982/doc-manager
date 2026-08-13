"""Index generation for the build pipeline.

Creates per-section navigation pages under ``output/html/``.  Sections are
detected automatically from the ``content/`` directory structure (Hugo-style)
or defined explicitly via ``content/.index.yml`` for backward compatibility.

When a section has an ``index.md`` (or ``index.md.j2``) file, the converter
handles index page generation — the indexer skips that section entirely.
Sections without an ``index.md`` are rendered using the Jinja2
``index_default.html`` template.
"""

from __future__ import annotations

from pathlib import Path

import frontmatter
import yaml

from documentos.build.collector import SourceFile
from documentos.build.converter import (
    _create_jinja_env,
    _make_output_path,
)
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
        result = _generate_from_index_yml(sources, config, index_yml)
        if result:
            return result
        # Fall back to section-based when .index.yml yields nothing

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
    """Generate per-section ``index.html`` files using Jinja2 templates.

    Sections that already have an ``index.md`` (or ``index.md.j2``) file on
    disk are **skipped** — the converter handles those via the
    ``index_default.html`` template.

    For sections **without** an ``index.md``, the ``index_default.html``
    template is rendered with ``body`` empty and ``section_documents``
    populated from the section's document list.

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

    env = _create_jinja_env(config)
    content_dir = config.root / "content"

    for section in sections:
        sec_key: str = section["key"]
        docs: list[SourceFile] = section["documents"]

        # --------------------------------------------------------
        # Check whether this section has its own index.md → skip
        # --------------------------------------------------------
        section_dir = content_dir if sec_key == "" else content_dir / sec_key
        has_index_md = any(
            (section_dir / name).is_file() for name in ("index.md", "index.md.j2")
        )
        if has_index_md:
            continue

        # Sort documents by .index.yml order or alphabetically by title
        if yml_order:
            docs = _sort_by_yml_order(docs, yml_order)
        else:
            docs = sorted(
                docs,
                key=lambda s: str(s.frontmatter.get("title", s.path.stem)).casefold(),
            )

        # Build context for Jinja2
        context = _build_index_context(config, section, docs, sections)

        try:
            rendered = env.get_template("index_default.html").render(**context)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to render index for section '{sec_key}': {exc}"
            ) from exc

        if sec_key == "":
            page_path = output_dir / "index.html"
        else:
            section_output_dir = output_dir / sec_key
            section_output_dir.mkdir(parents=True, exist_ok=True)
            page_path = section_output_dir / "index.html"

        page_path.write_text(rendered, encoding="utf-8")
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
    """Generate section-based pages using ``.index.yml`` section definitions.

    Uses Jinja2 ``index_default.html`` template for consistent output.
    """
    yml_sections = _parse_index_yml(index_yml)
    source_map: dict[str, SourceFile] = {str(s.path): s for s in sources}

    env = _create_jinja_env(config)
    output_dir = config.root / config.output.dir / "html"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Accumulate all documents across all YML sections
    all_docs: list[SourceFile] = []
    for yml_sec in yml_sections:
        for file_ref in yml_sec["files"]:
            src = source_map.get(file_ref)
            if src is not None:
                all_docs.append(src)

    if not all_docs:
        return []

    doc_infos = [_build_doc_info(d, config) for d in all_docs]

    context = {
        "project": {
            "title": config.project.title,
            "author": config.project.author,
            "language": config.project.language,
        },
        "title": f"{config.project.title} — Índice",
        "body": "",
        "documents": doc_infos,
        "sections": [],
        "assets": "assets",
        "breadcrumbs": [
            {"title": "Inicio", "href": "index.html"},
            {"title": f"{config.project.title} — Índice", "href": ""},
        ],
        "section_documents": doc_infos,
    }

    try:
        rendered = env.get_template("index_default.html").render(**context)
    except Exception as exc:
        raise RuntimeError(f"Failed to render .index.yml index: {exc}") from exc

    index_path = output_dir / "index.html"
    index_path.write_text(rendered, encoding="utf-8")
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

    Cross-section references are correctly relativized using
    ``os.path.relpath``.

    Args:
        source: The source file.
        config: The project configuration.
        section_key: The section key (``""`` for root section).

    Returns:
        Dict with ``title`` and ``href`` keys.
    """
    import os

    title = source.frontmatter.get("title", source.path.stem)
    html_path = _make_output_path(source, config, "html")
    prefix = Path(config.output.dir) / "html"

    if section_key:
        # For sub-sections, compute relative from section directory
        section_index_dir = prefix / section_key
        href = os.path.relpath(str(html_path), str(section_index_dir))
    else:
        href = str(html_path.relative_to(prefix))

    return {"title": str(title), "href": href}


def _build_doc_slug_info(
    source: SourceFile,
    config: ProjectConfig,
    section_key: str = "",
) -> dict[str, str]:
    """Extract title and slug from a source file for template context.

    Similar to ``_build_doc_info`` but returns ``slug`` key instead of
    ``href`` (for consistency with the converter's template context).

    Args:
        source: The source file.
        config: The project configuration.
        section_key: The section key (``""`` for root section).

    Returns:
        Dict with ``title`` and ``slug`` keys.
    """
    info = _build_doc_info(source, config, section_key)
    return {"title": info["title"], "slug": info["href"]}


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
# Internal — Jinja2 context builder for index pages
# ---------------------------------------------------------------------------


def _build_index_context(
    config: ProjectConfig,
    section: dict,
    docs: list[SourceFile],
    all_sections: list[dict],
) -> dict:
    """Build the Jinja2 context for an index page.

    Args:
        config: The project configuration.
        section: Section dict with keys ``key``, ``title``, ``weight``,
            ``documents``.
        docs: Pre-sorted documents for this section.
        all_sections: All section definitions (for sidebar).

    Returns:
        A dict suitable for rendering ``index_default.html``.
    """
    sec_key: str = section["key"]
    sec_title: str = section["title"]

    # Build document list with slugs relative to the index page location
    doc_infos: list[dict[str, str]] = []
    for doc in docs:
        info = _build_doc_slug_info(doc, config, sec_key)
        doc_infos.append(info)

    # Depth for assets and root index link
    depth = 0 if sec_key == "" else 1
    root_index_rel = "../" * depth + "index.html" if depth > 0 else "index.html"

    # Breadcrumbs
    breadcrumbs: list[dict[str, str]] = [
        {"title": "Inicio", "href": root_index_rel},
    ]
    if sec_key:
        breadcrumbs.append({"title": sec_title, "href": ""})

    # Build minimal section structure for sidebar.
    # Use the same document ordering as the main section_documents list
    # for consistency (alphabetical or YML order).
    sections_ctx: list[dict] = []
    for s in all_sections:
        s_key: str = s["key"]
        # Use pre-sorted docs if this is the current section, otherwise
        # sort alphabetically (the typical case for multi-section projects).
        if s_key == sec_key:
            sorted_sdocs = docs
        else:
            sorted_sdocs = sorted(
                s["documents"],
                key=lambda sd: str(
                    sd.frontmatter.get("title", sd.path.stem)
                ).casefold(),
            )
        section_doc_infos: list[dict[str, str]] = []
        for sdoc in sorted_sdocs:
            info = _build_doc_slug_info(sdoc, config, sec_key)
            section_doc_infos.append(info)
        sections_ctx.append(
            {
                "title": s["title"],
                "weight": s["weight"],
                "key": s_key,
                "documents": section_doc_infos,
            }
        )

    return {
        "project": {
            "title": config.project.title,
            "author": config.project.author,
            "language": config.project.language,
        },
        "title": sec_title if sec_key else config.project.title,
        "body": "",
        "documents": doc_infos,
        "sections": sections_ctx,
        "assets": "../" * depth + "assets" if depth > 0 else "assets",
        "breadcrumbs": breadcrumbs,
        "section_documents": doc_infos,
    }


# ---------------------------------------------------------------------------
# Internal — HTML escaping (kept for backward compatibility)
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
