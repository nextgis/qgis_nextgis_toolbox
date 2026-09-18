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
from threading import Lock
from time import sleep
from unittest.mock import Mock

import nextgis_toolbox.api.cache_manager as cache_manager_module
from nextgis_toolbox.api.client import ToolboxApiClient
from nextgis_toolbox.settings.nextgis_toolbox_settings import (
    NextgisToolboxSettings,
)
from nextgis_toolbox.tools.api import ToolsApi
from nextgis_toolbox.tools.repository import (
    TagsRepository,
    ToolsRepository,
)
from nextgis_toolbox.tools.semantics import ToolSemanticsCatalog


def build_tool_preset(alias: str = "Demo preset") -> dict:
    return {
        "alias": alias,
        "inputs": {"source": "/tmp/demo-input.tif"},
        "outputs": {"result": "/tmp/demo-output.tif"},
    }


def build_tool_summary(
    tool_id: int,
    name: str,
    *,
    alias: str,
    is_dev: bool = False,
) -> dict:
    return {
        "alias": alias,
        "can_run": False,
        "description": f"Description for {name}",
        "id": tool_id,
        "is_dev": is_dev,
        "is_favorite": False,
        "is_featured": False,
        "is_free": True,
        "is_new": False,
        "name": name,
        "tags": [10],
    }


def build_tool_detail(tool_summary: dict) -> dict:
    return {
        **tool_summary,
        "inputs": [
            {
                "alias": "Source",
                "description": "Input file",
                "name": "source",
                "required": True,
                "type": "file",
            }
        ],
        "outputs": [
            {
                "alias": "Result",
                "description": "Output file",
                "name": "result",
                "required": True,
                "type": "file",
            }
        ],
    }


def test_tools_api_fetches_lists_and_detail(api_server) -> None:
    public_tool = build_tool_summary(1, "public-tool", alias="Public")
    api_server.add_json_response(
        "GET",
        "/api/tools/",
        {"data": [public_tool]},
    )
    api_server.add_json_response(
        "GET",
        "/api/tags/",
        {
            "data": [
                {
                    "alias": "General",
                    "icon": "",
                    "id": 10,
                    "tools": [1],
                }
            ]
        },
    )
    api_server.add_json_response(
        "GET",
        "/api/tools/public-tool",
        build_tool_detail(public_tool),
    )
    api_server.add_json_response(
        "GET",
        "/api/tools/public-tool/presets",
        {"items": [build_tool_preset()]},
    )
    client = ToolboxApiClient(endpoint=api_server.base_url)
    api = ToolsApi(client)

    assert api.fetch_tools() == [public_tool]
    assert api.fetch_tags() == [
        {"alias": "General", "icon": "", "id": 10, "tools": [1]}
    ]
    assert api.fetch_tool("public-tool") == build_tool_detail(public_tool)
    assert api.fetch_tool_presets("public-tool") == [build_tool_preset()]


def test_tools_api_passes_feedback_to_catalog_requests(qgis_app) -> None:
    del qgis_app

    client = Mock()
    client.get.side_effect = [
        {"data": []},
        {"data": []},
        {},
        {"items": []},
    ]
    api = ToolsApi(client)
    feedback = Mock()

    api.fetch_tools(feedback)
    api.fetch_tags(feedback)
    api.fetch_tool("tool", feedback)
    api.fetch_tool_presets("tool", feedback)

    assert client.get.call_args_list == [
        (("tools/",), {"feedback": feedback}),
        (("tags/",), {"feedback": feedback}),
        (("tools/tool",), {"feedback": feedback, "cache_key": "tools/tool"}),
        (
            ("tools/tool/presets",),
            {"feedback": feedback, "cache_key": "tools/tool/presets"},
        ),
    ]


