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
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import parse_qs

import pytest
from qgis.PyQt.QtNetwork import QNetworkReply

from nextgis_toolbox.api import client as client_module
from nextgis_toolbox.api.authentication import (
    ToolboxTokenAuthentication,
)
from nextgis_toolbox.api.client import ToolboxApiClient
from nextgis_toolbox.core.exceptions import (
    NextgisToolboxCacheReadError,
    ToolboxError,
    ToolboxFileWriteError,
    ToolboxNetworkError,
)


def test_get_parses_json_response(api_server) -> None:
    api_server.add_json_response(
        "GET",
        "/api/tools/",
        {"data": [{"id": 1, "name": "public-tool"}]},
    )
    client = ToolboxApiClient(endpoint=api_server.base_url)

    response = client.get("tools/", query_params={"param": "value"})

    assert response == {"data": [{"id": 1, "name": "public-tool"}]}
    request = api_server.requests[-1]
    assert request.method == "GET"
    assert request.path == "/api/tools/"
    assert parse_qs(request.query) == {"param": ["value"], "lang": ["en"]}


def test_get_reuses_cached_json_response(
    api_server,
    monkeypatch,
    tmp_path: Path,
) -> None:
    import nextgis_toolbox.api.cache_manager as cache_manager_module

    monkeypatch.setattr(
        cache_manager_module.QStandardPaths,
        "writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )
    api_server.add_json_response(
        "GET",
        "/api/tools/public-tool",
        {"id": 1, "name": "public-tool"},
    )
    client = ToolboxApiClient(endpoint=api_server.base_url)

    first_response = client.get(
        "tools/public-tool",
        cache_key="tools/public-tool",
    )
    second_response = client.get(
        "tools/public-tool",
        cache_key="tools/public-tool",
    )

    assert first_response == {"id": 1, "name": "public-tool"}
    assert second_response == first_response
    assert [request.path for request in api_server.requests] == [
        "/api/tools/public-tool"
    ]


def test_get_falls_back_to_network_when_cache_read_fails(
    api_server,
    monkeypatch,
) -> None:
    api_server.add_json_response(
        "GET",
        "/api/tools/public-tool",
        {"id": 1, "name": "public-tool"},
    )
    client = ToolboxApiClient(endpoint=api_server.base_url)

    def raise_cache_error(*args, **kwargs):
        del args, kwargs
        raise NextgisToolboxCacheReadError("cache broken")

    monkeypatch.setattr(client._cache_manager, "get", raise_cache_error)

    response = client.get(
        "tools/public-tool",
        cache_key="tools/public-tool",
    )

    assert response == {"id": 1, "name": "public-tool"}
    assert [request.path for request in api_server.requests] == [
        "/api/tools/public-tool"
    ]


def test_post_sends_json_payload(api_server) -> None:
    api_server.add_json_response(
        "POST",
        "/api/tasks/",
        {"task_id": "task-1"},
    )
    client = ToolboxApiClient(endpoint=api_server.base_url)

    response = client.post("tasks/", {"tool": "hello"})

    assert response == {"task_id": "task-1"}
    request = api_server.requests[-1]
    assert request.method == "POST"
    assert request.path == "/api/tasks/"
    assert json.loads(request.body.decode("utf-8")) == {
        "tool": "hello",
    }


def test_post_does_not_resubmit_task_after_protocol_error(
    monkeypatch,
) -> None:
    client = ToolboxApiClient(endpoint="https://toolbox.nextgis.test")
    feedback = Mock()
    feedback.isCanceled.return_value = False

    failed_response = Mock()
    failed_response.error.return_value = (
        QNetworkReply.NetworkError.ProtocolInvalidOperationError
    )

    blocking_post = Mock(return_value=failed_response)
    network_manager = Mock()
    network_manager.blockingPost = blocking_post
    monkeypatch.setattr(
        client_module.QgsNetworkAccessManager,
        "instance",
        classmethod(lambda cls: network_manager),
    )

    # A failed POST may already have created a remote task. Retrying without
    # feedback is not a safe binding workaround and can submit it twice.
    with pytest.raises(ToolboxNetworkError):
        client.post("tasks/", {"tool": "hello"}, feedback=feedback)

    assert blocking_post.call_count == 1
    assert blocking_post.call_args.args[-1] is feedback


def test_upload_posts_binary_payload_and_parses_json_response(
    api_server,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "example.txt"
    source_path.write_text("payload", encoding="utf-8")
    api_server.add_json_response(
        "POST",
        "/api/upload",
        {"name": "example.txt", "local": {"uuid": "uuid-1"}, "s3": None},
    )
    client = ToolboxApiClient(endpoint=api_server.base_url)

    response = client.upload(source_path)

    assert response == {
        "name": "example.txt",
        "local": {"uuid": "uuid-1"},
        "s3": None,
    }
    request = api_server.requests[-1]
    assert request.method == "POST"
    assert request.path == "/api/upload"
    assert request.body == b"payload"
    assert parse_qs(request.query) == {
        "filename": ["example.txt"],
        "format": ["json"],
    }


def test_download_saves_file(api_server, tmp_path: Path) -> None:
    payload = b"downloaded-result"
    api_server.add_response(
        "HEAD",
        "/files/result.txt",
        b"",
        headers={
            "Content-Disposition": 'attachment; filename="server-result.txt"',
            "Content-Type": "text/plain",
        },
    )
    api_server.add_response(
        "GET",
        "/files/result.txt",
        payload,
        headers={
            "Content-Disposition": 'attachment; filename="server-result.txt"',
            "Content-Type": "text/plain",
        },
    )
    client = ToolboxApiClient(endpoint=api_server.base_url)
    destination_path = tmp_path / "downloads"

    saved_path = client.download(
        api_server.url("/files/result.txt"),
        destination_path,
    )

    assert saved_path == destination_path / "server-result.txt"
    assert saved_path.read_bytes() == payload
    assert api_server.requests[0].method == "HEAD"
    assert api_server.requests[1].method == "GET"
    assert api_server.requests[1].path == "/files/result.txt"


def test_download_wraps_directory_creation_errors(
    api_server,
    monkeypatch,
    tmp_path: Path,
) -> None:
    client = ToolboxApiClient(endpoint=api_server.base_url)
    api_server.add_response(
        "HEAD",
        "/files/result.txt",
        b"",
        headers={
            "Content-Disposition": 'attachment; filename="result.txt"',
            "Content-Type": "text/plain",
        },
    )

    def raise_os_error(
        self,
        mode: int = 0o777,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> None:
        del self, mode, parents, exist_ok
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "mkdir", raise_os_error)

    with pytest.raises(ToolboxFileWriteError) as error:
        client.download(
            api_server.url("/files/result.txt"),
            tmp_path / "downloads" / "result.txt",
        )

    assert error.value.detail is None
    assert any(
        note == "Technical details: permission denied"
        for note in getattr(error.value, "__notes__", [])
    )


def test_upload_file_wraps_read_errors(
    api_server,
    monkeypatch,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "example.txt"
    source_path.write_text("payload", encoding="utf-8")
    client = ToolboxApiClient(endpoint=api_server.base_url)

    def raise_os_error(self) -> bytes:
        del self
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "read_bytes", raise_os_error)

    with pytest.raises(ToolboxError) as error:
        client.upload(source_path)

    assert error.value.detail is None
    assert any(
        note == "Technical details: permission denied"
        for note in getattr(error.value, "__notes__", [])
    )


def test_cache_scope_changes_when_authentication_changes() -> None:
    client = ToolboxApiClient(endpoint="https://toolbox.nextgis.test")
    first_scope_path = client._cache_manager._metadata_path

    client.authentication = ToolboxTokenAuthentication(
        "11111111-1111-1111-1111-111111111111"
    )
    second_scope_path = client._cache_manager._metadata_path

    client.authentication = ToolboxTokenAuthentication(
        "22222222-2222-2222-2222-222222222222"
    )
    third_scope_path = client._cache_manager._metadata_path

    assert first_scope_path != second_scope_path
    assert second_scope_path != third_scope_path


def test_get_bytes_reuses_cached_binary_response(
    api_server,
    monkeypatch,
    tmp_path: Path,
) -> None:
    import nextgis_toolbox.api.cache_manager as cache_manager_module

    payload = b"help-image"
    monkeypatch.setattr(
        cache_manager_module.QStandardPaths,
        "writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )
    api_server.add_response(
        "GET",
        "/files/help.png",
        payload,
        headers={"Content-Type": "image/png"},
    )
    client = ToolboxApiClient(endpoint=api_server.base_url)

    first_response = client.get_bytes(
        api_server.url("/files/help.png"),
        cache_key="help-images/https://example.com/help.png",
    )
    second_response = client.get_bytes(
        api_server.url("/files/help.png"),
        cache_key="help-images/https://example.com/help.png",
    )

    assert first_response == payload
    assert second_response == payload
    assert [request.path for request in api_server.requests] == [
        "/files/help.png"
    ]
