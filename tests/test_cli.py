from documentos import __version__, cli


def test_version():
    assert __version__ == "0.1.0"


def test_cli_imports():
    """Verify the CLI module can be imported."""
    assert hasattr(cli, "main")
