"""Preprocessor for Jinja2 templates in the build pipeline.

Handles loading external data files (CSV, JSON, YAML, XML) and executing
SQLite queries, then injects those datasets into Jinja2 templates found
among the collected source files.
"""

from __future__ import annotations

import csv
import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

import yaml
from jinja2 import Environment, StrictUndefined

from documentos.build.collector import SourceFile
from documentos.config import ProjectConfig

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_DATA_EXTENSIONS: frozenset[str] = frozenset({".csv", ".json", ".yml", ".xml"})

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DataContext:
    """Encapsulates all data available for injection into templates.

    Attributes:
        project: Project metadata (title, author, language) from config.
        data: Dictionary of data loaded from the ``data/`` directory.
        db: Dictionary of SQLite query results keyed by alias.
    """

    project: dict = field(default_factory=dict)
    data: dict = field(default_factory=dict)
    db: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_data_files(config: ProjectConfig) -> dict:
    """Load data files from the configured ``data/`` directory.

    Reads files with supported extensions:

    - ``.csv`` → ``list[dict]`` via ``csv.DictReader``.
    - ``.json`` → ``dict | list`` via ``json.load``.
    - ``.yml`` → ``dict | list`` via ``yaml.safe_load``.
    - ``.xml`` → ``dict`` via ``xml.etree.ElementTree``.

    Files whose name starts with ``.`` or ``_`` are ignored.  A warning is
    emitted for files with unrecognised extensions.

    Args:
        config: The project configuration.

    Returns:
        A dictionary mapping each file's basename (without extension) to
        its parsed content.  Returns an empty dict if the directory does
        not exist or contains no supported files.
    """
    data_dir = config.root / config.data.dir
    if not data_dir.is_dir():
        return {}

    result: dict = {}
    for item_path in sorted(data_dir.iterdir()):
        if not item_path.is_file():
            continue
        name = item_path.name
        if name.startswith(".") or name.startswith("_"):
            continue

        suffix = item_path.suffix.lower()
        if suffix not in VALID_DATA_EXTENSIONS:
            logging.warning(
                "Unrecognised file extension '%s' in data directory. "
                "File '%s' will be ignored.",
                suffix,
                item_path,
            )
            continue

        key = item_path.stem
        try:
            result[key] = _parse_data_file(item_path, suffix)
        except Exception as exc:
            logging.warning("Failed to parse data file '%s': %s", item_path, exc)

    return result


def preprocess(source: SourceFile, context: DataContext) -> str:
    """Process a source file through the Jinja2 preprocessor.

    If *source.format* is ``"md.j2"``, the file is loaded as a Jinja2
    template and rendered with the variables from *context*.  The
    following variables are available inside templates:

    - ``project`` — project metadata (from ``context.project``).
    - ``data`` — external data files (from ``context.data``).
    - ``db`` — SQLite query results (from ``context.db``).
    - ``current`` — frontmatter of the current source file.

    If *source.format* is anything else, the raw file content is returned
    unchanged.

    Args:
        source: The source file to process.
        context: The data context to inject into the template.

    Returns:
        The rendered Markdown text (or raw content for non-Jinja2 files).

    Raises:
        jinja2.TemplateSyntaxError: If the Jinja2 template contains a
            syntax error (propagated from Jinja2).
        jinja2.UndefinedError: If the template references an undefined
            variable (propagated from Jinja2).
    """
    if source.format != "md.j2":
        return source.path.read_text(encoding="utf-8")

    template_text = source.path.read_text(encoding="utf-8")
    jinja_env = Environment(undefined=StrictUndefined, keep_trailing_newline=True)
    template = jinja_env.from_string(template_text)

    template_vars = {
        "project": _to_template_dict(context.project),
        "data": _to_template_dict(context.data),
        "db": _to_template_dict(context.db),
        "current": _to_template_dict(source.frontmatter),
    }

    return template.render(**template_vars)


