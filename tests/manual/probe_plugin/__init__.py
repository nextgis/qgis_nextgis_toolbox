import json
import os
import traceback
from pathlib import Path

from qgis.PyQt.QtCore import QTimer

from .runtime import DesktopTools


def classFactory(iface):
    return ProbePlugin(iface)


class ProbePlugin:
    """Execute trusted local scripts on the GUI thread, without a network port."""

    def __init__(self, iface):
        self.root = Path(os.environ["TOOLBOX_TEST_ROOT"])
        self.api = DesktopTools(iface, self.root)
        self.namespace = {"api": self.api, "iface": iface}
        self.timer = QTimer(iface.mainWindow())
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._dispatch)

    def initGui(self):
        self.timer.start()

    def unload(self):
        self.timer.stop()
        self.api.close_dialog()
        self.timer.deleteLater()

    def _dispatch(self):
        request_path = self.root / "request.json"
        if not request_path.exists():
            return
        # Stop polling during nested event loops to prevent competing writers.
        self.timer.stop()
        request = {}
        try:
            request = json.loads(request_path.read_text("utf-8"))
            request_path.unlink()
            self.namespace.pop("result", None)
            exec(
                compile(request["code"], "<desktop-test>", "exec"),
                self.namespace,
            )
            response = {
                "id": request["id"],
                "result": self.namespace.get("result"),
            }
        except Exception:
            error = traceback.format_exc()
            token = os.environ.get("NEXTGIS_TOOLBOX_AUTHENTICATION_TOKEN", "")
            if token:
                error = error.replace(token, "<redacted>")
            response = {
                "id": request.get("id"),
                "error": error,
            }
        finally:
            self.timer.start()
        target = self.root / "response.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(response, default=str), "utf-8")
        temporary.replace(target)
