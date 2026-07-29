from documentos import __version__, config


def test_version():
    assert __version__ == "0.1.0"


def test_config_imports():
    """Verify the config module can be imported."""
    assert hasattr(config, "ProjectConfig")
    assert hasattr(config, "load_config")
    assert hasattr(config, "init_config")
