"""Unit tests for the preprocessor module."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import pytest
from jinja2 import TemplateSyntaxError, UndefinedError

from documentos.build.collector import SourceFile
from documentos.build.preprocessor import (
    DataContext,
    _extract_sqlite_path,
    _TemplateNamespace,
    _to_template_dict,
    execute_db_queries,
    load_data_files,
    preprocess,
)
from documentos.config import ProjectConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project_config(
    tmp_path: Path, data_dir_name: str = "data"
) -> ProjectConfig:
    """Create a minimal ProjectConfig rooted at *tmp_path* with a data dir."""
    config = ProjectConfig(root=tmp_path)
    config.data.dir = data_dir_name
    return config


def _make_source_file(
    path: Path, fmt: str = "md", frontmatter: dict | None = None
) -> SourceFile:
    """Create a SourceFile pointing at *path*."""
    return SourceFile(path=path, format=fmt, frontmatter=frontmatter or {})


# ---------------------------------------------------------------------------
# DataContext
# ---------------------------------------------------------------------------


class TestDataContext:
    """Tests for the DataContext dataclass."""

    def test_creation_defaults(self) -> None:
        ctx = DataContext()
        assert ctx.project == {}
        assert ctx.data == {}
        assert ctx.db == {}

    def test_creation_with_values(self) -> None:
        ctx = DataContext(
            project={"title": "Test"},
            data={"equipos": [{"id": "1"}]},
            db={"autores": [{"nombre": "Ana"}]},
        )
        assert ctx.project == {"title": "Test"}
        assert ctx.data == {"equipos": [{"id": "1"}]}
        assert ctx.db == {"autores": [{"nombre": "Ana"}]}

    def test_fields_are_mutable(self) -> None:
        ctx = DataContext()
        ctx.project["title"] = "New"
        ctx.data["key"] = "val"
        ctx.db["q"] = ["result"]
        assert ctx.project == {"title": "New"}
        assert ctx.data == {"key": "val"}
        assert ctx.db == {"q": ["result"]}


# ---------------------------------------------------------------------------
# load_data_files
# ---------------------------------------------------------------------------


class TestLoadDataFiles:
    """Tests for the load_data_files function."""

    # --- CSV ------------------------------------------------------------------

    def test_load_csv(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        file = data_dir / "equipos.csv"
        file.write_text("id,nombre\n1,Bomba\n2,Motor\n", encoding="utf-8")

        config = _make_project_config(tmp_path)
        result = load_data_files(config)
        assert result == {
            "equipos": [
                {"id": "1", "nombre": "Bomba"},
                {"id": "2", "nombre": "Motor"},
            ]
        }

    def test_load_json_list(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        file = data_dir / "items.json"
        file.write_text(json.dumps([{"a": 1}, {"a": 2}]), encoding="utf-8")

        config = _make_project_config(tmp_path)
        result = load_data_files(config)
        assert result == {"items": [{"a": 1}, {"a": 2}]}

    def test_load_json_object(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        file = data_dir / "config.json"
        file.write_text(json.dumps({"key": "value", "num": 42}), encoding="utf-8")

        config = _make_project_config(tmp_path)
        result = load_data_files(config)
        assert result == {"config": {"key": "value", "num": 42}}

    def test_load_yml(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        file = data_dir / "settings.yml"
        file.write_text("mode: production\nport: 8080\n", encoding="utf-8")

        config = _make_project_config(tmp_path)
        result = load_data_files(config)
        assert result == {"settings": {"mode": "production", "port": 8080}}

    def test_load_yml_empty(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        file = data_dir / "empty.yml"
        file.write_text("", encoding="utf-8")

        config = _make_project_config(tmp_path)
        result = load_data_files(config)
        assert result == {"empty": []}

    def test_load_xml(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        file = data_dir / "catalog.xml"
        file.write_text(
            '<?xml version="1.0"?><root><item id="1">Widget</item></root>',
            encoding="utf-8",
        )

        config = _make_project_config(tmp_path)
        result = load_data_files(config)
        assert "catalog" in result
        assert isinstance(result["catalog"], dict)
        assert "item" in result["catalog"]

    # --- Ignore hidden files --------------------------------------------------

    def test_ignores_dot_prefix(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / ".hidden.csv").write_text("id,name\n1,Hidden\n", encoding="utf-8")
        (data_dir / "visible.csv").write_text("id,name\n1,Visible\n", encoding="utf-8")

        config = _make_project_config(tmp_path)
        result = load_data_files(config)
        assert list(result.keys()) == ["visible"]

    def test_ignores_underscore_prefix(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "_draft.csv").write_text("id,name\n1,Draft\n", encoding="utf-8")
        (data_dir / "final.csv").write_text("id,name\n1,Final\n", encoding="utf-8")

        config = _make_project_config(tmp_path)
        result = load_data_files(config)
        assert list(result.keys()) == ["final"]

    # --- Unrecognised extension -----------------------------------------------

    def test_unrecognized_extension_warning(self, tmp_path: Path, caplog) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "unknown.txt").write_text("hello\n", encoding="utf-8")

        config = _make_project_config(tmp_path)
        with caplog.at_level(logging.WARNING):
            result = load_data_files(config)

        assert result == {}
        assert "Unrecognised file extension" in caplog.text

    # --- Empty / missing directory --------------------------------------------

    def test_empty_data_directory(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        config = _make_project_config(tmp_path)
        result = load_data_files(config)
        assert result == {}

    def test_missing_data_directory(self, tmp_path: Path) -> None:
        config = _make_project_config(tmp_path)
        result = load_data_files(config)
        assert result == {}

    # --- Multiple file types --------------------------------------------------

    def test_multiple_file_types(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "users.csv").write_text("id,name\n1,Alice\n", encoding="utf-8")
        (data_dir / "metadata.json").write_text(
            json.dumps({"version": "1.0"}), encoding="utf-8"
        )
        (data_dir / "settings.yml").write_text(
            "theme: dark\n", encoding="utf-8"
        )

        config = _make_project_config(tmp_path)
        result = load_data_files(config)
        assert set(result.keys()) == {"users", "metadata", "settings"}
        assert result["users"] == [{"id": "1", "name": "Alice"}]
        assert result["metadata"] == {"version": "1.0"}
        assert result["settings"] == {"theme": "dark"}

    # --- Custom data dir name -------------------------------------------------

    def test_custom_data_dir(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "datos"
        data_dir.mkdir()
        (data_dir / "info.csv").write_text("key,val\na,1\n", encoding="utf-8")

        config = _make_project_config(tmp_path, data_dir_name="datos")
        result = load_data_files(config)
        assert result == {"info": [{"key": "a", "val": "1"}]}

    # --- Ignores subdirectories -----------------------------------------------

    def test_ignores_subdirectories(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        sub = data_dir / "sub"
        sub.mkdir()
        (sub / "nested.csv").write_text("id,name\n1,Deep\n", encoding="utf-8")

        config = _make_project_config(tmp_path)
        result = load_data_files(config)
        assert result == {}

    # --- Corrupt files --------------------------------------------------------

    def test_corrupt_json_emits_warning(self, tmp_path: Path, caplog) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "bad.json").write_text("not valid json", encoding="utf-8")

        config = _make_project_config(tmp_path)
        with caplog.at_level(logging.WARNING):
            result = load_data_files(config)
        assert result == {}
        assert "Failed to parse data file" in caplog.text

    def test_load_xml_with_text_content(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        file = data_dir / "note.xml"
        file.write_text(
            '<?xml version="1.0"?><note><to>Alice</to><body>Hello</body></note>',
            encoding="utf-8",
        )

        config = _make_project_config(tmp_path)
        result = load_data_files(config)
        assert result == {
            "note": {"to": {"#text": "Alice"}, "body": {"#text": "Hello"}},
        }

    # --- JSON extension case-insensitivity ------------------------------------

    def test_json_extension_case_insensitive(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        file = data_dir / "info.JSON"
        file.write_text(json.dumps({"key": "value"}), encoding="utf-8")

        config = _make_project_config(tmp_path)
        result = load_data_files(config)
        assert result == {"info": {"key": "value"}}

    def test_xml_with_repeated_child_tags(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        file = data_dir / "items.xml"
        file.write_text(
            '<?xml version="1.0"?><root>'
            '<item id="1">A</item>'
            '<item id="2">B</item>'
            '</root>',
            encoding="utf-8",
        )

        config = _make_project_config(tmp_path)
        result = load_data_files(config)
        assert "items" in result
        items = result["items"]["item"]
        assert isinstance(items, list)
        assert len(items) == 2


# ---------------------------------------------------------------------------
# preprocess
# ---------------------------------------------------------------------------


class TestPreprocess:
    """Tests for the preprocess function."""

    # --- Passthrough ----------------------------------------------------------

    def test_passthrough_md(self, tmp_path: Path) -> None:
        file = tmp_path / "doc.md"
        file.write_text("# Hello\n\nWorld\n", encoding="utf-8")
        source = _make_source_file(file, fmt="md")
        context = DataContext()

        result = preprocess(source, context)
        assert result == "# Hello\n\nWorld\n"

    def test_passthrough_adoc(self, tmp_path: Path) -> None:
        file = tmp_path / "doc.adoc"
        file.write_text("= Title\n", encoding="utf-8")
        source = _make_source_file(file, fmt="adoc")
        context = DataContext()

        result = preprocess(source, context)
        assert result == "= Title\n"

    def test_passthrough_ipynb(self, tmp_path: Path) -> None:
        file = tmp_path / "nb.ipynb"
        file.write_text('{"cells": []}', encoding="utf-8")
        source = _make_source_file(file, fmt="ipynb")
        context = DataContext()

        result = preprocess(source, context)
        assert result == '{"cells": []}'

    # --- Jinja2 rendering -----------------------------------------------------

    def test_render_simple_j2(self, tmp_path: Path) -> None:
        file = tmp_path / "template.md.j2"
        file.write_text("# {{ project.title }}\n", encoding="utf-8")
        source = _make_source_file(file, fmt="md.j2")
        context = DataContext(project={"title": "My Project"})

        result = preprocess(source, context)
        assert result == "# My Project\n"

    def test_render_with_data(self, tmp_path: Path) -> None:
        file = tmp_path / "template.md.j2"
        file.write_text(
            "{% for item in data.items %}- {{ item.name }}\n{% endfor %}",
            encoding="utf-8",
        )
        source = _make_source_file(file, fmt="md.j2")
        context = DataContext(
            data={"items": [{"name": "A"}, {"name": "B"}]}
        )

        result = preprocess(source, context)
        assert result == "- A\n- B\n"

    def test_render_with_db(self, tmp_path: Path) -> None:
        file = tmp_path / "template.md.j2"
        file.write_text(
            "{{ db.autores[0].nombre }}\n", encoding="utf-8"
        )
        source = _make_source_file(file, fmt="md.j2")
        context = DataContext(
            db={"autores": [{"nombre": "Carlos"}]}
        )

        result = preprocess(source, context)
        assert result == "Carlos\n"

    def test_render_project_available(self, tmp_path: Path) -> None:
        file = tmp_path / "template.md.j2"
        file.write_text(
            "Title: {{ project.title }}\nAuthor: {{ project.author }}\n",
            encoding="utf-8",
        )
        source = _make_source_file(file, fmt="md.j2")
        context = DataContext(
            project={"title": "Manual", "author": "Equipo"}
        )

        result = preprocess(source, context)
        assert result == "Title: Manual\nAuthor: Equipo\n"

    def test_render_current_frontmatter(self, tmp_path: Path) -> None:
        file = tmp_path / "template.md.j2"
        file.write_text("Current title: {{ current.title }}\n", encoding="utf-8")
        source = _make_source_file(
            file, fmt="md.j2", frontmatter={"title": "Chapter 1"}
        )
        context = DataContext()

        result = preprocess(source, context)
        assert result == "Current title: Chapter 1\n"

    # --- Jinja2 errors --------------------------------------------------------

    def test_undefined_variable_raises_undefined_error(
        self, tmp_path: Path
    ) -> None:
        file = tmp_path / "template.md.j2"
        file.write_text("{{ nonexistent }}\n", encoding="utf-8")
        source = _make_source_file(file, fmt="md.j2")
        context = DataContext()

        with pytest.raises(UndefinedError):
            preprocess(source, context)

    def test_syntax_error_raises_template_syntax_error(
        self, tmp_path: Path
    ) -> None:
        file = tmp_path / "template.md.j2"
        file.write_text("{% for %}\n", encoding="utf-8")
        source = _make_source_file(file, fmt="md.j2")
        context = DataContext()

        with pytest.raises(TemplateSyntaxError):
            preprocess(source, context)

    # --- Complex templates ----------------------------------------------------

    def test_render_with_all_contexts(self, tmp_path: Path) -> None:
        file = tmp_path / "template.md.j2"
        file.write_text(
            "# {{ project.title }}\n"
            "Author: {{ current.author }}\n"
            "{% for item in data.items %}- {{ item }}\n{% endfor %}"
            "DB count: {{ db.results | length }}\n",
            encoding="utf-8",
        )
        source = _make_source_file(
            file, fmt="md.j2", frontmatter={"author": "Ana"}
        )
        context = DataContext(
            project={"title": "Report"},
            data={"items": ["a", "b", "c"]},
            db={"results": [{"id": 1}]},
        )

        result = preprocess(source, context)
        expected = "# Report\nAuthor: Ana\n- a\n- b\n- c\nDB count: 1\n"
        assert result == expected


# ---------------------------------------------------------------------------
# execute_db_queries
# ---------------------------------------------------------------------------


class TestExecuteDbQueries:
    """Tests for the execute_db_queries function."""

    def test_executes_single_query(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE autores (id INTEGER, nombre TEXT)")
        conn.execute("INSERT INTO autores VALUES (1, 'Ana')")
        conn.execute("INSERT INTO autores VALUES (2, 'Luis')")
        conn.commit()
        conn.close()

        config = ProjectConfig(root=tmp_path)
        config.database.url = f"sqlite:///{db_path.name}"
        config.database.data_queries = [
            {"alias": "autores", "sql": "SELECT * FROM autores"}
        ]

        result = execute_db_queries(config)
        assert "autores" in result
        assert result["autores"] == [
            {"id": 1, "nombre": "Ana"},
            {"id": 2, "nombre": "Luis"},
        ]

    def test_executes_multiple_queries(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE t1 (val TEXT)")
        conn.execute("INSERT INTO t1 VALUES ('x')")
        conn.execute("CREATE TABLE t2 (num INTEGER)")
        conn.execute("INSERT INTO t2 VALUES (42)")
        conn.commit()
        conn.close()

        config = ProjectConfig(root=tmp_path)
        config.database.url = f"sqlite:///{db_path.name}"
        config.database.data_queries = [
            {"alias": "q1", "sql": "SELECT * FROM t1"},
            {"alias": "q2", "sql": "SELECT num FROM t2"},
        ]

        result = execute_db_queries(config)
        assert result == {
            "q1": [{"val": "x"}],
            "q2": [{"num": 42}],
        }

    def test_no_queries_returns_empty(self, tmp_path: Path) -> None:
        config = ProjectConfig(root=tmp_path)
        config.database.data_queries = []

        result = execute_db_queries(config)
        assert result == {}

    def test_non_sqlite_url_returns_empty(self, tmp_path: Path, caplog) -> None:
        config = ProjectConfig(root=tmp_path)
        config.database.url = "postgresql://localhost/db"
        config.database.data_queries = [
            {"alias": "q", "sql": "SELECT 1"}
        ]

        with caplog.at_level(logging.WARNING):
            result = execute_db_queries(config)
        assert result == {}
        assert "not a recognised SQLite URL" in caplog.text

    def test_missing_db_file_returns_empty(self, tmp_path: Path, caplog) -> None:
        config = ProjectConfig(root=tmp_path)
        config.database.url = "sqlite:///nonexistent.db"
        config.database.data_queries = [
            {"alias": "q", "sql": "SELECT 1"}
        ]

        with caplog.at_level(logging.WARNING):
            result = execute_db_queries(config)
        assert result == {}
        assert "does not exist" in caplog.text

    def test_failed_query_logs_warning(self, tmp_path: Path, caplog) -> None:
        db_path = tmp_path / "project.db"
        conn = sqlite3.connect(str(db_path))
        conn.close()

        config = ProjectConfig(root=tmp_path)
        config.database.url = f"sqlite:///{db_path.name}"
        config.database.data_queries = [
            {"alias": "q", "sql": "SELECT * FROM nonexistent_table"}
        ]

        with caplog.at_level(logging.WARNING):
            result = execute_db_queries(config)
        assert result == {}
        assert "failed" in caplog.text

    def test_connection_error_logs_warning(self, tmp_path: Path, caplog) -> None:
        db_file = tmp_path / "locked.db"
        db_file.touch()
        db_file.chmod(0o000)

        try:
            config = ProjectConfig(root=tmp_path)
            config.database.url = f"sqlite:///{db_file.name}"
            config.database.data_queries = [
                {"alias": "q", "sql": "SELECT 1"}
            ]

            with caplog.at_level(logging.WARNING):
                result = execute_db_queries(config)

            assert result == {}
            assert "Failed to connect" in caplog.text
        finally:
            db_file.chmod(0o644)


# ---------------------------------------------------------------------------
# _extract_sqlite_path
# ---------------------------------------------------------------------------


class TestExtractSqlitePath:
    """Tests for the _extract_sqlite_path helper."""

    def test_extracts_path(self) -> None:
        assert _extract_sqlite_path("sqlite:///project.db") == "project.db"

    def test_extracts_relative_path(self) -> None:
        assert (
            _extract_sqlite_path("sqlite:///data/sub/db.sqlite")
            == "data/sub/db.sqlite"
        )

    def test_non_sqlite_url_returns_none(self) -> None:
        assert _extract_sqlite_path("postgresql://localhost/db") is None

    def test_missing_slashes_returns_none(self) -> None:
        assert _extract_sqlite_path("sqlite:project.db") is None


# ---------------------------------------------------------------------------
# _TemplateNamespace (internal helper)
# ---------------------------------------------------------------------------


class TestTemplateNamespace:
    """Tests for the _TemplateNamespace internal helper."""

    def test_getitem(self) -> None:
        ns = _TemplateNamespace({"key": "value"})
        assert ns["key"] == "value"

    def test_iter(self) -> None:
        ns = _TemplateNamespace({"a": 1, "b": 2})
        keys = list(ns)
        assert set(keys) == {"a", "b"}

    def test_len(self) -> None:
        ns = _TemplateNamespace({"a": 1, "b": 2, "c": 3})
        assert len(ns) == 3

    def test_getattr_key_exists(self) -> None:
        ns = _TemplateNamespace({"nested": {"inner": "val"}})
        inner = ns.nested
        assert isinstance(inner, _TemplateNamespace)
        assert inner.inner == "val"

    def test_getattr_key_missing(self) -> None:
        ns = _TemplateNamespace({})
        with pytest.raises(AttributeError, match="has no attribute 'missing'"):
            _ = ns.missing

    def test_to_template_dict_converts_nested(self) -> None:
        result = _to_template_dict({"a": {"b": "c"}})
        assert isinstance(result, _TemplateNamespace)
        assert isinstance(result.a, _TemplateNamespace)

    def test_to_template_dict_converts_list_of_dicts(self) -> None:
        result = _to_template_dict([{"key": "val"}])
        assert isinstance(result, list)
        assert isinstance(result[0], _TemplateNamespace)

    def test_to_template_dict_passes_through_primitives(self) -> None:
        assert _to_template_dict("hello") == "hello"
        assert _to_template_dict(42) == 42
        assert _to_template_dict(True) is True
        assert _to_template_dict(None) is None
