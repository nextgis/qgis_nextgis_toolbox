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

from typing import cast
from unittest.mock import Mock

import pytest
from qgis.core import QgsTask
from qgis.PyQt.QtCore import QObject

import nextgis_toolbox.tools.tools_manager as tools_manager_module
from nextgis_toolbox.core.exceptions import (
    ToolboxError,
    ToolboxSortingError,
    ToolboxTagNotFoundError,
    ToolboxToolNotFoundError,
)
from nextgis_toolbox.tools.load_tools_task import LoadToolsTask
from nextgis_toolbox.tools.models import (
    SortBy,
    ToolboxTag,
    ToolboxTool,
)
from nextgis_toolbox.tools.tools_manager import ToolsManager


def build_tool(
    tool_id: int,
    name: str,
    alias: str,
    tag_ids,
    *,
    is_favorite: bool = False,
    is_featured: bool = False,
) -> ToolboxTool:
    return ToolboxTool(
        alias=alias,
        can_run=False,
        description=f"Description for {name}",
        id=tool_id,
        is_dev=False,
        is_featured=is_featured,
        is_free=True,
        is_favorite=is_favorite,
        is_new=False,
        name=name,
        tag_ids=tag_ids,
    )


def test_tools_manager_loads_models_and_supports_lookups(qgis_app) -> None:
    del qgis_app

    alpha_tag = ToolboxTag(id=2, alias="Alpha", icon="", tool_ids=[])
    beta_tag = ToolboxTag(id=1, alias="Beta", icon="", tool_ids=[])
    zebra_tool = build_tool(20, "zebra", "Zebra", [1], is_favorite=True)
    alpha_tool = build_tool(
        10,
        "alpha",
        "Alpha",
        [1, 2],
        is_featured=True,
    )
    manager = ToolsManager(Mock())
    manager._tags_repository.fetch_tags = Mock(
        return_value=[beta_tag, alpha_tag]
    )
    manager._tools_repository.fetch_tools = Mock(
        return_value=[zebra_tool, alpha_tool]
    )

    manager.load()

    assert [tag.alias for tag in manager.tags()] == ["Alpha", "Beta"]
    assert [tag.id for tag in manager.tags(sort_by=SortBy.ID)] == [
        1,
        2,
    ]
    assert [tool.name for tool in manager.tools()] == ["alpha", "zebra"]
    assert [tool.id for tool in manager.tools(sort_by=SortBy.ID)] == [
        10,
        20,
    ]
    assert [tool.alias for tool in manager.tools(sort_by=SortBy.ALIAS)] == [
        "Alpha",
        "Zebra",
    ]
    assert manager.tool(tool_id=10) is alpha_tool
    assert manager.tool(name="zebra") is zebra_tool
    assert manager.tag(2) is alpha_tag
    assert manager.find_tools(tool_id=20) == [zebra_tool]
    assert manager.find_tools(name=["alpha", "zebra"]) == [
        alpha_tool,
        zebra_tool,
    ]
    assert manager.find_tools(is_featured=True) == [alpha_tool]
    assert manager.find_tools(is_favorite=True) == [zebra_tool]
    assert manager.find_tools(tag=alpha_tag) == [alpha_tool]
    assert manager.find_tools(tag=[1, alpha_tag]) == [alpha_tool, zebra_tool]
    assert alpha_tag.tool_ids == [10]
    assert beta_tag.tool_ids == [10, 20]


def test_tools_manager_refresh_emits_loading_signals(qgis_app) -> None:
    del qgis_app

    tag = ToolboxTag(id=1, alias="General", icon="", tool_ids=[])
    tool = build_tool(1, "alpha", "Alpha", [1])
    manager = ToolsManager(Mock())
    manager._tags_repository.fetch_tags = Mock(return_value=[tag])
    manager._tools_repository.fetch_tools = Mock(return_value=[tool])

    started = []
    finished = []
    manager.catalog_loading_started.connect(started.append)
    manager.catalog_loading_finished.connect(
        lambda is_successful, error_message: finished.append(
            (is_successful, error_message)
        )
    )

    manager.refresh()

    assert started == [None]
    assert finished == [(True, "")]
    assert manager.tools() == [tool]


def test_tools_manager_validates_lookup_arguments(qgis_app) -> None:
    del qgis_app

    manager = ToolsManager(Mock())

    with pytest.raises(ValueError):
        manager.tool()

    with pytest.raises(ValueError):
        manager.tool(tool_id=1, name="alpha")

    with pytest.raises(ValueError):
        manager.find_tools()

    with pytest.raises(ValueError):
        manager.find_tools(tool_id=1, name="alpha")

    with pytest.raises(ValueError):
        manager.find_tools(name="alpha", is_favorite=True)