def test_tools_api_sets_tool_favorite(api_server) -> None:
    api_server.add_json_response(
        "POST",
        "/api/tools/public-tool/favorite",
        {"status": "updated"},
    )
    client = ToolboxApiClient(endpoint=api_server.base_url)
    api = ToolsApi(client)

    response = api.set_tool_favorite("public-tool", True)

    assert response == {"status": "updated"}
    assert json.loads(api_server.requests[-1].body.decode("utf-8")) == {
        "new_value": 1
    }


def test_tools_repository_keeps_public_tools_when_can_run_is_false(
    api_server,
) -> None:
    public_tool = build_tool_summary(1, "public-tool", alias="Public")
    api_server.add_json_response(
        "GET",
        "/api/tools/",
        {"data": [public_tool]},
    )
    api_server.add_json_response(
        "GET",
        "/api/tools/public-tool",
        build_tool_detail(public_tool),
    )
    api_server.add_json_response(
        "GET",
        "/api/tools/public-tool/presets",
        {"items": []},
    )
    settings = NextgisToolboxSettings()
    settings.is_developer_mode = False
    repository = ToolsRepository(
        ToolsApi(ToolboxApiClient(endpoint=api_server.base_url))
    )

    tools = repository.fetch_tools()

    assert len(tools) == 1
    assert tools[0].name == "public-tool"
    assert tools[0].can_run is False
    assert tools[0].is_favorite is False
    assert tools[0].presets == []
    assert [parameter.name for parameter in tools[0].inputs] == ["source"]
    assert [parameter.name for parameter in tools[0].outputs] == ["result"]


def test_tools_repository_includes_dev_tools_in_developer_mode(
    api_server,
) -> None:
    public_tool = build_tool_summary(1, "public-tool", alias="Public")
    dev_tool = build_tool_summary(
        2,
        "developer-tool",
        alias="Developer",
        is_dev=True,
    )
    api_server.add_json_response(
        "GET",
        "/api/tools/",
        {"data": [public_tool, dev_tool]},
    )
    api_server.add_json_response(
        "GET",
        "/api/tools/public-tool",
        build_tool_detail(public_tool),
    )
    api_server.add_json_response(
        "GET",
        "/api/tools/public-tool/presets",
        {"items": []},
    )
    api_server.add_json_response(
        "GET",
        "/api/tools/developer-tool",
        build_tool_detail(dev_tool),
    )
    api_server.add_json_response(
        "GET",
        "/api/tools/developer-tool/presets",
        {"items": []},
    )
    settings = NextgisToolboxSettings()
    settings.is_developer_mode = True
    repository = ToolsRepository(
        ToolsApi(ToolboxApiClient(endpoint=api_server.base_url))
    )

    tools = repository.fetch_tools()

    assert [tool.name for tool in tools] == [
        "public-tool",
        "developer-tool",
    ]


def test_tools_repository_fetches_four_tools_concurrently() -> None:
    tool_summaries = [
        build_tool_summary(
            tool_id,
            f"tool-{tool_id}",
            alias=f"Tool {tool_id}",
        )
        for tool_id in range(1, 6)
    ]
    repository = ToolsRepository(
        Mock(),
        is_semantic_enrichment_enabled=False,
    )
    active_requests = 0
    maximum_active_requests = 0
    request_lock = Lock()

    def fetch_tool_details(tool_name: str, feedback=None) -> dict:
        del feedback
        nonlocal active_requests, maximum_active_requests

        with request_lock:
            active_requests += 1
            maximum_active_requests = max(
                maximum_active_requests,
                active_requests,
            )

        try:
            sleep(0.05)
        finally:
            with request_lock:
                active_requests -= 1

        tool_summary = next(
            tool for tool in tool_summaries if tool["name"] == tool_name
        )
        return build_tool_detail(tool_summary)

    repository._fetch_tool_details = Mock(side_effect=fetch_tool_details)
    repository._fetch_tool_presets = Mock(return_value=[])

    tools = repository._fetch_all_tools_data(
        tool_summaries,
        feedback=None,
        is_developer_mode=False,
    )

    assert maximum_active_requests == 4
    assert [tool.name for tool in tools] == [
        "tool-1",
        "tool-2",
        "tool-3",
        "tool-4",
        "tool-5",
    ]


