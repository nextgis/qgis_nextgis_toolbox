import json
import os
import shlex
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, Tuple


class DesktopSession:
    """Own one isolated QGIS process and its trusted file-based script bridge."""

    def __init__(
        self,
        endpoint: str,
        command: str = "qgis",
        timeout: int = 180,
        token: str = "",
    ) -> None:
        base = Path(os.environ.get("TOOLBOX_TEST_ARTIFACTS", "/tmp/opencode"))
        base.mkdir(parents=True, exist_ok=True)
        self.root = Path(
            tempfile.mkdtemp(prefix="toolbox-desktop-", dir=str(base))
        )
        self.endpoint = endpoint
        self.command = shlex.split(command)
        self.timeout = timeout
        self.token = token
        self.process = None
        self.log = None
        self.broken = False
        self._command_lock = Lock()
        self.local_requests: Optional[List[Tuple[str, str]]] = None
        self.local_submissions: List[Dict[str, Any]] = []

    def __enter__(self) -> "DesktopSession":
        project = Path(__file__).resolve().parents[2]
        plugins = self.root / "plugins"
        shutil.copytree(
            project / "src" / "nextgis_toolbox",
            plugins / "nextgis_toolbox",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        shutil.copytree(
            Path(__file__).resolve().parent / "probe_plugin",
            plugins / "toolbox_test_probe",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        bootstrap = self.root / "bootstrap.py"
        bootstrap.write_text(
            "import sys, qgis.utils\n"
            "import os\n"
            "from qgis.core import QgsApplication\n"
            "from qgis.PyQt.QtCore import QTimer\n"
            "def record_message(message, tag, level):\n"
            "    token = os.environ.get('NEXTGIS_TOOLBOX_AUTHENTICATION_TOKEN', '')\n"
            "    if token:\n"
            "        message = message.replace(token, '<redacted>')\n"
            f"    with open({str(self.root / 'messages.log')!r}, 'a', encoding='utf-8') as stream:\n"
            "        stream.write(f'{tag}: {message}\\n')\n"
            "QgsApplication.messageLog().messageReceived.connect(record_message)\n"
            f"sys.path.insert(0, {str(plugins)!r})\n"
            f"qgis.utils.plugin_paths.insert(0, {str(plugins)!r})\n"
            "def start():\n"
            "    qgis.utils.updateAvailablePlugins()\n"
            "    from nextgis_toolbox.settings.nextgis_toolbox_settings import NextgisToolboxSettings\n"
            "    NextgisToolboxSettings().is_experimental_qgis_integration_enabled = True\n"
            "    for name in ('processing', 'nextgis_toolbox', 'toolbox_test_probe'):\n"
            "        if name not in qgis.utils.plugins:\n"
            "            assert qgis.utils.loadPlugin(name), name\n"
            "            assert qgis.utils.startPlugin(name), name\n"
            "QTimer.singleShot(0, start)\n",
            "utf-8",
        )
        environment = dict(os.environ)
        # Never inherit another profile or an ambient plugin search path.
        environment.pop("PYTHONPATH", None)
        environment["QGIS_PLUGINPATH"] = str(plugins)
        environment["QGIS_CUSTOM_CONFIG_PATH"] = str(self.root / "config")
        environment["QGIS_AUTH_DB_DIR_PATH"] = str(self.root / "auth")
        for name in ("CACHE", "CONFIG", "DATA"):
            environment[f"XDG_{name}_HOME"] = str(self.root / name.lower())
        environment["TOOLBOX_TEST_ROOT"] = str(self.root)
        environment["NEXTGIS_TOOLBOX_ENDPOINT"] = self.endpoint
        token = self.token
        environment["NEXTGIS_TOOLBOX_AUTHENTICATION_TOKEN"] = token
        environment["NEXTGIS_TOOLBOX_AUTHENTICATION_TYPE"] = (
            "token" if token else "none"
        )
        arguments = self.command + [
            "--nologo",
            "--noversioncheck",
            "--noplugins",
            "--profiles-path",
            str(self.root / "profiles"),
            "--profile",
            "integration",
            "--code",
            str(bootstrap),
        ]
        (self.root / "command.json").write_text(json.dumps(arguments), "utf-8")
        self.log = (self.root / "qgis.log").open("w", encoding="utf-8")
        try:
            self.process = subprocess.Popen(
                arguments, env=environment, stdout=self.log, stderr=self.log
            )
            self.wait(
                "api.state()",
                lambda state: state["state"] == "loaded" and state["menu"],
            )
            return self
        except BaseException:
            self.close()
            raise

    def execute(self, code: str, timeout: Optional[float] = None) -> Any:
        """Execute a trusted script with persistent ``api`` and ``iface`` variables.

        Assign a JSON-compatible value to ``result`` to return it to the caller.
        A timeout poisons the session; remote operations must not be retried.
        """
        if not self._command_lock.acquire(blocking=False):
            raise RuntimeError(
                "Another script is already running in this session"
            )
        try:
            return self._execute(code, timeout)
        finally:
            self._command_lock.release()

    def _execute(self, code: str, timeout: Optional[float]) -> Any:
        if self.process is None:
            raise RuntimeError(
                "Use DesktopSession as a context manager before executing scripts"
            )
        if self.broken:
            raise RuntimeError(
                "Session timed out; restart explicitly, do not resubmit remote tasks"
            )
        request_id = uuid.uuid4().hex
        request = self.root / "request.json"
        temporary = request.with_suffix(".tmp")
        response_path = self.root / "response.json"
        if response_path.exists():
            response_path.unlink()
        temporary.write_text(
            json.dumps({"id": request_id, "code": code}), "utf-8"
        )
        temporary.replace(request)
        deadline = time.monotonic() + (
            self.timeout if timeout is None else timeout
        )
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self.broken = True
                raise RuntimeError(
                    "QGIS exited; see " + str(self.root / "qgis.log")
                )
            if response_path.exists():
                response = json.loads(response_path.read_text("utf-8"))
                if response["id"] == request_id:
                    if "error" in response:
                        raise RuntimeError(response["error"])
                    return response["result"]
            time.sleep(0.05)
        self.broken = True
        raise TimeoutError(
            "QGIS command timed out; artifacts: " + str(self.root)
        )

    def evaluate(
        self, expression: str, timeout: Optional[float] = None
    ) -> Any:
        """Evaluate a trusted expression in the QGIS GUI thread."""
        return self.execute("result = " + expression, timeout)

    def wait(
        self,
        expression: str,
        predicate: Callable[[Any], bool],
        timeout: Optional[float] = None,
    ) -> Any:
        """Wait for an observed condition while QGIS processes its event loop."""
        deadline = time.monotonic() + (
            self.timeout if timeout is None else timeout
        )
        last_error = None
        while time.monotonic() < deadline:
            try:
                value = self.evaluate(
                    expression, timeout=max(0.1, deadline - time.monotonic())
                )
                if predicate(value):
                    return value
                if isinstance(value, dict) and (
                    value.get("catalog_error") or value.get("state") == "error"
                ):
                    raise AssertionError(
                        f"QGIS initialization failed: {value}; artifacts: {self.root}"
                    )
            except RuntimeError as error:
                last_error = error
                if self.process.poll() is not None:
                    raise
            time.sleep(0.1)
        raise TimeoutError(
            f"Condition failed: {expression}; {last_error}; artifacts: {self.root}"
        )

    def close(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.log is not None:
            self.log.close()

    def __exit__(self, *args) -> None:
        self.close()
