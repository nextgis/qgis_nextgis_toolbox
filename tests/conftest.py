# NextGIS Toolbox Plugin
# Copyright (C) 2026  NextGIS
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or any
# later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, see <https://www.gnu.org/licenses/>.

import gc
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Dict, Generator, List, Optional, Tuple
from unittest.mock import MagicMock, Mock
from urllib.parse import urlsplit

import pytest
import qgis.utils
from qgis.core import (
    QgsApplication,
    QgsLayerTreeModel,
    QgsProject,
    QgsSettings,
)
from qgis.gui import QgisInterface, QgsLayerTreeView, QgsMapCanvas
from qgis.PyQt.QtCore import QSize, Qt
from qgis.PyQt.QtWidgets import QMainWindow, QMenu, QToolBar

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = WORKSPACE_ROOT / "src"
PROCESSING_PLUGIN_ROOT = (
    Path(QgsApplication.pkgDataPath()) / "python" / "plugins"
)

if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

if PROCESSING_PLUGIN_ROOT.exists() and (
    str(PROCESSING_PLUGIN_ROOT) not in sys.path
):
    sys.path.insert(0, str(PROCESSING_PLUGIN_ROOT))

if PROCESSING_PLUGIN_ROOT.exists() and (
    str(PROCESSING_PLUGIN_ROOT) not in qgis.utils.plugin_paths
):
    qgis.utils.plugin_paths.append(str(PROCESSING_PLUGIN_ROOT))


@dataclass(frozen=True)
class ApplicationInfo:
    application: QgsApplication
    qgis_auth_db_path: Path
    qgis_custom_config_path: Path


@dataclass(frozen=True)
class ServerResponse:
    body: bytes
    headers: Dict[str, str]
    status: int


@dataclass(frozen=True)
class CapturedRequest:
    body: bytes
    headers: Dict[str, str]
    method: str
    path: str
    query: str


APPLICATION_INFO: Optional[ApplicationInfo] = None


class TestHttpRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self._handle_request()

    def do_HEAD(self) -> None:  # noqa: N802
        self._handle_request(send_body=False)

    def do_POST(self) -> None:  # noqa: N802
        self._handle_request()

    def log_message(self, format: str, *args) -> None:
        del format, args

    def _handle_request(self, send_body: bool = True) -> None:
        state = getattr(self.server, "state")
        content_length = int(self.headers.get("Content-Length", "0"))
        request_body = self.rfile.read(content_length)
        request_url = urlsplit(self.path)

        state.requests.append(
            CapturedRequest(
                body=request_body,
                headers={key: value for key, value in self.headers.items()},
                method=self.command,
                path=request_url.path,
                query=request_url.query,
            )
        )

        response = state.pop_response(self.command, request_url.path)
        if response is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        self.send_response(response.status)

        response_headers = dict(response.headers)
        if "Content-Length" not in response_headers:
            response_headers["Content-Length"] = str(len(response.body))

        for key, value in response_headers.items():
            self.send_header(key, value)

        self.end_headers()
        if send_body:
            self.wfile.write(response.body)


class LocalApiServer:
    def __init__(self) -> None:
        self.requests: List[CapturedRequest] = []
        self._responses: Dict[Tuple[str, str], List[ServerResponse]] = {}
        self._server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            TestHttpRequestHandler,
        )
        setattr(self._server, "state", self)
        self._thread = Thread(target=self._server.serve_forever)
        self._thread.daemon = True
        self._thread.start()

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def add_json_response(
        self,
        method: str,
        path: str,
        payload: object,
        *,
        headers: Optional[Dict[str, str]] = None,
        status: int = 200,
    ) -> None:
        response_headers = {"Content-Type": "application/json"}
        if headers is not None:
            response_headers.update(headers)

        self.add_response(
            method,
            path,
            json.dumps(payload).encode("utf-8"),
            headers=response_headers,
            status=status,
        )

    def add_response(
        self,
        method: str,
        path: str,
        body: bytes,
        *,
        headers: Optional[Dict[str, str]] = None,
        status: int = 200,
    ) -> None:
        key = (method.upper(), path)
        response = ServerResponse(
            body=body,
            headers={} if headers is None else headers,
            status=status,
        )
        self._responses.setdefault(key, []).append(response)

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)

    def pop_response(
        self,
        method: str,
        path: str,
    ) -> Optional[ServerResponse]:
        key = (method.upper(), path)
        responses = self._responses.get(key, [])
        if not responses:
            return None

        return responses.pop(0)


