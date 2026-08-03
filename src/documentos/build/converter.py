"""Pandoc converter for the build pipeline.

Invokes Pandoc via ``pypandoc`` to transform preprocessed Markdown into
the output formats declared in ``config.yml`` (``html``, ``epub``, ``pdf``).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pypandoc

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
    source: SourceFile, config: ProjectConfig, preprocessed: str
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

    Returns:
        A list of ``ConvertedFile`` instances, one per output format.

    Raises:
        RuntimeError: If Pandoc is not installed.
    """
    # Verify Pandoc is available -------------------------------------------------
    try:
        pypandoc.get_pandoc_version()
    except OSError as exc:
        raise RuntimeError(
            "Pandoc is not installed or not found in PATH. "
            "Please install Pandoc: https://pandoc.org/installing.html"
        ) from exc

    results: list[ConvertedFile] = []

    for fmt in config.output.formats:
        result = _convert_single(source, config, preprocessed, fmt)
        results.append(result)

    return results


# ---------------------------------------------------------------------------
# Internal helpers — dispatch
# ---------------------------------------------------------------------------


def _convert_single(
    source: SourceFile, config: ProjectConfig, preprocessed: str, fmt: str
) -> ConvertedFile:
    """Dispatch conversion to the appropriate format handler."""
    try:
        if fmt == "html":
            return _convert_to_html(source, config, preprocessed)
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
    # Strip "content/" prefix if present
    if len(relative.parts) > 1 and relative.parts[0] == "content":
        relative = Path(*relative.parts[1:])

    # Replace the source format suffix with the target output extension
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
# Internal helpers — HTML
# ---------------------------------------------------------------------------


def _convert_to_html(
    source: SourceFile, config: ProjectConfig, preprocessed: str
) -> ConvertedFile:
    """Convert preprocessed Markdown to standalone HTML5 via Pandoc.

    Uses ``pypandoc.convert_text()`` with ``--standalone`` and ``--toc``.
    If a Pandoc HTML template exists in the project templates directory it
    is passed via ``--template``.
    """
    output_path = _make_output_path(source, config, "html")
    full_output = config.root / output_path
    full_output.parent.mkdir(parents=True, exist_ok=True)

    extra_args = ["--standalone", "--toc"]

    # Check for user-provided HTML template
    templates_dir = config.root / config.templates.dir
    html_template = templates_dir / "pandoc.html"
    if html_template.is_file():
        extra_args.append(f"--template={html_template}")

    try:
        html = pypandoc.convert_text(
            preprocessed,
            "html5",
            format="markdown",
            extra_args=extra_args,
        )
    except RuntimeError as exc:
        raise RuntimeError(f"Failed to convert {source.path} to HTML: {exc}") from exc

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

    Generates an ``epub-metadata.xml`` file from the project configuration
    and passes it to Pandoc via ``--epub-metadata``.
    """
    output_path = _make_output_path(source, config, "epub")
    full_output = config.root / output_path
    full_output.parent.mkdir(parents=True, exist_ok=True)

    metadata_path = _generate_epub_metadata(config)
    try:
        # Write the preprocessed Markdown to a temp file for convert_file
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
                extra_args=["--toc", f"--epub-metadata={metadata_path}"],
            )
        except RuntimeError as exc:
            raise RuntimeError(
                f"Failed to convert {source.path} to EPUB: {exc}"
            ) from exc
        finally:
            tmp_md_path.unlink(missing_ok=True)
    finally:
        # Clean up the temporary metadata file
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


def _resolve_latex_template(
    config: ProjectConfig, extra_args: list[str]
) -> None:
    """Resolve the LaTeX template path and append ``--template`` to *extra_args*.

    Priority:
    1. ``config.pdf.template`` (if configured and the file exists).
    2. ``templates/pandoc.latex`` (if it exists).
    """
    if config.pdf.template:
        candidate = config.root / config.pdf.template
        if candidate.is_file():
            extra_args.append(f"--template={candidate}")
            return

    default_template = config.root / config.templates.dir / "pandoc.latex"
    if default_template.is_file():
        extra_args.append(f"--template={default_template}")


# ---------------------------------------------------------------------------
# Internal helpers — PDF (two-step: Pandoc → LaTeX → latexmk)
# ---------------------------------------------------------------------------


def _convert_to_pdf(
    source: SourceFile, config: ProjectConfig, preprocessed: str
) -> ConvertedFile:
    """Convert preprocessed Markdown to PDF via Pandoc + LaTeX + latexmk.

    The conversion proceeds in two steps:

    1. Preprocessed Markdown is converted to LaTeX via Pandoc.
    2. The LaTeX file is compiled to PDF using ``latexmk -pdfxe``.

    If ``latexmk`` is not available a warning is emitted and the PDF is
    skipped without blocking other formats.
    """
    output_path = _make_output_path(source, config, "pdf")
    full_output = config.root / output_path
    full_output.parent.mkdir(parents=True, exist_ok=True)

    # Check for latexmk availability
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

    # Step 1: Convert Markdown to LaTeX ------------------------------------------
    latex_extra_args: list[str] = ["--standalone"]

    # Determine LaTeX template: config.pdf.template has highest priority,
    # falling back to templates/pandoc.latex
    _resolve_latex_template(config, latex_extra_args)

    # Math packages via --include-in-header (must be a file path, not raw text)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tex", encoding="utf-8", delete=False
    ) as math_header_fh:
        math_header_fh.write(
            "\\usepackage{amsmath}\n"
            "\\usepackage{amssymb}\n"
            "\\usepackage{unicode-math}\n"
        )
        math_header_path = math_header_fh.name

    try:
        latex_extra_args.append(f"--include-in-header={math_header_path}")

        # Header/footer variables from config.pdf
        if config.pdf.header:
            latex_extra_args.append(f"--variable=header={config.pdf.header}")
        if config.pdf.footer:
            latex_extra_args.append(f"--variable=footer={config.pdf.footer}")

        latex_content = pypandoc.convert_text(
            preprocessed,
            "latex",
            format="markdown",
            extra_args=latex_extra_args,
        )
    except RuntimeError as exc:
        raise RuntimeError(
            f"Failed to convert {source.path} to LaTeX: {exc}"
        ) from exc
    finally:
        Path(math_header_path).unlink(missing_ok=True)

    # Step 2: Compile LaTeX to PDF via latexmk -----------------------------------
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

        # Move the generated PDF to the output location
        pdf_file = tmp_dir_path / f"{full_output.stem}.pdf"
        if not pdf_file.is_file():
            raise RuntimeError(f"latexmk did not produce a PDF for {source.path}")
        try:
            shutil.move(str(pdf_file), str(full_output))
        except OSError as exc:
            raise RuntimeError(
                f"Failed to move PDF for {source.path}: {exc}"
            ) from exc

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
    """Generate an ``epub-metadata.xml`` file from project configuration.

    The file is written to a temporary location and must be cleaned up by
    the caller.

    Args:
        config: The project configuration.

    Returns:
        Path to the generated temporary metadata XML file.
    """
    metadata_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f"  <dc:title>{_escape_xml(config.project.title)}</dc:title>\n"
        f"  <dc:creator>{_escape_xml(config.project.author)}</dc:creator>\n"
        f"  <dc:language>{_escape_xml(config.project.language)}</dc:language>\n"
        "</metadata>\n"
    )

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".xml", encoding="utf-8", delete=False
    )
    try:
        tmp.write(metadata_xml)
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