def execute_db_queries(config: ProjectConfig) -> dict:
    """Execute SQLite data queries defined in the project configuration.

    Reads ``database.data_queries`` from *config*, connects to the SQLite
    database specified by ``database.url``, and executes each query.  Each
    result is exposed in the returned dictionary under its ``alias`` key.

    Supported URL format: ``sqlite:///path/to/database.db``.

    Args:
        config: The project configuration.

    Returns:
        A dictionary ``{alias: list_of_row_dicts}``.  Returns an empty
        dict if no queries are configured or the database URL is not
        SQLite.
    """
    queries = config.database.data_queries
    if not queries:
        return {}

    url = config.database.url
    db_path_str = _extract_sqlite_path(url)
    if db_path_str is None:
        logging.warning(
            "Database URL '%s' is not a recognised SQLite URL. Skipping data queries.",
            url,
        )
        return {}

    db_path = config.root / db_path_str
    if not db_path.is_file():
        logging.warning(
            "SQLite database file '%s' does not exist. Skipping data queries.",
            db_path,
        )
        return {}

    result: dict = {}
    try:
        connection = sqlite3.connect(str(db_path))
        connection.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        logging.warning("Failed to connect to SQLite database '%s': %s", db_path, exc)
        return {}

    try:
        for query_def in queries:
            alias = query_def["alias"]
            sql = query_def["sql"]
            try:
                cursor = connection.execute(sql)
                rows = cursor.fetchall()
                result[alias] = [dict(row) for row in rows]
            except sqlite3.Error as exc:
                logging.warning("Query '%s' failed: %s", alias, exc)
    finally:
        connection.close()

    return result


# ---------------------------------------------------------------------------
# Internal helpers — data file parsing
# ---------------------------------------------------------------------------


def _parse_data_file(file_path: Path, suffix: str) -> dict | list:
    """Parse a single data file based on its extension.

    Args:
        file_path: Absolute path to the data file.
        suffix: Lowercase file extension (including dot).

    Returns:
        Parsed data as a Python native structure.
    """
    if suffix == ".csv":
        with file_path.open("r", encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))
    elif suffix == ".json":
        with file_path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    elif suffix == ".yml":
        with file_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
            if data is None:
                return []
            return data
    elif suffix == ".xml":
        tree = ElementTree.parse(str(file_path))
        root = tree.getroot()
        return _xml_to_dict(root)


# ---------------------------------------------------------------------------
# Internal helpers — XML
# ---------------------------------------------------------------------------


def _xml_to_dict(element: ElementTree.Element) -> dict:
    """Convert an XML element into a nested dictionary.

    Text content is stored under a ``"#text"`` key.  Attributes are
    included as regular dict entries (string values).  Child elements are
    grouped by tag name; when multiple siblings share the same tag they
    become a list.

    Args:
        element: The root XML element to convert.

    Returns:
        A dictionary representation of the XML tree.
    """
    result: dict = {}
    if element.text and element.text.strip():
        result["#text"] = element.text.strip()

    for attr_key, attr_value in element.attrib.items():
        result[attr_key] = attr_value

    for child in element:
        child_dict = _xml_to_dict(child)
        tag = child.tag
        if tag in result:
            existing = result[tag]
            if not isinstance(existing, list):
                result[tag] = [existing]
            result[tag].append(child_dict)
        else:
            result[tag] = child_dict

    return result


# ---------------------------------------------------------------------------
# Internal helpers — SQLite URL
# ---------------------------------------------------------------------------


_SQLITE_URL_RE = re.compile(r"^sqlite:///(.+)$")


def _extract_sqlite_path(url: str) -> str | None:
    """Extract the filesystem path from a ``sqlite:///`` URL.

    Args:
        url: A database URL string (e.g. ``"sqlite:///project.db"``).

    Returns:
        The extracted filesystem path, or ``None`` if the URL does not
        match the expected SQLite format.
    """
    match = _SQLITE_URL_RE.match(url)
    if match is None:
        return None
    return match.group(1)


# ---------------------------------------------------------------------------
# Internal helpers — Jinja2 context
# ---------------------------------------------------------------------------


class _TemplateNamespace:
    """A dict-like namespace for Jinja2 that avoids method name collisions.

    Plain ``dict`` objects cause issues in Jinja2 because keys like
    ``items``, ``keys`` or ``values`` collide with built-in dict methods
    during attribute resolution.  This wrapper provides a clean namespace
    where only the actual data keys are exposed.
    """

    __slots__ = ("_data",)

    def __init__(self, data: dict) -> None:
        self._data = data

    def __getattr__(self, name: str) -> object:
        try:
            return _to_template_dict(self._data[name])
        except KeyError:
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'"
            ) from None

    def __getitem__(self, name: str) -> object:
        return _to_template_dict(self._data[name])

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)


def _to_template_dict(value: object) -> object:
    """Recursively convert plain ``dict`` objects to ``_TemplateNamespace``.

    Lists are traversed so that nested dicts inside them are also
    converted.  Other types (str, int, bool, None) are returned unchanged.

    Args:
        value: Any Python value from the template context.

    Returns:
        The same structure with all dicts replaced by namespace objects.
    """
    if isinstance(value, dict):
        return _TemplateNamespace(value)
    if isinstance(value, list):
        return [_to_template_dict(item) for item in value]
    return value