def start_qgis() -> QgsApplication:
    global APPLICATION_INFO

    if APPLICATION_INFO is not None:
        return APPLICATION_INFO.application

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    qgis_custom_config_path = Path(
        tempfile.mkdtemp(prefix="TestNextgisToolbox-config-")
    )
    qgis_auth_db_path = Path(
        tempfile.mkdtemp(prefix="TestNextgisToolbox-authdb-")
    )
    os.environ["QGIS_CUSTOM_CONFIG_PATH"] = str(qgis_custom_config_path)
    os.environ["QGIS_AUTH_DB_DIR_PATH"] = str(qgis_auth_db_path)

    QgsApplication.setAttribute(
        Qt.ApplicationAttribute.AA_ShareOpenGLContexts,
        True,
    )
    QgsApplication.setOrganizationName("NextGIS_Test")
    QgsApplication.setOrganizationDomain("nextgis.test")
    QgsApplication.setApplicationName("NextGIS Toolbox Tests")
    QgsSettings().clear()

    application = QgsApplication(
        list(map(os.fsencode, sys.argv)), True, platformName="desktop"
    )
    application.initQgis()
    processing_plugin_root = (
        Path(QgsApplication.pkgDataPath()) / "python" / "plugins"
    )
    if processing_plugin_root.exists():
        for search_path in (sys.path, qgis.utils.plugin_paths):
            if str(processing_plugin_root) not in search_path:
                search_path.insert(0, str(processing_plugin_root))
    init_interface()

    APPLICATION_INFO = ApplicationInfo(
        application=application,
        qgis_auth_db_path=qgis_auth_db_path,
        qgis_custom_config_path=qgis_custom_config_path,
    )
    return application


def pytest_configure(config) -> None:
    del config
    # UI compatibility modules select the runtime at import time. Initialize
    # the desktop application before test collection, not only in fixtures.
    start_qgis()


def pytest_unconfigure(config) -> None:
    del config
    stop_qgis()


def stop_qgis() -> None:
    global APPLICATION_INFO

    if APPLICATION_INFO is None:
        return

    QgsSettings().clear()
    for _ in range(3):
        gc.collect()
        QgsApplication.processEvents()

    APPLICATION_INFO.application.exitQgis()
    shutil.rmtree(APPLICATION_INFO.qgis_custom_config_path, ignore_errors=True)
    shutil.rmtree(APPLICATION_INFO.qgis_auth_db_path, ignore_errors=True)
    APPLICATION_INFO = None


def init_interface() -> QgisInterface:
    iface = getattr(qgis.utils, "iface", None)
    if iface is None:
        iface = Mock(spec=QgisInterface)
        qgis.utils.iface = iface

    assert isinstance(iface, Mock)

    main_window = iface.mainWindow.return_value
    if not isinstance(main_window, QMainWindow):
        main_window = QMainWindow()
        iface.mainWindow.return_value = main_window

    map_canvas = iface.mapCanvas.return_value
    if not isinstance(map_canvas, QgsMapCanvas):
        map_canvas = QgsMapCanvas(main_window)
        map_canvas.resize(QSize(400, 400))
        iface.mapCanvas.return_value = map_canvas

    layer_tree_view = iface.layerTreeView.return_value
    if not isinstance(layer_tree_view, QgsLayerTreeView):
        layer_tree_view = QgsLayerTreeView(main_window)
        iface.layerTreeView.return_value = layer_tree_view

    layer_tree_model = QgsLayerTreeModel(
        QgsProject.instance().layerTreeRoot(),
        layer_tree_view,
    )
    layer_tree_view.setModel(layer_tree_model)

    vector_menu = iface.vectorMenu.return_value
    if not isinstance(vector_menu, QMenu):
        vector_menu = QMenu("Vector", main_window)
        iface.vectorMenu.return_value = vector_menu

    raster_menu = iface.rasterMenu.return_value
    if not isinstance(raster_menu, QMenu):
        raster_menu = QMenu("Raster", main_window)
        iface.rasterMenu.return_value = raster_menu

    web_menu = iface.webMenu.return_value
    if not isinstance(web_menu, QMenu):
        web_menu = QMenu("web", main_window)
        iface.webMenu.return_value = web_menu

    selection_toolbar = iface.selectionToolBar.return_value
    if not isinstance(selection_toolbar, QToolBar):
        selection_toolbar = QToolBar(main_window)
        iface.selectionToolBar.return_value = selection_toolbar

    user_profile_manager = iface.userProfileManager.return_value
    if not isinstance(user_profile_manager, MagicMock):
        user_profile = MagicMock()
        user_profile.folder.return_value = tempfile.mkdtemp(
            prefix="TestNextgisToolbox-profile-"
        )
        user_profile_manager = MagicMock()
        user_profile_manager.userProfile.return_value = user_profile
        iface.userProfileManager.return_value = user_profile_manager

    return iface


@pytest.fixture(scope="session")
def qgis_app() -> Generator[QgsApplication, None, None]:
    application = start_qgis()
    try:
        yield application
    finally:
        stop_qgis()


@pytest.fixture(autouse=True)
def reset_qgis_settings(
    qgis_app: QgsApplication,
) -> Generator[None, None, None]:
    del qgis_app

    settings = QgsSettings()
    settings.clear()
    yield
    settings.clear()


@pytest.fixture
def qgis_iface(qgis_app: QgsApplication) -> QgisInterface:
    del qgis_app

    iface = init_interface()
    QgsProject.instance().removeAllMapLayers()
    iface.mapCanvas().setLayers([])
    iface.mapCanvas().resize(QSize(400, 400))
    return iface


@pytest.fixture
def api_server(
    qgis_app: QgsApplication,
) -> Generator[LocalApiServer, None, None]:
    del qgis_app

    server = LocalApiServer()
    try:
        yield server
    finally:
        server.close()
