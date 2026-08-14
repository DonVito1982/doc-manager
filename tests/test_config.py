"""Unit tests for the config module."""

from pathlib import Path

import pytest

from documentos import __version__, config
from documentos.config import (
    ConfigError,
    DatabaseSection,
    DataSection,
    MarkupSection,
    OutputSection,
    PdfSection,
    ProjectConfig,
    ProjectInfo,
    ServerSection,
    TemplatesSection,
    init_config,
    load_config,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_yaml(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _create_required_dirs(project_root: Path) -> None:
    """Create all directories that load_config expects."""
    for dirname in config.REQUIRED_DIRECTORIES:
        (project_root / dirname).mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Module-level smoke tests (kept from original placeholder)
# ---------------------------------------------------------------------------


def test_version() -> None:
    assert __version__ == "0.1.0"


def test_config_imports() -> None:
    """Verify the config module exposes the expected public API."""
    assert hasattr(config, "ProjectConfig")
    assert hasattr(config, "load_config")
    assert hasattr(config, "init_config")
    assert hasattr(config, "ConfigError")


# ---------------------------------------------------------------------------
# 1. test_load_valid_config
# ---------------------------------------------------------------------------


VALID_YAML = """\
project:
  title: "Manual de Ingeniería"
  author: "Equipo Técnico"
  language: "es"

output:
  formats:
    - html
    - pdf
    - epub
  dir: "salida"

pdf:
  header: "Encabezado"
  footer: "Pie de página"
  template: "custom.latex"

markup:
  default: "pandoc-markdown"

data:
  dir: "datos"
  files:
    - "datos.csv"

templates:
  dir: "plantillas"
  default_layout: "layout.html"

database:
  url: "sqlite:///mi_proyecto.db"

server:
  host: "0.0.0.0"
  port: 8080
"""


def test_load_valid_config(tmp_path: Path) -> None:
    """Load a complete YAML config and verify every field."""
    config_path = tmp_path / "config.yml"
    _write_yaml(config_path, VALID_YAML)
    _create_required_dirs(tmp_path)

    cfg = load_config(config_path)

    assert isinstance(cfg, ProjectConfig)
    assert cfg.root == tmp_path.resolve()

    # project
    assert cfg.project.title == "Manual de Ingeniería"
    assert cfg.project.author == "Equipo Técnico"
    assert cfg.project.language == "es"

    # output
    assert cfg.output.formats == ["html", "pdf", "epub"]
    assert cfg.output.dir == "salida"

    # pdf
    assert cfg.pdf.header == "Encabezado"
    assert cfg.pdf.footer == "Pie de página"
    assert cfg.pdf.template == "custom.latex"

    # markup
    assert cfg.markup.default == "pandoc-markdown"

    # data
    assert cfg.data.dir == "datos"
    assert cfg.data.files == ["datos.csv"]

    # templates
    assert cfg.templates.dir == "plantillas"
    assert cfg.templates.default_layout == "layout.html"

    # database
    assert cfg.database.url == "sqlite:///mi_proyecto.db"

    # server
    assert cfg.server.host == "0.0.0.0"
    assert cfg.server.port == 8080


# ---------------------------------------------------------------------------
# 2. test_load_minimal_config
# ---------------------------------------------------------------------------


def test_load_minimal_config(tmp_path: Path) -> None:
    """Load a minimal YAML with only project.title and verify defaults."""
    config_path = tmp_path / "config.yml"
    _write_yaml(config_path, 'project:\n  title: "Solo título"\n')
    _create_required_dirs(tmp_path)

    cfg = load_config(config_path)

    assert cfg.project.title == "Solo título"
    # Defaults for project section
    assert cfg.project.author == config.DEFAULT_PROJECT_AUTHOR
    assert cfg.project.language == config.DEFAULT_PROJECT_LANGUAGE

    # Defaults for output
    assert cfg.output.formats == ["html", "pdf", "epub"]
    assert cfg.output.dir == config.DEFAULT_OUTPUT_DIR

    # Defaults for pdf
    assert cfg.pdf.header == config.DEFAULT_PDF_HEADER
    assert cfg.pdf.footer == config.DEFAULT_PDF_FOOTER
    assert cfg.pdf.template is None

    # Defaults for markup
    assert cfg.markup.default == config.DEFAULT_MARKUP

    # Defaults for data
    assert cfg.data.dir == config.DEFAULT_DATA_DIR
    assert cfg.data.files == []

    # Defaults for templates
    assert cfg.templates.dir == config.DEFAULT_TEMPLATES_DIR
    assert cfg.templates.default_layout == config.DEFAULT_LAYOUT

    # Defaults for database
    assert cfg.database.url == config.DEFAULT_DATABASE_URL

    # Defaults for server
    assert cfg.server.host == config.DEFAULT_SERVER_HOST
    assert cfg.server.port == config.DEFAULT_SERVER_PORT


# ---------------------------------------------------------------------------
# 3. test_load_missing_file
# ---------------------------------------------------------------------------


def test_load_missing_file(tmp_path: Path) -> None:
    """Verify descriptive error when config.yml does not exist."""
    missing = tmp_path / "nonexistent" / "config.yml"
    with pytest.raises(ConfigError, match="not found"):
        load_config(missing)


# ---------------------------------------------------------------------------
# 4. test_load_invalid_yaml
# ---------------------------------------------------------------------------


def test_load_invalid_yaml(tmp_path: Path) -> None:
    """Verify descriptive error on malformed YAML."""
    config_path = tmp_path / "config.yml"
    _write_yaml(config_path, "project: [unclosed\n")
    with pytest.raises(ConfigError, match="Failed to parse YAML"):
        load_config(config_path)


# ---------------------------------------------------------------------------
# 5. test_load_empty_formats
# ---------------------------------------------------------------------------


def test_load_empty_formats(tmp_path: Path) -> None:
    """Empty output.formats must raise ConfigError."""
    config_path = tmp_path / "config.yml"
    _write_yaml(
        config_path,
        'project:\n  title: "Test"\noutput:\n  formats: []\n',
    )
    _create_required_dirs(tmp_path)
    with pytest.raises(ConfigError, match="cannot be empty"):
        load_config(config_path)


# ---------------------------------------------------------------------------
# 6. test_load_invalid_format
# ---------------------------------------------------------------------------


def test_load_invalid_format(tmp_path: Path) -> None:
    """An unsupported format (e.g. 'docx') must raise ConfigError."""
    config_path = tmp_path / "config.yml"
    _write_yaml(
        config_path,
        'project:\n  title: "Test"\noutput:\n  formats:\n    - pdf\n    - docx\n',
    )
    _create_required_dirs(tmp_path)
    with pytest.raises(ConfigError, match="Unsupported output format"):
        load_config(config_path)


# ---------------------------------------------------------------------------
# 7. test_load_missing_content_dir
# ---------------------------------------------------------------------------


def test_load_missing_content_dir(tmp_path: Path) -> None:
    """Missing content/ directory must raise ConfigError."""
    config_path = tmp_path / "config.yml"
    _write_yaml(config_path, 'project:\n  title: "Test"\n')
    # Only create data/ and templates/ — not content/
    (tmp_path / "data").mkdir()
    (tmp_path / "templates").mkdir()
    with pytest.raises(ConfigError, match="Missing required director"):
        load_config(config_path)


# ---------------------------------------------------------------------------
# 8. test_init_config
# ---------------------------------------------------------------------------


def test_init_config(tmp_path: Path) -> None:
    """init_config generates config.yml and returns ProjectConfig."""
    config_path = tmp_path / "config.yml"
    cfg = init_config(config_path)

    # File must exist on disk
    assert config_path.is_file()

    # Returned object has expected defaults
    assert isinstance(cfg, ProjectConfig)
    assert cfg.root == tmp_path.resolve()
    assert cfg.project.title == config.DEFAULT_PROJECT_TITLE
    assert cfg.output.formats == ["html", "pdf", "epub"]
    assert cfg.pdf.template is None

    # Can be reloaded *after* required dirs exist
    _create_required_dirs(tmp_path)
    reloaded = load_config(config_path)
    assert reloaded.project.title == config.DEFAULT_PROJECT_TITLE


# ---------------------------------------------------------------------------
# 9. test_init_config_roundtrip
# ---------------------------------------------------------------------------


def test_init_config_roundtrip(tmp_path: Path) -> None:
    """init → file → load produces an equivalent ProjectConfig."""
    config_path = tmp_path / "config.yml"
    _create_required_dirs(tmp_path)

    initial = init_config(config_path)
    reloaded = load_config(config_path)

    # Compare field-by-field (excluding root which is always derived)
    assert reloaded.project == initial.project
    assert reloaded.output == initial.output
    assert reloaded.pdf == initial.pdf
    assert reloaded.markup == initial.markup
    assert reloaded.data == initial.data
    assert reloaded.templates == initial.templates
    assert reloaded.database == initial.database
    assert reloaded.server == initial.server


# ---------------------------------------------------------------------------
# 10. test_load_config_missing_dirs
# ---------------------------------------------------------------------------

MISSING_DIR_CASES = [
    # Only content exists, data + templates missing
    ({"content"}, "data"),
    # Only data exists, content + templates missing
    ({"data"}, "content"),
    # Only templates exists, content + data missing
    ({"templates"}, "content"),
    # None of the required dirs exist
    (set(), "content"),
]


@pytest.mark.parametrize("present_dirs,expected_missing", MISSING_DIR_CASES)
def test_load_config_missing_dirs_combined(
    tmp_path: Path, present_dirs: set[str], expected_missing: str
) -> None:
    """Missing data/ and/or templates/ raise ConfigError (content/ always required)."""
    config_path = tmp_path / "config.yml"
    _write_yaml(config_path, 'project:\n  title: "Test"\n')
    for dname in present_dirs:
        (tmp_path / dname).mkdir()

    with pytest.raises(ConfigError, match="Missing required director"):
        load_config(config_path)


# ---------------------------------------------------------------------------
# Additional edge-case tests
# ---------------------------------------------------------------------------


def test_load_empty_yaml_file(tmp_path: Path) -> None:
    """An empty YAML file (or file with only comments) uses full defaults."""
    config_path = tmp_path / "config.yml"
    _write_yaml(config_path, "")
    _create_required_dirs(tmp_path)

    cfg = load_config(config_path)
    assert cfg.project.title == config.DEFAULT_PROJECT_TITLE
    assert cfg.project.author == config.DEFAULT_PROJECT_AUTHOR
    assert cfg.output.formats == ["html", "pdf", "epub"]


def test_load_yaml_scalar_top_level(tmp_path: Path) -> None:
    """A YAML file that is not a mapping should raise ConfigError."""
    config_path = tmp_path / "config.yml"
    _write_yaml(config_path, "- just a list\n")
    _create_required_dirs(tmp_path)
    with pytest.raises(ConfigError, match="Expected a YAML mapping"):
        load_config(config_path)


def test_init_config_writes_valid_yaml(tmp_path: Path) -> None:
    """The file generated by init_config must be parseable as YAML."""
    import yaml

    config_path = tmp_path / "config.yml"
    init_config(config_path)

    with config_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert isinstance(data, dict)
    assert data["project"]["title"] == config.DEFAULT_PROJECT_TITLE


def test_config_error_is_exception() -> None:
    """ConfigError is a subclass of Exception."""
    assert issubclass(ConfigError, Exception)


def test_default_dataclass_instances() -> None:
    """All section dataclasses can be instantiated with defaults."""
    assert ProjectInfo().title == config.DEFAULT_PROJECT_TITLE
    assert OutputSection().formats == ["html", "pdf", "epub"]
    assert PdfSection().template is None
    assert MarkupSection().default == "pandoc-markdown"
    assert DataSection().files == []
    assert TemplatesSection().default_layout == "base.html"
    assert DatabaseSection().url == "sqlite:///project.db"
    assert ServerSection().port == 5000


def test_projec_config_default_root_is_cwd() -> None:
    """Default ProjectConfig.root is Path() (current directory)."""
    cfg = ProjectConfig()
    assert cfg.root == Path()


def test_load_config_formats_case_sensitive(tmp_path: Path) -> None:
    """Formats must match exactly — 'HTML' is not valid."""
    config_path = tmp_path / "config.yml"
    _write_yaml(
        config_path,
        'project:\n  title: "Test"\noutput:\n  formats:\n    - HTML\n',
    )
    _create_required_dirs(tmp_path)
    with pytest.raises(ConfigError, match="Unsupported output format"):
        load_config(config_path)


# ---------------------------------------------------------------------------
# Edge-case coverage: non-list values for list-typed fields
# ---------------------------------------------------------------------------


def test_load_config_output_formats_is_string(tmp_path: Path) -> None:
    """If output.formats is a string instead of a list, fall back to defaults."""
    config_path = tmp_path / "config.yml"
    _write_yaml(
        config_path,
        'project:\n  title: "Test"\noutput:\n  formats: html\n',
    )
    _create_required_dirs(tmp_path)
    cfg = load_config(config_path)
    assert cfg.output.formats == ["html", "pdf", "epub"]


def test_load_config_data_files_is_string(tmp_path: Path) -> None:
    """If data.files is a string instead of a list, fall back to empty list."""
    config_path = tmp_path / "config.yml"
    _write_yaml(
        config_path,
        'project:\n  title: "Test"\ndata:\n  files: single.csv\n',
    )
    _create_required_dirs(tmp_path)
    cfg = load_config(config_path)
    assert cfg.data.files == []


def test_load_config_data_queries_is_string(tmp_path: Path) -> None:
    """If database.data_queries is a string instead of a list, fall back to empty."""
    config_path = tmp_path / "config.yml"
    _write_yaml(
        config_path,
        "project:\n  title: Test\ndatabase:\n  data_queries: not_a_list\n",
    )
    _create_required_dirs(tmp_path)
    cfg = load_config(config_path)
    assert cfg.database.data_queries == []


def test_load_config_assets_extra_dirs_not_list(tmp_path: Path) -> None:
    """If assets.extra_dirs is not a list, fall back to empty list (line 355)."""
    config_path = tmp_path / "config.yml"
    _write_yaml(
        config_path,
        'project:\n  title: "Test"\nassets:\n  extra_dirs: not_a_list\n',
    )
    _create_required_dirs(tmp_path)
    cfg = load_config(config_path)
    assert cfg.assets.extra_dirs == []
