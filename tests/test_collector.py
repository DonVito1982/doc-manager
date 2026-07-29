from documentos import __version__
from documentos.build import collector


def test_version():
    assert __version__ == "0.1.0"


def test_collector_imports():
    """Verify the collector module can be imported."""
    assert hasattr(collector, "collect")
