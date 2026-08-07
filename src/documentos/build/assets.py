"""Asset management for the build pipeline.

Copies static assets (CSS, JavaScript, images, fonts) from the package and
the user's project into the output directory so the generated HTML can
reference them.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from documentos.build.collector import RECOGNIZED_SUFFIXES
from documentos.config import ProjectConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _should_skip(name: str) -> bool:
    """Return ``True`` if *name* starts with ``.`` or ``_``."""
    return name.startswith(".") or name.startswith("_")


def _is_source_file(name: str) -> bool:
    """Return ``True`` if *name* is a recognised source file (md, ipynb, ...)."""
    for suffix in RECOGNIZED_SUFFIXES:
        if name.endswith(suffix):
            return True
    return False


def _copy_tree_items(
    src: Path,
    dst: Path,
    *,
    rel_prefix: Path | None = None,
) -> list[Path]:
    """Recursively copy files from *src* to *dst*, skipping hidden items.

    Returns the list of destination ``Path`` objects relative to *dst*.
    """
    copied: list[Path] = []
    for item in src.rglob("*"):
        if not item.is_file():
            continue
        if any(_should_skip(part) for part in item.parts):
            continue
        rel = item.relative_to(src)
        dest = dst / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dest)
        entry = (rel_prefix / rel) if rel_prefix else rel
        copied.append(entry)
    return copied


# ---------------------------------------------------------------------------
# Package asset discovery
# ---------------------------------------------------------------------------


def _get_package_templates_dir() -> Path:
    """Return the absolute path to the bundled ``templates/`` directory."""
    return Path(__file__).resolve().parent.parent / "templates"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def copy_assets(config: ProjectConfig) -> list[Path]:
    """Copy static assets into the output directory.

    Copies, in order:

    1. Packaged CSS and JavaScript from the installed package.
    2. User assets from ``templates/assets/`` (overrides packaged files if
       names collide).
    3. Non-source files from ``content/`` (images, attachments — anything
       whose extension is not recognised by the collector).
    4. Any directories listed in ``config.assets.extra_dirs``.

    Files and directories whose name starts with ``.`` or ``_`` are ignored.

    Args:
        config: The project configuration.

    Returns:
        A list of ``Path`` entries (relative to ``output/html/``) for every
        file that was copied.
    """
    copied: list[Path] = []

    output_dir = config.root / config.output.dir / "html"
    output_dir.mkdir(parents=True, exist_ok=True)
    assets_output = output_dir / "assets"

    package_dir = _get_package_templates_dir()

    # 1 ─ Packaged CSS ------------------------------------------------------
    css_src = package_dir / "css"
    css_dst = assets_output / "css"
    if css_src.is_dir():
        css_dst.mkdir(parents=True, exist_ok=True)
        for item in css_src.iterdir():
            if item.is_file() and not _should_skip(item.name):
                shutil.copy2(item, css_dst / item.name)
                copied.append(Path("assets") / "css" / item.name)

    # 2 ─ Packaged JavaScript -----------------------------------------------
    js_src = package_dir / "js"
    js_dst = assets_output / "js"
    if js_src.is_dir():
        js_dst.mkdir(parents=True, exist_ok=True)
        for item in js_src.iterdir():
            if item.is_file() and not _should_skip(item.name):
                shutil.copy2(item, js_dst / item.name)
                copied.append(Path("assets") / "js" / item.name)

    # 3 ─ User assets (templates/assets/) ───────────────────────────────────
    user_assets_dir = config.root / config.templates.dir / "assets"
    if user_assets_dir.is_dir():
        for item in user_assets_dir.rglob("*"):
            if not item.is_file():
                continue
            if any(_should_skip(part) for part in item.parts):
                continue
            rel = item.relative_to(user_assets_dir)
            dest = assets_output / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)
            copied.append(Path("assets") / rel)

    # 4 ─ Non-source content files (images, attachments) ────────────────────
    content_dir = config.root / "content"
    if content_dir.is_dir():
        for item in content_dir.rglob("*"):
            if not item.is_file():
                continue
            if any(_should_skip(part) for part in item.parts):
                continue
            if _is_source_file(item.name):
                continue
            rel = item.relative_to(content_dir)
            dest = output_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)
            copied.append(rel)

    # 5 ─ Extra directories (config.assets.extra_dirs) ──────────────────────
    for extra in config.assets.extra_dirs:
        extra_path = config.root / extra
        if extra_path.is_dir():
            copied.extend(
                _copy_tree_items(extra_path, assets_output, rel_prefix=Path("assets"))
            )

    return copied
