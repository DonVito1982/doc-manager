"""Unit tests for the assets module."""

from __future__ import annotations

from pathlib import Path

from documentos.build.assets import _is_source_file, _should_skip, copy_assets
from documentos.config import ProjectConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(tmp_path: Path) -> ProjectConfig:
    config = ProjectConfig(root=tmp_path)
    return config


def _create_file(path: Path, content: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class TestIsSourceFile:
    def test_md_is_source(self):
        assert _is_source_file("doc.md") is True

    def test_md_j2_is_source(self):
        assert _is_source_file("template.md.j2") is True

    def test_ipynb_is_source(self):
        assert _is_source_file("notebook.ipynb") is True

    def test_adoc_is_source(self):
        assert _is_source_file("doc.adoc") is True

    def test_png_is_not_source(self):
        assert _is_source_file("image.png") is False

    def test_pdf_is_not_source(self):
        assert _is_source_file("doc.pdf") is False

    def test_txt_is_not_source(self):
        assert _is_source_file("notes.txt") is False


class TestShouldSkip:
    def test_dotfile_skipped(self):
        assert _should_skip(".hidden") is True

    def test_underscore_skipped(self):
        assert _should_skip("_draft") is True

    def test_normal_file_not_skipped(self):
        assert _should_skip("style.css") is False


# ---------------------------------------------------------------------------
# copy_assets
# ---------------------------------------------------------------------------


class TestCopyAssets:
    def test_copy_packaged_css(self, tmp_path: Path):
        config = _make_config(tmp_path)
        (config.root / "templates").mkdir(exist_ok=True)

        result = copy_assets(config)

        css_dest = tmp_path / "output" / "html" / "assets" / "css" / "style.css"
        assert css_dest.is_file()
        assert any(p == Path("assets") / "css" / "style.css" for p in result)

    def test_copy_packaged_js(self, tmp_path: Path):
        config = _make_config(tmp_path)
        (config.root / "templates").mkdir(exist_ok=True)

        result = copy_assets(config)

        js_dest = tmp_path / "output" / "html" / "assets" / "js" / "mathjax-config.js"
        assert js_dest.is_file()
        assert any(p == Path("assets") / "js" / "mathjax-config.js" for p in result)

    def test_copy_user_assets(self, tmp_path: Path):
        config = _make_config(tmp_path)
        user_css = tmp_path / "templates" / "assets" / "css" / "custom.css"
        _create_file(user_css, "/* custom */")

        result = copy_assets(config)

        dest = tmp_path / "output" / "html" / "assets" / "css" / "custom.css"
        assert dest.is_file()
        assert dest.read_text() == "/* custom */"
        assert any(p == Path("assets") / "css" / "custom.css" for p in result)

    def test_user_assets_override_packaged(self, tmp_path: Path):
        config = _make_config(tmp_path)
        user_css = tmp_path / "templates" / "assets" / "css" / "style.css"
        _create_file(user_css, "/* user override */")

        copy_assets(config)

        dest = tmp_path / "output" / "html" / "assets" / "css" / "style.css"
        assert dest.is_file()
        assert dest.read_text() == "/* user override */"

    def test_copy_content_images(self, tmp_path: Path):
        config = _make_config(tmp_path)
        (config.root / "content").mkdir(exist_ok=True)
        (config.root / "templates").mkdir(exist_ok=True)
        _create_file(tmp_path / "content" / "imagenes" / "diagrama.png", "PNG")

        result = copy_assets(config)

        dest = tmp_path / "output" / "html" / "imagenes" / "diagrama.png"
        assert dest.is_file()
        assert any(p == Path("imagenes") / "diagrama.png" for p in result)

    def test_copy_content_attachments(self, tmp_path: Path):
        config = _make_config(tmp_path)
        (config.root / "content").mkdir(exist_ok=True)
        (config.root / "templates").mkdir(exist_ok=True)
        _create_file(tmp_path / "content" / "anexos" / "documento.pdf", "PDF")

        result = copy_assets(config)

        dest = tmp_path / "output" / "html" / "anexos" / "documento.pdf"
        assert dest.is_file()
        assert any(p == Path("anexos") / "documento.pdf" for p in result)

    def test_content_source_files_not_copied(self, tmp_path: Path):
        config = _make_config(tmp_path)
        (config.root / "content").mkdir(exist_ok=True)
        (config.root / "templates").mkdir(exist_ok=True)
        _create_file(tmp_path / "content" / "doc.md", "# Doc")

        result = copy_assets(config)

        assert not (tmp_path / "output" / "html" / "doc.md").exists()
        assert not any("doc.md" in str(p) for p in result)

    def test_ignore_hidden_in_assets(self, tmp_path: Path):
        config = _make_config(tmp_path)
        _create_file(tmp_path / "templates" / "assets" / ".secreto.css", "secret")

        copy_assets(config)

        hidden_dest = tmp_path / "output" / "html" / "assets" / ".secreto.css"
        assert not hidden_dest.exists()

    def test_ignore_underscore_in_assets(self, tmp_path: Path):
        config = _make_config(tmp_path)
        _create_file(tmp_path / "templates" / "assets" / "_draft.css", "draft")

        copy_assets(config)

        assert not (tmp_path / "output" / "html" / "assets" / "_draft.css").exists()

    def test_ignore_hidden_in_content(self, tmp_path: Path):
        config = _make_config(tmp_path)
        (config.root / "content").mkdir(exist_ok=True)
        (config.root / "templates").mkdir(exist_ok=True)
        _create_file(tmp_path / "content" / ".secret.png", "secret")

        copy_assets(config)

        assert not (tmp_path / "output" / "html" / ".secret.png").exists()

    def test_ignore_underscore_in_content(self, tmp_path: Path):
        config = _make_config(tmp_path)
        (config.root / "content").mkdir(exist_ok=True)
        (config.root / "templates").mkdir(exist_ok=True)
        _create_file(tmp_path / "content" / "_draft_img.png", "draft")

        copy_assets(config)

        assert not (tmp_path / "output" / "html" / "_draft_img.png").exists()

    def test_copy_extra_dirs(self, tmp_path: Path):
        config = _make_config(tmp_path)
        (config.root / "templates").mkdir(exist_ok=True)
        config.assets.extra_dirs = ["static"]
        _create_file(tmp_path / "static" / "logo.png", "LOGO")

        result = copy_assets(config)

        dest = tmp_path / "output" / "html" / "assets" / "logo.png"
        assert dest.is_file()
        assert dest.read_text() == "LOGO"
        assert any(p == Path("assets") / "logo.png" for p in result)

    def test_copy_extra_dirs_nested(self, tmp_path: Path):
        config = _make_config(tmp_path)
        (config.root / "templates").mkdir(exist_ok=True)
        config.assets.extra_dirs = ["media"]
        _create_file(tmp_path / "media" / "img" / "hero.jpg", "JPG")

        result = copy_assets(config)

        dest = tmp_path / "output" / "html" / "assets" / "img" / "hero.jpg"
        assert dest.is_file()
        assert any(p == Path("assets") / "img" / "hero.jpg" for p in result)

    def test_extra_dirs_ignore_hidden(self, tmp_path: Path):
        config = _make_config(tmp_path)
        (config.root / "templates").mkdir(exist_ok=True)
        config.assets.extra_dirs = ["static"]
        _create_file(tmp_path / "static" / ".hidden.png", "x")

        copy_assets(config)

        assert not (tmp_path / "output" / "html" / "assets" / ".hidden.png").exists()

    def test_extra_dirs_ignore_underscore(self, tmp_path: Path):
        config = _make_config(tmp_path)
        (config.root / "templates").mkdir(exist_ok=True)
        config.assets.extra_dirs = ["static"]
        _create_file(tmp_path / "static" / "_draft.png", "x")

        copy_assets(config)

        assert not (tmp_path / "output" / "html" / "assets" / "_draft.png").exists()

    def test_copy_assets_returns_paths(self, tmp_path: Path):
        config = _make_config(tmp_path)
        (config.root / "templates").mkdir(exist_ok=True)

        result = copy_assets(config)

        assert isinstance(result, list)
        assert all(isinstance(p, Path) for p in result)
        assert len(result) > 0

    def test_copy_assets_creates_output_dir(self, tmp_path: Path):
        config = _make_config(tmp_path)
        (config.root / "templates").mkdir(exist_ok=True)

        assert not (tmp_path / "output").exists()

        copy_assets(config)

        assert (tmp_path / "output" / "html" / "assets").is_dir()

    def test_no_content_dir_no_error(self, tmp_path: Path):
        config = _make_config(tmp_path)
        (config.root / "templates").mkdir(exist_ok=True)

        result = copy_assets(config)

        assert isinstance(result, list)

    def test_no_user_assets_dir_no_error(self, tmp_path: Path):
        config = _make_config(tmp_path)
        (config.root / "templates").mkdir(exist_ok=True)

        result = copy_assets(config)

        assert isinstance(result, list)

    def test_extra_dirs_does_not_exist_no_error(self, tmp_path: Path):
        config = _make_config(tmp_path)
        (config.root / "templates").mkdir(exist_ok=True)
        config.assets.extra_dirs = ["fantasma"]

        result = copy_assets(config)

        assert isinstance(result, list)