def test_tools_manager_raises_for_missing_tools_and_tags(qgis_app) -> None:
    del qgis_app

    tag = ToolboxTag(id=1, alias="General", icon="", tool_ids=[])
    tool = build_tool(1, "alpha", "Alpha", [1])
    manager = ToolsManager(Mock())
    manager._tags_repository.fetch_tags = Mock(return_value=[tag])
    manager._tools_repository.fetch_tools = Mock(return_value=[tool])

    manager.load()

    with pytest.raises(ToolboxToolNotFoundError):
        manager.tool(tool_id=99)

    with pytest.raises(ToolboxToolNotFoundError):
        manager.find_tools(name="missing-tool")

    with pytest.raises(ToolboxTagNotFoundError):
        manager.tag(99)

    with pytest.raises(ToolboxTagNotFoundError):
        manager.find_tools(tag=99)


def test_tools_manager_raises_for_unsupported_sorting(qgis_app) -> None:
    del qgis_app

    manager = ToolsManager(Mock())

    with pytest.raises(ToolboxSortingError):
        manager.tools(sort_by=cast(SortBy, "unexpected"))

    with pytest.raises(ToolboxSortingError):
        manager.tags(sort_by=cast(SortBy, "unexpected"))


def test_tools_manager_updates_favorite_state(qgis_app) -> None:
    del qgis_app

    tag = ToolboxTag(id=1, alias="General", icon="", tool_ids=[])
    tool = build_tool(1, "alpha", "Alpha", [1])
    manager = ToolsManager(Mock())
    manager._tags_repository.fetch_tags = Mock(return_value=[tag])
    manager._tools_repository.fetch_tools = Mock(return_value=[tool])

    manager.load()
    manager._tools_repository.set_tool_favorite = Mock()

    manager.set_tool_favorite("alpha", True)

    assert manager.tool(name="alpha").is_favorite is True
    manager._tools_repository.set_tool_favorite.assert_called_once_with(
        "alpha",
        True,
    )


def test_tools_manager_cancels_previous_catalog_load_before_refreshing(
    qgis_app,
    monkeypatch,
) -> None:
    del qgis_app

    class FakeSignal:
        def connect(self, _slot) -> None:
            return None

    class FakeLoadToolsTask:
        def __init__(self, **_kwargs) -> None:
            self.progressChanged = FakeSignal()
            self.cancel_calls = 0

        def cancel(self) -> None:
            self.cancel_calls += 1

    class FakePlugin(QObject):
        class Mode:
            GUI = object()

        def __init__(self) -> None:
            super().__init__()
            self.mode = self.Mode.GUI
            self.qgis_tasks_manager = Mock()

    plugin = FakePlugin()
    manager = ToolsManager(Mock(), parent=plugin)  # type: ignore[arg-type]
    monkeypatch.setattr(
        tools_manager_module,
        "LoadToolsTask",
        FakeLoadToolsTask,
    )

    manager.refresh()
    previous_task = manager._catalog_load_task
    manager.refresh(clear_cache=True)

    assert isinstance(previous_task, FakeLoadToolsTask)
    assert previous_task.cancel_calls == 1
    assert plugin.qgis_tasks_manager.addTask.call_count == 2


def test_tools_manager_reports_active_catalog_load_error(qgis_app) -> None:
    del qgis_app

    class FakePlugin(QObject):
        def __init__(self) -> None:
            super().__init__()
            self.notifier = Mock()

    class FailedTask:
        def __init__(self, error: ToolboxError) -> None:
            self.error = error
            self.tags = []
            self.tools = []

        def cancel(self) -> None:
            return None

        def isCanceled(self) -> bool:  # noqa: N802
            return False

    plugin = FakePlugin()
    manager = ToolsManager(Mock(), parent=plugin)  # type: ignore[arg-type]
    error = ToolboxError("Catalog request failed")
    task = FailedTask(error)
    manager._catalog_load_task = task  # type: ignore[assignment]

    manager._on_catalog_load_finished(task, False)  # type: ignore[arg-type]

    assert manager.error is error
    plugin.notifier.display_exception.assert_called_once_with(error)


def test_catalog_load_task_is_canceled_without_prompt(qgis_app) -> None:
    del qgis_app

    task = LoadToolsTask(Mock(), Mock(), Mock())

    assert task.flags() & QgsTask.Flag.CancelWithoutPrompt
