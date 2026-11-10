import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.fake_weverse import FakeWeverse, MediaServer  # noqa: E402


@pytest.fixture(scope="session")
def media(tmp_path_factory):
    server = MediaServer(tmp_path_factory.mktemp("media"))
    yield server
    server.stop()


@pytest.fixture()
def fake(media):
    f = FakeWeverse(media).install()
    yield f
    f.uninstall()


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """Isola configuração, biblioteca e pasta de vídeos em um diretório temporário."""
    monkeypatch.setenv("DOWNVERSE_HOME", str(tmp_path / "cfg"))
    return tmp_path


@pytest.fixture()
def core(home):
    from downverse.engine import Engine
    from downverse.library import Library
    from downverse.manager import AnalysisManager, DownloadManager
    from downverse.settings import SettingsStore

    settings = SettingsStore()
    settings.update({"output_dir": str(home / "Videos"), "date_timezone": "utc"})
    library = Library()
    engine = Engine(settings, library)
    return type("Core", (), dict(
        settings=settings, library=library, engine=engine,
        downloads=DownloadManager(settings, library, engine),
        analyses=AnalysisManager(settings, library, engine),
        root=home / "Videos" / "Weverse",
    ))
