import json
from unittest.mock import Mock

import pytest

from tests.manual.desktop import DesktopSession


def test_desktop_timeout_blocks_automatic_resubmission(monkeypatch, tmp_path):
    monkeypatch.setenv("TOOLBOX_TEST_ARTIFACTS", str(tmp_path))
    session = DesktopSession("http://127.0.0.1:1234")
    session.process = Mock()
    session.process.poll.return_value = None

    with pytest.raises(TimeoutError):
        session.execute("result = api.run_demo('hello')", timeout=0)
    original = (session.root / "request.json").read_text("utf-8")
    with pytest.raises(RuntimeError, match="do not resubmit"):
        session.execute("result = api.run_demo('hello')")

    assert (session.root / "request.json").read_text("utf-8") == original
    assert json.loads(original)["code"] == "result = api.run_demo('hello')"


def test_desktop_rejects_competing_scripts(monkeypatch, tmp_path):
    monkeypatch.setenv("TOOLBOX_TEST_ARTIFACTS", str(tmp_path))
    session = DesktopSession("http://127.0.0.1:1234")
    with session._command_lock:
        with pytest.raises(RuntimeError, match="already running"):
            session.execute("result = 1")
    assert not (session.root / "request.json").exists()