def test_tags_repository_returns_tag_models(api_server) -> None:
    api_server.add_json_response(
        "GET",
        "/api/tags/",
        {
            "data": [
                {
                    "alias": "General",
                    "icon": "",
                    "id": 10,
                    "tools": [1],
                }
            ]
        },
    )
    repository = TagsRepository(
        ToolsApi(ToolboxApiClient(endpoint=api_server.base_url))
    )

    tags = repository.fetch_tags()

    assert len(tags) == 1
    assert tags[0].id == 10
    assert tags[0].alias == "General"
    assert tags[0].tool_ids == [1]


def test_tools_repository_reuses_cached_tool_details_and_presets(
    api_server,
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        cache_manager_module.QStandardPaths,
        "writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )

    public_tool = build_tool_summary(1, "public-tool", alias="Public")
    api_server.add_json_response(
        "GET",
        "/api/tools/",
        {"data": [public_tool]},
    )
    api_server.add_json_response(
        "GET",
        "/api/tools/public-tool",
        build_tool_detail(public_tool),
    )
    api_server.add_json_response(
        "GET",
        "/api/tools/public-tool/presets",
        {"items": [build_tool_preset()]},
    )

    repository = ToolsRepository(
        ToolsApi(ToolboxApiClient(endpoint=api_server.base_url)),
    )

    repository.fetch_tools()

    api_server.add_json_response(
        "GET",
        "/api/tools/",
        {"data": [public_tool]},
    )
    tools = repository.fetch_tools()

    assert [request.path for request in api_server.requests].count(
        "/api/tools/public-tool"
    ) == 1
    assert [request.path for request in api_server.requests].count(
        "/api/tools/public-tool/presets"
    ) == 1
    assert tools[0].name == "public-tool"
    assert tools[0].presets[0].alias == "Demo preset"
    assert [parameter.name for parameter in tools[0].inputs] == ["source"]


def test_tools_repository_updates_cached_favorite_state(
    api_server,
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        cache_manager_module.QStandardPaths,
        "writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )

    public_tool = build_tool_summary(1, "public-tool", alias="Public")
    api_server.add_json_response(
        "GET",
        "/api/tools/",
        {"data": [public_tool]},
    )
    api_server.add_json_response(
        "GET",
        "/api/tools/public-tool",
        build_tool_detail(public_tool),
    )
    api_server.add_json_response(
        "GET",
        "/api/tools/public-tool/presets",
        {"items": []},
    )
    api_server.add_json_response(
        "POST",
        "/api/tools/public-tool/favorite",
        {"status": "updated"},
    )

    client = ToolboxApiClient(endpoint=api_server.base_url)
    repository = ToolsRepository(
        ToolsApi(client),
    )

    repository.fetch_tools()
    repository.set_tool_favorite("public-tool", True)

    updated_details = build_tool_detail(
        {
            **public_tool,
            "is_favorite": True,
        }
    )
    api_server.add_json_response(
        "GET",
        "/api/tools/public-tool",
        updated_details,
    )

    refreshed_details = repository._fetch_tool_details("public-tool")
    favorite_request = next(
        request for request in api_server.requests if request.method == "POST"
    )

    assert refreshed_details["is_favorite"] is True
    assert json.loads(favorite_request.body.decode("utf-8")) == {
        "new_value": 1
    }


def test_tools_repository_applies_semantic_overlays_when_enabled(
    api_server,
) -> None:
    public_tool = build_tool_summary(1, "public-tool", alias="Public")
    api_server.add_json_response(
        "GET",
        "/api/tools/",
        {"data": [public_tool]},
    )
    api_server.add_json_response(
        "GET",
        "/api/tools/public-tool",
        build_tool_detail(public_tool),
    )
    api_server.add_json_response(
        "GET",
        "/api/tools/public-tool/presets",
        {"items": []},
    )

    catalog = ToolSemanticsCatalog(
        {
            "public-tool": {
                "inputs": {
                    "source": {
                        "kind": "style",
                        "constraints": {"style_type": "qml"},
                    }
                },
                "outputs": {
                    "result": {
                        "kind": "layer",
                        "constraints": {
                            "layer_type": "vector",
                            "file_count": "single",
                        },
                    }
                },
            }
        }
    )
    repository = ToolsRepository(
        ToolsApi(ToolboxApiClient(endpoint=api_server.base_url)),
        is_semantic_enrichment_enabled=True,
        semantics_catalog=catalog,
    )

    tools = repository.fetch_tools()

    assert tools[0].inputs[0].input_semantic is not None
    assert tools[0].inputs[0].input_semantic.kind == "style"
    assert tools[0].outputs[0].output_semantic is not None
    assert tools[0].outputs[0].output_semantic.kind == "layer"


def test_tools_repository_skips_semantic_overlays_when_disabled(
    api_server,
) -> None:
    public_tool = build_tool_summary(1, "public-tool", alias="Public")
    api_server.add_json_response(
        "GET",
        "/api/tools/",
        {"data": [public_tool]},
    )
    api_server.add_json_response(
        "GET",
        "/api/tools/public-tool",
        build_tool_detail(public_tool),
    )
    api_server.add_json_response(
        "GET",
        "/api/tools/public-tool/presets",
        {"items": []},
    )

    catalog = ToolSemanticsCatalog(
        {
            "public-tool": {
                "inputs": {
                    "source": {
                        "kind": "style",
                        "constraints": {"style_type": "qml"},
                    }
                }
            }
        }
    )
    repository = ToolsRepository(
        ToolsApi(ToolboxApiClient(endpoint=api_server.base_url)),
        is_semantic_enrichment_enabled=False,
        semantics_catalog=catalog,
    )

    tools = repository.fetch_tools()

    assert tools[0].inputs[0].input_semantic is None


def test_default_semantic_resource_catalog_enriches_tool_data() -> None:
    catalog = ToolSemanticsCatalog()

    enriched = catalog.enrich_tool_data(
        {
            "name": "add_regions",
            "inputs": [{"name": "userfile"}],
            "outputs": [{"name": "result"}],
        }
    )

    assert enriched["inputs"][0]["input_semantic"]["kind"] == "layer"
    assert enriched["outputs"][0]["output_semantic"]["kind"] == "layer"


def test_tools_repository_keeps_summary_fields_fresh_when_using_cache(
    api_server,
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        cache_manager_module.QStandardPaths,
        "writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )

    original_tool = build_tool_summary(1, "public-tool", alias="Public")
    cached_details = build_tool_detail(original_tool)

    api_server.add_json_response(
        "GET",
        "/api/tools/",
        {"data": [original_tool]},
    )
    api_server.add_json_response(
        "GET",
        "/api/tools/public-tool",
        cached_details,
    )
    api_server.add_json_response(
        "GET",
        "/api/tools/public-tool/presets",
        {"items": []},
    )

    repository = ToolsRepository(
        ToolsApi(ToolboxApiClient(endpoint=api_server.base_url)),
    )
    repository.fetch_tools()

    updated_summary = build_tool_summary(
        1,
        "public-tool",
        alias="Updated Public",
    )
    updated_summary["description"] = "Updated description"
    merged_tool_data = repository._merge_tool_data(
        updated_summary,
        cached_details,
        [build_tool_preset()],
    )

    assert merged_tool_data["alias"] == "Updated Public"
    assert merged_tool_data["description"] == "Updated description"
    assert merged_tool_data["presets"][0]["alias"] == "Demo preset"
    assert [parameter["name"] for parameter in merged_tool_data["inputs"]] == [
        "source"
    ]
