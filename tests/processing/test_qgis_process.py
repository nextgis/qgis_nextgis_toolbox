# NextGIS Toolbox
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

import json
import os
import shutil
import subprocess

import pytest

from nextgis_toolbox.settings.nextgis_toolbox_settings import (
    AuthenticationType,
    NextgisToolboxSettings,
)
from tests.conftest import SOURCE_ROOT

QGIS_PROCESS_COMMAND = ["qgis_process"]
QGIS_PROCESS_ENDPOINT = None
QGIS_PROCESS_AUTHENTICATION_TYPE = AuthenticationType.NONE
QGIS_PROCESS_AUTHENTICATION_TOKEN = ""


def _skip_if_qgis_process_unavailable() -> None:
    if shutil.which(QGIS_PROCESS_COMMAND[0]) is None:
        pytest.skip("qgis_process is required for integration tests")


@pytest.fixture(autouse=True)
def isolated_process_profile(tmp_path, monkeypatch):
    # Enabling a plugin must never change the user's QGIS profile.
    for variable, directory in (
        ("HOME", "home"),
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_DATA_HOME", "data"),
        ("QGIS_CUSTOM_CONFIG_PATH", "qgis"),
        ("QGIS_AUTH_DB_DIR_PATH", "auth"),
    ):
        path = tmp_path / directory
        path.mkdir()
        monkeypatch.setenv(variable, str(path))
    monkeypatch.setattr(__name__ + ".QGIS_PROCESS_ENDPOINT", None)
    monkeypatch.setattr(
        __name__ + ".QGIS_PROCESS_AUTHENTICATION_TYPE", AuthenticationType.NONE
    )
    monkeypatch.setattr(__name__ + ".QGIS_PROCESS_AUTHENTICATION_TOKEN", "")


def _qgis_process_env() -> dict:
    environment = dict(os.environ)
    environment["QGIS_PLUGINPATH"] = str(SOURCE_ROOT)
    python_path = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = os.pathsep.join(
        [path for path in (str(SOURCE_ROOT), python_path) if path]
    )
    environment.setdefault("QT_QPA_PLATFORM", "offscreen")

    if QGIS_PROCESS_ENDPOINT is not None:
        environment[NextgisToolboxSettings.ENV_API_ENDPOINT] = (
            QGIS_PROCESS_ENDPOINT
        )

    environment[NextgisToolboxSettings.ENV_AUTHENTICATION_TYPE] = str(
        QGIS_PROCESS_AUTHENTICATION_TYPE
    )
    environment[NextgisToolboxSettings.ENV_AUTHENTICATION_TOKEN] = (
        QGIS_PROCESS_AUTHENTICATION_TOKEN
    )

    return environment


def _run_qgis_process(
    *args: str, input_text: str = ""
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*QGIS_PROCESS_COMMAND, *args],
        capture_output=True,
        check=False,
        env=_qgis_process_env(),
        input=input_text,
        text=True,
        timeout=180,
    )


def _enable_plugin() -> None:
    result = _run_qgis_process("plugins", "enable", "nextgis_toolbox")
    combined_output = f"{result.stdout}\n{result.stderr}"
    assert (
        result.returncode == 0
        or "Plugin is already enabled!" in combined_output
    ), combined_output


def _set_local_endpoint(endpoint: str) -> None:
    global QGIS_PROCESS_ENDPOINT
    global QGIS_PROCESS_AUTHENTICATION_TOKEN
    global QGIS_PROCESS_AUTHENTICATION_TYPE

    QGIS_PROCESS_ENDPOINT = endpoint
    QGIS_PROCESS_AUTHENTICATION_TYPE = AuthenticationType.NONE
    QGIS_PROCESS_AUTHENTICATION_TOKEN = ""


def _register_catalog_responses(api_server) -> None:
    def add_json_response_pair(
        path: str,
        payload: object,
        *,
        repeat: int = 4,
    ) -> None:
        paths = [path]
        if path.endswith("/"):
            paths.append(path.rstrip("/"))
        else:
            paths.append(f"{path}/")

        for current_path in paths:
            for _ in range(repeat):
                api_server.add_json_response("GET", current_path, payload)

    add_json_response_pair("/api/tags/", {"data": []})
    add_json_response_pair(
        "/api/tools/",
        {
            "data": [
                {
                    "alias": "Demo Tool",
                    "can_run": True,
                    "description": "Description",
                    "id": 1,
                    "is_dev": False,
                    "is_featured": False,
                    "is_free": True,
                    "is_new": False,
                    "name": "demo-tool",
                    "tags": [],
                }
            ]
        },
    )
    add_json_response_pair(
        "/api/tools/demo-tool",
        {
            "alias": "Demo Tool",
            "description": "Description",
            "docs": "",
            "id": 1,
            "inputs": [],
            "is_dev": False,
            "is_featured": False,
            "is_favorite": False,
            "is_free": True,
            "is_new": False,
            "name": "demo-tool",
            "outputs": [],
            "tags": [],
        },
    )
    add_json_response_pair(
        "/api/tools/demo-tool/presets",
        {"items": []},
    )


def test_qgis_process_lists_toolbox_algorithm(api_server, qgis_app) -> None:
    del qgis_app
    _skip_if_qgis_process_unavailable()
    _set_local_endpoint(api_server.base_url)
    _register_catalog_responses(api_server)
    _enable_plugin()

    result = _run_qgis_process("list")

    assert result.returncode == 0, result.stderr
    assert "nextgis_toolbox:demo-tool" in result.stdout


def test_qgis_process_runs_toolbox_algorithm(api_server, qgis_app) -> None:
    del qgis_app
    _skip_if_qgis_process_unavailable()
    _set_local_endpoint(api_server.base_url)
    _register_catalog_responses(api_server)
    api_server.add_json_response(
        "POST",
        "/api/tasks/",
        {"task_id": "task-1"},
    )
    api_server.add_json_response(
        "GET",
        "/api/tasks/task-1",
        {
            "error": None,
            "operation": "demo-tool",
            "output": [],
            "progress": 100.0,
            "state": "SUCCESS",
            "status": "SUCCESS",
            "tool": "demo-tool",
        },
    )
    _enable_plugin()

    result = _run_qgis_process(
        "--json",
        "run",
        "nextgis_toolbox:demo-tool",
        "-",
        input_text=json.dumps({"inputs": {}}),
    )

    assert result.returncode == 0, result.stderr
    assert any(
        request.method == "POST" and request.path == "/api/tasks/"
        for request in api_server.requests
    )
    assert any(
        request.method == "GET" and request.path == "/api/tasks/task-1"
        for request in api_server.requests
    )
