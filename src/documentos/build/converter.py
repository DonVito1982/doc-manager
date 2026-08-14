"""Pandoc converter for the build pipeline.

Invokes Pandoc via ``pypandoc`` to transform preprocessed Markdown into
the output formats declared in ``config.yml`` (``html``, ``epub``, ``pdf``).

Uses Jinja2 templates for HTML layout and EPUB metadata.  LaTeX templates
are Pandoc-native (``.tex``) and resolved from the user project or the
packaged defaults.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import frontmatter as frontmatter_lib
import pypandoc
from jinja2 import (
    ChoiceLoader,
    Environment,
    FileSystemLoader,
    PackageLoader,
    TemplateNotFound,
)

from documentos.build.collector import SourceFile
from documentos.config import ProjectConfig

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ConvertedFile:
    """Result of converting a single source file to a single format.

    Attributes:
        source: Relative path of the original source file.
        format: Output format (``"html"``, ``"epub"``, ``"pdf"``).
        output: Relative path of the generated file.
        success: Whether the conversion completed without errors.
        error: Error message if *success* is ``False``.
    """

    source: Path
    format: str
    output: Path
    success: bool
    error: str | None = None


@dataclass
class BuildResult:
    """Aggregated results of a complete build run.

    Attributes:
        converted: All converted files (both successful and failed).
        errors: Global error messages (e.g. Pandoc not installed).
        warnings: Non-blocking warnings.
        output_dir: Output directory used.
    """

    converted: list[ConvertedFile] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    output_dir: Path = field(default_factory=Path)


# ---------------------------------------------------------------------------
# File extension mapping (source format → output extension)
# ---------------------------------------------------------------------------

_FORMAT_TO_OUTPUT_EXT: dict[str, str] = {
    "html": ".html",
    "epub": ".epub",
    "pdf": ".pdf",
    "tex": ".tex",
}

_FORMAT_TO_SUFFIX: dict[str, str] = {
    "md": ".md",
    "md.j2": ".md.j2",
    "ipynb": ".ipynb",
    "adoc": ".adoc",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def convert(
    source: SourceFile,
    config: ProjectConfig,
    preprocessed: str,
    all_documents: list[SourceFile] | None = None,
) -> list[ConvertedFile]:
    """Convert preprocessed Markdown to all configured output formats.

    For each format declared in ``config.output.formats`` the function
    invokes Pandoc (via ``pypandoc``) with the appropriate options and
    writes the output to ``config.root / config.output.dir / <format>``.

    The output directory structure mirrors the ``content/`` hierarchy
    (stripping the ``content/`` prefix from the source path).

    Args:
        source: The source file being converted.
        config: The project configuration.
        preprocessed: Preprocessed Markdown content ready for Pandoc.
        all_documents: Optional list of all collected source files, used
            to populate the sidebar in the HTML template.

    Returns:
        A list of ``ConvertedFile`` instances, one per output format.

    Raises:
        RuntimeError: If Pandoc is not installed.
    """
    try:
        pypandoc.get_pandoc_version()
    except OSError as exc:
        raise RuntimeError(
            "Pandoc is not installed or not found in PATH. "
            "Please install Pandoc: https://pandoc.org/installing.html"
        ) from exc

    results: list[ConvertedFile] = []

    # index.md files only generate HTML output
    formats = list(config.output.formats)
    if source.path.stem == "index":
        formats = ["html"]

    for fmt in formats:
        result = _convert_single(source, config, preprocessed, fmt, all_documents)
        results.append(result)

    return results


# ---------------------------------------------------------------------------
# Internal helpers — dispatch
# ---------------------------------------------------------------------------


def _convert_single(
    source: SourceFile,
    config: ProjectConfig,
    preprocessed: str,
    fmt: str,
    all_documents: list[SourceFile] | None = None,
) -> ConvertedFile:
    """Dispatch conversion to the appropriate format handler."""
    try:
        if fmt == "html":
            return _convert_to_html(source, config, preprocessed, all_documents)
        elif fmt == "epub":
            return _convert_to_epub(source, config, preprocessed)
        elif fmt == "pdf":
            return _convert_to_pdf(source, config, preprocessed)
        else:
            return ConvertedFile(
                source=source.path,
                format=fmt,
                output=Path(),
                success=False,
                error=f"Unsupported output format: {fmt}",
            )
    except Exception as exc:
        output_path = _make_output_path(source, config, fmt)
        logging.warning("Conversion failed for %s → %s: %s", source.path, fmt, exc)
        return ConvertedFile(
            source=source.path,
            format=fmt,
            output=output_path,
            success=False,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Internal helpers — output path
# ---------------------------------------------------------------------------


def _make_output_path(source: SourceFile, config: ProjectConfig, fmt: str) -> Path:
    """Compute the output path for a source file and format.

    The returned path is relative to the project root::

        <output_dir> / <fmt> / <relative_path_without_content_prefix>

    where the source file extension is replaced by the target format
    extension.

    Example::

        content/guia/instalacion.md.j2  →  output/html/guia/instalacion.html
    """
    relative = source.path
    if len(relative.parts) > 1 and relative.parts[0] == "content":
        relative = Path(*relative.parts[1:])

    suffix = _FORMAT_TO_SUFFIX.get(source.format, Path(source.path).suffix)
    name_without_suffix = (
        relative.name[: -len(suffix)]
        if relative.name.endswith(suffix)
        else relative.stem
    )
    target_ext = _FORMAT_TO_OUTPUT_EXT.get(fmt, f".{fmt}")

    if name_without_suffix:
        output_name = f"{name_without_suffix}{target_ext}"
    else:
        output_name = f"{relative.stem}{target_ext}"

    output_rel = relative.parent / output_name

    return Path(config.output.dir) / fmt / output_rel


# ---------------------------------------------------------------------------
# Internal helpers — Jinja2 environment
# ---------------------------------------------------------------------------


def _create_jinja_env(config: ProjectConfig) -> Environment:
    """Create a Jinja2 environment with template resolution.

    Templates are resolved in this order:
    1. User's project ``templates/`` directory (if it exists).
    2. Packaged templates inside ``documentos/templates/``.

    Args:
        config: The project configuration.

    Returns:
        A configured Jinja2 ``Environment``.
    """
    loaders: list = []

    user_templates = config.root / config.templates.dir
    if user_templates.is_dir():
        loaders.append(FileSystemLoader(str(user_templates)))

    loaders.append(PackageLoader("documentos", "templates"))

    return Environment(
        loader=ChoiceLoader(loaders),
        autoescape=True,
    )


# ---------------------------------------------------------------------------
# Internal helpers — template context
# ---------------------------------------------------------------------------


def _build_document_list(
    documents: list[SourceFile],
    config: ProjectConfig,
    current_source: SourceFile | None = None,
) -> list[dict[str, str]]:
    """Build a list of document dicts for template rendering.

    Each dict contains ``title`` (from frontmatter or filename),
    ``slug`` (relative HTML output path), and ``section`` (the section
    the document belongs to).

    When *current_source* is provided, slugs are computed relative to
    the current document's output directory so that sidebar links work
    correctly when rendered from deeply nested pages.

    Args:
        documents: List of collected source files.
        config: The project configuration.
        current_source: Optional source file being rendered, used to
            relativize sidebar link slugs.

    Returns:
        A list of dicts with ``title``, ``slug``, and ``section`` keys.
    """
    result: list[dict[str, str]] = []

    # Compute the current source's output parent directory
    # (relative to output/html/) so we can relativize all slugs.
    current_parent: Path | None = None
    if current_source is not None:
        current_slug_full = _make_output_path(current_source, config, "html")
        current_parent = (
            current_slug_full.relative_to(Path(config.output.dir) / "html")
        ).parent

    for doc in documents:
        title = doc.frontmatter.get("title", doc.path.stem)
        html_path = _make_output_path(doc, config, "html")
        slug = str(html_path.relative_to(Path(config.output.dir) / "html"))

        # Relativize the slug if we are inside a subdirectory.
        if current_parent is not None:
            slug = os.path.relpath(slug, str(current_parent))

        result.append({"title": str(title), "slug": slug, "section": doc.section})
    return result


def _build_section_structure(
    all_documents: list[SourceFile],
    config: ProjectConfig,
    current_source: SourceFile | None = None,
) -> list[dict]:
    """Group documents by section for the sidebar.

    For each section the optional ``_index.md`` file is read for a display
    title and weight.  Sections are sorted by weight, then title.

    When *current_source* is provided, document slugs are relativized to
    the current document's output directory so that sidebar links resolve
    correctly from deeply nested pages.

    Args:
        all_documents: List of all collected source files.
        config: The project configuration.
        current_source: Optional source file being rendered, used to
            relativize sidebar link slugs.

    Returns:
        A list of dicts with keys ``title`` (str), ``weight`` (int),
        ``key`` (str), ``documents`` (list of dicts with ``title``,
        ``slug``, ``section``).
    """
    # ------------------------------------------------------------
    # Group by section
    # ------------------------------------------------------------
    groups: dict[str, list[SourceFile]] = {}
    for doc in all_documents:
        sec = doc.section
        groups.setdefault(sec, []).append(doc)

    # ------------------------------------------------------------
    # Read _index.md metadata and build structure
    # ------------------------------------------------------------
    content_dir = config.root / "content"
    result: list[dict] = []

    for sec_key, docs in groups.items():
        # Read _index.md for section metadata
        meta: dict = {}
        section_dir = content_dir if sec_key == "" else content_dir / sec_key
        for name in ("_index.md", "_index.md.j2"):
            path = section_dir / name
            if path.is_file():
                try:
                    post = frontmatter_lib.load(str(path))
                    if post.metadata:
                        meta = dict(post.metadata)
                except Exception:
                    pass
                break

        title = meta.get("title", sec_key if sec_key else config.project.title)
        raw_weight = meta.get("weight")
        try:
            weight = (
                int(raw_weight)
                if raw_weight is not None
                else (0 if sec_key == "" else 999)
            )
        except (ValueError, TypeError):
            weight = 0 if sec_key == "" else 999

        # Convert docs to template format, sorted by title
        doc_list = _build_document_list(
            sorted(
                docs,
                key=lambda s: str(s.frontmatter.get("title", s.path.stem)).casefold(),
            ),
            config,
            current_source=current_source,
        )

        result.append(
            {
                "title": str(title),
                "weight": weight,
                "key": sec_key,
                "documents": doc_list,
            }
        )

    # Sort sections by weight, then title
    result.sort(key=lambda s: (s["weight"], str(s["title"]).casefold()))
    return result


def _build_html_context(
    source: SourceFile,
    config: ProjectConfig,
    all_documents: list[SourceFile] | None,
) -> dict:
    """Build the Jinja2 context for the HTML template.

    Args:
        source: The source file being converted.
        config: The project configuration.
        all_documents: Optional list of all collected source files.

    Returns:
        A dict with keys ``project``, ``title``, ``documents``,
        ``sections``, ``current_section``, ``section_title``,
        ``breadcrumbs``, ``assets``.
    """
    doc_list = (
        _build_document_list(all_documents, config, current_source=source)
        if all_documents
        else []
    )
    sections = (
        _build_section_structure(all_documents, config, current_source=source)
        if all_documents
        else []
    )

    # Determine section info for the current document
    current_section = source.section

    # Find section title for breadcrumbs
    section_title = ""
    for sec in sections:
        if sec.get("key") == current_section:
            section_title = str(sec["title"])
            break

    # Build breadcrumbs
    doc_slug = str(
        _make_output_path(source, config, "html").relative_to(
            Path(config.output.dir) / "html"
        )
    )
    # Compute depth: number of parent directories
    slug_parent = Path(doc_slug).parent
    if str(slug_parent) == ".":
        depth = 0
    else:
        depth = len(slug_parent.parts)

    root_index_rel = "../" * depth + "index.html" if depth > 0 else "index.html"

    breadcrumbs: list[dict[str, str]] = [
        {"title": "Inicio", "href": root_index_rel},
    ]

    if current_section != "":
        section_index_rel = "index.html"
        breadcrumbs.append({"title": section_title, "href": section_index_rel})

    # Assets prefix: relative path from current doc to output/html/assets/
    assets_prefix = "../" * depth

    # Add document title as last breadcrumb (no href — current page)
    doc_title = source.frontmatter.get("title", source.path.stem)
    breadcrumbs.append({"title": str(doc_title), "href": ""})

    # Build section_documents list for index.md files
    section_documents: list[dict[str, str]] = []
    if source.path.stem == "index":
        section_documents = [
            {"slug": doc["slug"], "title": doc["title"]}
            for doc in doc_list
            if doc.get("section") == current_section
        ]

    return {
        "project": {
            "title": config.project.title,
            "author": config.project.author,
            "language": config.project.language,
        },
        "title": source.frontmatter.get("title", source.path.stem),
        "body": "$body$",
        "documents": doc_list,
        "sections": sections,
        "current_section": current_section,
        "section_title": section_title,
        "breadcrumbs": breadcrumbs,
        "assets": f"{assets_prefix}assets",
        "section_documents": section_documents,
    }


# ---------------------------------------------------------------------------
# Internal helpers — math filter resolution
# ---------------------------------------------------------------------------


def _resolve_math_filter_path() -> str:
    """Resolve the absolute path to the Pandoc math filter script.

    Returns:
        Absolute path to ``math_filter.py`` packaged inside
        ``documentos/build/``.

    Raises:
        RuntimeError: If the filter script cannot be located.
    """
    import importlib.resources

    pkg = importlib.resources.files("documentos") / "build" / "math_filter.py"
    if not pkg.is_file():
        raise RuntimeError(
            "Packaged math filter not found at documentos/build/math_filter.py"
        )
    with importlib.resources.as_file(pkg) as filter_path:
        return str(filter_path)


# ---------------------------------------------------------------------------
# Internal helpers — HTML
# ---------------------------------------------------------------------------


def _convert_to_html(
    source: SourceFile,
    config: ProjectConfig,
    preprocessed: str,
    all_documents: list[SourceFile] | None = None,
) -> ConvertedFile:
    """Convert preprocessed Markdown to standalone HTML5 via Pandoc.

    Renders the ``base.html`` Jinja2 template (with ``$body$`` preserved
    for Pandoc replacement) and passes it to Pandoc via ``--template``.
    """
    output_path = _make_output_path(source, config, "html")
    full_output = config.root / output_path
    full_output.parent.mkdir(parents=True, exist_ok=True)

    math_filter_path = _resolve_math_filter_path()
    extra_args = ["--standalone", "--toc", f"--filter={math_filter_path}"]

    env = _create_jinja_env(config)
    context = _build_html_context(source, config, all_documents)

    frontmatter_template: str | None = source.frontmatter.get("template")

    # Detect index.md files → use index_default.html by default
    if source.path.stem == "index":
        template_name = frontmatter_template or "index_default.html"
    else:
        template_name = frontmatter_template or "base.html"

    try:
        rendered_template = env.get_template(template_name).render(**context)
    except TemplateNotFound:
        if frontmatter_template:
            logging.warning(
                "Template '%s' declared in frontmatter of %s not found in "
                "templates/. Falling back to default template.",
                frontmatter_template,
                source.path,
            )
        rendered_template = env.get_template("base.html").render(**context)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to render HTML template for {source.path}: {exc}"
        ) from exc

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", encoding="utf-8", delete=False
    ) as tmp_template:
        tmp_template.write(rendered_template)
        template_path = tmp_template.name

    try:
        extra_args.append(f"--template={template_path}")
        html = pypandoc.convert_text(
            preprocessed,
            "html5",
            format="markdown",
            extra_args=extra_args,
        )
    except RuntimeError as exc:
        raise RuntimeError(f"Failed to convert {source.path} to HTML: {exc}") from exc
    finally:
        Path(template_path).unlink(missing_ok=True)

    full_output.write_text(html, encoding="utf-8")

    return ConvertedFile(
        source=source.path,
        format="html",
        output=output_path,
        success=True,
    )


# ---------------------------------------------------------------------------
# Internal helpers — EPUB
# ---------------------------------------------------------------------------


def _convert_to_epub(
    source: SourceFile, config: ProjectConfig, preprocessed: str
) -> ConvertedFile:
    """Convert preprocessed Markdown to EPUB via Pandoc.

    Generates an ``epub-metadata.xml`` file from the Jinja2 template and
    passes it to Pandoc via ``--epub-metadata``.
    """
    output_path = _make_output_path(source, config, "epub")
    full_output = config.root / output_path
    full_output.parent.mkdir(parents=True, exist_ok=True)

    metadata_path = _generate_epub_metadata(config)
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", encoding="utf-8", delete=False
        ) as tmp_md:
            tmp_md.write(preprocessed)
            tmp_md_path = Path(tmp_md.name)

        try:
            pypandoc.convert_file(
                str(tmp_md_path),
                to="epub",
                format="markdown",
                outputfile=str(full_output),
                extra_args=[
                    "--toc",
                    f"--epub-metadata={metadata_path}",
                    f"--filter={_resolve_math_filter_path()}",
                ],
            )
        except RuntimeError as exc:
            raise RuntimeError(
                f"Failed to convert {source.path} to EPUB: {exc}"
            ) from exc
        finally:
            tmp_md_path.unlink(missing_ok=True)
    finally:
        metadata_path.unlink(missing_ok=True)

    return ConvertedFile(
        source=source.path,
        format="epub",
        output=output_path,
        success=True,
    )


# ---------------------------------------------------------------------------
# Internal helpers — LaTeX template resolution
# ---------------------------------------------------------------------------


def _resolve_latex_template_path(config: ProjectConfig) -> Path | None:
    """Resolve the LaTeX template path for Pandoc.

    Priority:
    1. ``config.pdf.template`` (if configured and the file exists).
    2. User's ``templates/latex-template.tex`` (if it exists).
    3. Packaged ``templates/latex-template.tex``.

    Args:
        config: The project configuration.

    Returns:
        Absolute path to the template file, or ``None`` if no template
        is found.
    """
    if config.pdf.template:
        candidate = config.root / config.pdf.template
        if candidate.is_file():
            return candidate

    user_template = config.root / config.templates.dir / "latex-template.tex"
    if user_template.is_file():
        return user_template

    import importlib.resources

    packaged = (
        importlib.resources.files("documentos") / "templates" / "latex-template.tex"
    )
    if packaged.is_file():
        with importlib.resources.as_file(packaged) as pkg_path:
            return Path(str(pkg_path))

    return None


# ---------------------------------------------------------------------------
# Internal helpers — PDF (two-step: Pandoc → LaTeX → latexmk)
# ---------------------------------------------------------------------------


def _convert_to_pdf(
    source: SourceFile, config: ProjectConfig, preprocessed: str
) -> ConvertedFile:
    """Convert preprocessed Markdown to PDF via Pandoc + LaTeX + latexmk.

    The conversion proceeds in two steps:

    1. Preprocessed Markdown is converted to LaTeX via Pandoc.
       The intermediate ``.tex`` file is saved to ``output/tex/`` for
       debugging and template inspection.
    2. The LaTeX file is compiled to PDF using ``latexmk -pdfxe``.

    If ``latexmk`` is not available a warning is emitted and the PDF is
    skipped without blocking other formats.
    """
    output_path = _make_output_path(source, config, "pdf")
    full_output = config.root / output_path
    full_output.parent.mkdir(parents=True, exist_ok=True)

    if shutil.which("latexmk") is None:
        logging.warning(
            "latexmk not found in PATH. Skipping PDF generation for %s. "
            "Install TeX Live and latexmk to enable PDF output: "
            "apt-get install texlive-xetex texlive-latex-extra latexmk",
            source.path,
        )
        return ConvertedFile(
            source=source.path,
            format="pdf",
            output=output_path,
            success=False,
            error="latexmk not installed — PDF generation skipped",
        )

    math_filter_path = _resolve_math_filter_path()
    latex_extra_args: list[str] = [
        "--standalone",
        f"--filter={math_filter_path}",
    ]

    pdf_template_name: str | None = source.frontmatter.get("pdf_template")
    template_path: Path | None = None

    if pdf_template_name:
        candidate = config.root / config.templates.dir / pdf_template_name
        if candidate.is_file():
            template_path = candidate
        else:
            logging.warning(
                "Template '%s' declared in frontmatter of %s not found in "
                "templates/. Falling back to default template.",
                pdf_template_name,
                source.path,
            )

    if template_path is None:
        template_path = _resolve_latex_template_path(config)

    if template_path is not None:
        latex_extra_args.append(f"--template={template_path}")

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tex", encoding="utf-8", delete=False
    ) as math_header_fh:
        math_header_fh.write(
            "\\usepackage{amsmath}\n\\usepackage{amssymb}\n\\usepackage{unicode-math}\n"
        )
        math_header_path = math_header_fh.name

    try:
        latex_extra_args.append(f"--include-in-header={math_header_path}")

        if config.pdf.header:
            latex_extra_args.append(f"--variable=header={config.pdf.header}")
        if config.pdf.footer:
            latex_extra_args.append(f"--variable=footer={config.pdf.footer}")
        latex_extra_args.append(f"--variable=mathfont={config.pdf.math_font}")

        latex_content = pypandoc.convert_text(
            preprocessed,
            "latex",
            format="markdown",
            extra_args=latex_extra_args,
        )
    except RuntimeError as exc:
        raise RuntimeError(f"Failed to convert {source.path} to LaTeX: {exc}") from exc
    finally:
        Path(math_header_path).unlink(missing_ok=True)

    tex_output_path = _make_output_path(source, config, "tex")
    tex_full_path = config.root / tex_output_path
    tex_full_path.parent.mkdir(parents=True, exist_ok=True)
    tex_full_path.write_text(latex_content, encoding="utf-8")

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_dir_path = Path(tmp_dir)
        tex_file = tmp_dir_path / f"{full_output.stem}.tex"
        tex_file.write_text(latex_content, encoding="utf-8")

        try:
            subprocess.run(
                [
                    "latexmk",
                    "-pdfxe",
                    "-interaction=nonstopmode",
                    str(tex_file),
                ],
                cwd=str(tmp_dir_path),
                capture_output=True,
                text=True,
                check=True,
                timeout=120,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"latexmk failed for {source.path}: {exc.stderr}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"latexmk timed out for {source.path}") from exc

        pdf_file = tmp_dir_path / f"{full_output.stem}.pdf"
        if not pdf_file.is_file():
            raise RuntimeError(f"latexmk did not produce a PDF for {source.path}")
        try:
            shutil.move(str(pdf_file), str(full_output))
        except OSError as exc:
            raise RuntimeError(f"Failed to move PDF for {source.path}: {exc}") from exc

    return ConvertedFile(
        source=source.path,
        format="pdf",
        output=output_path,
        success=True,
    )


# ---------------------------------------------------------------------------
# Internal helpers — EPUB metadata
# ---------------------------------------------------------------------------


def _generate_epub_metadata(config: ProjectConfig) -> Path:
    """Generate an ``epub-metadata.xml`` file from the Jinja2 template.

    The file is written to a temporary location and must be cleaned up by
    the caller.

    Args:
        config: The project configuration.

    Returns:
        Path to the generated temporary metadata XML file.
    """
    env = _create_jinja_env(config)
    context = {
        "project": {
            "title": config.project.title,
            "author": config.project.author,
            "language": config.project.language,
        },
    }

    try:
        rendered = env.get_template("epub-metadata.xml").render(**context)
    except Exception as exc:
        raise RuntimeError(f"Failed to render EPUB metadata template: {exc}") from exc

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".xml", encoding="utf-8", delete=False
    )
    try:
        tmp.write(rendered)
        return Path(tmp.name)
    finally:
        tmp.close()


def _escape_xml(text: str) -> str:
    """Escape special XML characters in *text*."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
