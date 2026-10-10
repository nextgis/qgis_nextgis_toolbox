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

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union, cast

from qgis.PyQt.QtCore import pyqtSlot

from nextgis_toolbox.core.exceptions import (
    ToolboxError,
    ToolboxSortingError,
    ToolboxTagNotFoundError,
    ToolboxToolNotFoundError,
)
from nextgis_toolbox.core.logging import logger
from nextgis_toolbox.tools.api import ToolsApi
from nextgis_toolbox.tools.load_tools_task import (
    LoadToolsTask,
)
from nextgis_toolbox.tools.models import (
    SortBy,
    ToolboxTag,
    ToolboxTool,
    ToolsManagerState,
)
from nextgis_toolbox.tools.repository import (
    TagsRepository,
    ToolsRepository,
)
from nextgis_toolbox.tools.tools_interface import (
    ToolsInterface,
)

if TYPE_CHECKING:
    from nextgis_toolbox.nextgis_toolbox_interface import (
        NextgisToolboxInterface,
    )


class ToolsManager(ToolsInterface):
    """Feature-level manager for Toolbox tools."""

    def __init__(
        self,
        tools_api: ToolsApi,
        parent: Optional["NextgisToolboxInterface"] = None,
    ) -> None:
        """Initialize tools manager.

        :param tools_api: API for managing tools and tags.
        :param parent: Optional Qt parent.
        """
        super().__init__(parent)
        self._tools_api = tools_api
        self._tools_repository = ToolsRepository(tools_api)
        self._tags_repository = TagsRepository(tools_api)
        self._tools: List[ToolboxTool] = []
        self._tags: List[ToolboxTag] = []

        self._catalog_load_task: Optional[LoadToolsTask] = None

        self._state = ToolsManagerState.INITIALIZATION
        self._error: Optional[ToolboxError] = None

    @property
    def state(self) -> ToolsManagerState:
        return self._state

    @property
    def error(self) -> Optional[ToolboxError]:
        return self._error

    @property
    def is_semantic_enrichment_enabled(self) -> bool:
        return self._tools_repository.is_semantic_enrichment_enabled

    def set_api(self, tools_api: ToolsApi) -> None:
        """Set the API for managing tools and tags.

        :param tools_api: API for managing tools and tags.
        """
        self._tools_api = tools_api
        self._tools_repository.set_api(tools_api)
        self._tags_repository.set_api(tools_api)

    def set_semantic_enrichment_enabled(self, value: bool) -> None:
        self._tools_repository.set_semantic_enrichment_enabled(value)

    @pyqtSlot()
    def load(self) -> None:
        """Load all components of the tools feature."""

    @pyqtSlot()
    def unload(self) -> None:
        """Unload all components of the tools feature."""
        self._reset()
        self._set_state(ToolsManagerState.UNLOADED)

    def refresh(
        self,
        *,
        clear_cache: bool = False,
    ) -> None:
        """Refresh the tools catalog using the active runtime mode.

        :param clear_cache: Clear API cache before reloading.
        """
        plugin = cast("NextgisToolboxInterface", self.parent())
        use_async_refresh = (
            plugin is not None and plugin.mode == plugin.Mode.GUI
        )

        if use_async_refresh:
            self._start_catalog_load(clear_cache=clear_cache)
            return

        self._load_synchronously(clear_cache=clear_cache)

    def tools(
        self,
        *,
        sort_by: SortBy = SortBy.NAME,
    ) -> List[ToolboxTool]:
        """Return cached Toolbox tools with resolved tags.

        :returns: List of cached tool models.
        """
        if sort_by == SortBy.NAME:
            return self._tools

        if sort_by == SortBy.ID:
            return self._sort_tools(self._tools, sort_by=SortBy.ID)

        if sort_by == SortBy.ALIAS:
            return self._sort_tools(self._tools, sort_by=SortBy.ALIAS)

        raise ToolboxSortingError("tool", sort_by)

    def tool(
        self,
        *,
        tool_id: Optional[int] = None,
        name: Optional[str] = None,
    ) -> ToolboxTool:
        """Return one cached Toolbox tool by identifier."""
        if (tool_id is None) == (name is None):
            raise ValueError(
                "Exactly one of 'tool_id' or 'name' must be provided."
            )

        if tool_id is not None:
            for tool in self._tools:
                if tool.id == tool_id:
                    return tool

            raise ToolboxToolNotFoundError(tool_id=tool_id)

        name = str(name)
        for tool in self._tools:
            if tool.name == name:
                return tool

        raise ToolboxToolNotFoundError(name=name)

    def find_tools(
        self,
        *,
        tool_id: Optional[Union[int, List[int]]] = None,
        name: Optional[Union[str, List[str]]] = None,
        tag: Optional[
            Union[int, ToolboxTag, List[Union[int, ToolboxTag]]]
        ] = None,
        is_featured: Optional[bool] = None,
        is_favorite: Optional[bool] = None,
    ) -> List[ToolboxTool]:
        """Return cached tools matching a single search criterion."""
        criteria_count = sum(
            value is not None
            for value in (
                tool_id,
                name,
                tag,
                is_featured,
                is_favorite,
            )
        )
        if criteria_count != 1:
            raise ValueError("Exactly one search criterion must be provided.")

        if tool_id is not None:
            tool_ids = set(self._normalize_int_list(tool_id))
            missing_tool_ids = [
                current_tool_id
                for current_tool_id in tool_ids
                if not any(tool.id == current_tool_id for tool in self._tools)
            ]
            if missing_tool_ids:
                raise ToolboxToolNotFoundError(tool_id=missing_tool_ids[0])

            return [tool for tool in self._tools if tool.id in tool_ids]

        if name is not None:
            tool_names = set(self._normalize_str_list(name))
            missing_tool_names = [
                current_tool_name
                for current_tool_name in tool_names
                if not any(
                    tool.name == current_tool_name for tool in self._tools
                )
            ]
            if missing_tool_names:
                raise ToolboxToolNotFoundError(name=missing_tool_names[0])

            return [tool for tool in self._tools if tool.name in tool_names]

        if is_featured is not None:
            return [
                tool for tool in self._tools if tool.is_featured is is_featured
            ]

        if is_favorite is not None:
            return [
                tool for tool in self._tools if tool.is_favorite is is_favorite
            ]

        tag_ids = self._resolve_tag_ids(tag)
        matching_tag_ids = set(tag_ids)

        return [
            tool
            for tool in self._tools
            if any(tag.id in matching_tag_ids for tag in tool.tags)
        ]

    def set_tool_favorite(
        self,
        tool_name: str,
        is_favorite: bool,
        *,
        sync_remote: bool = True,
    ) -> None:
        tool = self.tool(name=tool_name)
        if tool.is_favorite is is_favorite and not sync_remote:
            return

        tool.is_favorite = is_favorite

        if not sync_remote:
            return

        self._tools_repository.set_tool_favorite(tool_name, is_favorite)

    def tags(
        self,
        *,
        sort_by: SortBy = SortBy.ALIAS,
    ) -> List[ToolboxTag]:
        """Return cached Toolbox tags.

        :returns: List of cached tag models.
        """
        if sort_by == SortBy.ALIAS:
            return self._tags

        if sort_by == SortBy.ID:
            return self._sort_tags(self._tags, sort_by=SortBy.ID)

        raise ToolboxSortingError("tag", sort_by)

    def tag(self, tag_id: int) -> ToolboxTag:
        """Return one cached Toolbox tag by identifier."""
        for tag in self._tags:
            if tag.id == tag_id:
                return tag

        raise ToolboxTagNotFoundError(tag_id=tag_id)

    def _apply_catalog(
        self,
        tags: List[ToolboxTag],
        tools: List[ToolboxTool],
    ) -> None:
        self._tags = self._sort_tags(tags, sort_by=SortBy.ALIAS)
        self._tools = self._sort_tools(tools, sort_by=SortBy.NAME)

        self._assign_tags_to_tools()

    def _assign_tags_to_tools(self) -> None:
        """Resolve cached tag identifiers to cached tag models."""
        tag_by_id: Dict[int, ToolboxTag] = {tag.id: tag for tag in self._tags}
        tool_ids_by_tag_id: Dict[int, List[int]] = {
            tag.id: [] for tag in self._tags
        }

        for tool in self._tools:
            tool.tags = [
                tag_by_id[tag_id]
                for tag_id in tool.tag_ids
                if tag_id in tag_by_id
            ]

            for tag in tool.tags:
                tool_ids_by_tag_id.setdefault(tag.id, []).append(tool.id)

        for tag in self._tags:
            tag.tool_ids = tool_ids_by_tag_id.get(tag.id, [])

    def _resolve_tag_ids(
        self,
        value: Optional[Union[int, ToolboxTag, List[Union[int, ToolboxTag]]]],
    ) -> List[int]:
        """Normalize tag search criteria to tag identifiers."""
        if value is None:
            return []

        tag_values = self._normalize_to_list(value)
        tag_ids: List[int] = []

        for tag_value in tag_values:
            if isinstance(tag_value, ToolboxTag):
                tag_id = tag_value.id
            else:
                tag_id = int(tag_value)

            if not any(tag.id == tag_id for tag in self._tags):
                raise ToolboxTagNotFoundError(tag_id=tag_id)

            tag_ids.append(tag_id)

        return tag_ids

    def _reset(self) -> None:
        if self._catalog_load_task is not None:
            self._catalog_load_task.cancel()
            self._catalog_load_task = None

        self._tools = []
        self._tags = []

    def _load_synchronously(self, *, clear_cache: bool = False) -> None:
        if clear_cache:
            self._tools_api.invalidate_cache()

        self._reset()

        self._set_state(ToolsManagerState.LOADING)

        try:
            self._apply_catalog(
                self._tags_repository.fetch_tags(),
                self._tools_repository.fetch_tools(),
            )

        except ToolboxError as error:
            logger.error(
                "Failed to load NextGIS Toolbox catalog: %s",
                str(error),
                exc_info=error,
            )
            self._reset()
            self._set_state(ToolsManagerState.ERROR, error)
            return

        except Exception as error:
            logger.exception(
                "Failed to load NextGIS Toolbox catalog",
                exc_info=error,
            )
            self._reset()

            catalog_error = ToolboxError(
                "Failed to load NextGIS Toolbox catalog."
            )
            catalog_error.__cause__ = error

            self._set_state(ToolsManagerState.ERROR, catalog_error)
            return

        self._set_state(ToolsManagerState.LOADED)

    def _start_catalog_load(self, *, clear_cache: bool = False) -> None:
        if clear_cache:
            self._tools_api.invalidate_cache()

        self._reset()

        load_task = LoadToolsTask(
            tags_repository=self._tags_repository,
            tools_repository=self._tools_repository,
            on_finished=self._on_catalog_load_finished,
        )
        load_task.progressChanged.connect(self.loading_progress_changed.emit)
        self._catalog_load_task = load_task

        self._set_state(ToolsManagerState.LOADING)

        plugin = cast("NextgisToolboxInterface", self.parent())
        plugin.qgis_tasks_manager.addTask(load_task)

    def _on_catalog_load_finished(
        self,
        load_task: LoadToolsTask,
        result: bool,
    ) -> None:
        if load_task is not self._catalog_load_task:
            return

        self._catalog_load_task = None

        if load_task.isCanceled():
            self._reset()
            self._set_state(
                ToolsManagerState.ERROR,
                ToolboxError("Tools catalog load was canceled."),
            )
            return

        elif load_task.error is not None:
            self._reset()
            self._set_state(ToolsManagerState.ERROR, load_task.error)
            self._notify_load_error(load_task.error)
            return

        elif not result:
            self._reset()
            error = ToolboxError("Failed to load tools catalog.")
            self._set_state(ToolsManagerState.ERROR, error)
            self._notify_load_error(error)
            return

        self._apply_catalog(load_task.tags, load_task.tools)
        self._set_state(ToolsManagerState.LOADED)

    def _notify_load_error(self, error: ToolboxError) -> None:
        plugin = cast("NextgisToolboxInterface", self.parent())
        if plugin is None:
            return

        plugin.notifier.display_exception(error)

    def _normalize_to_list(
        self, value: Any
    ) -> List[Union[int, str, ToolboxTag]]:
        """Normalize scalar or list search values to a list."""
        if isinstance(value, list):
            return value

        return [value]

    def _normalize_int_list(self, value: Union[int, List[int]]) -> List[int]:
        if isinstance(value, list):
            return value

        return [value]

    def _normalize_str_list(
        self,
        value: Union[str, List[str]],
    ) -> List[str]:
        if isinstance(value, list):
            return value

        return [value]

    def _sort_tags(
        self,
        tags: List[ToolboxTag],
        *,
        sort_by: SortBy,
    ) -> List[ToolboxTag]:
        """Return tags sorted using the requested key."""
        if sort_by == SortBy.ID:
            return sorted(tags, key=lambda tag: tag.id)

        if sort_by == SortBy.ALIAS:
            return sorted(tags, key=lambda tag: tag.alias)

        raise ToolboxSortingError("tag", sort_by)

    def _sort_tools(
        self,
        tools: List[ToolboxTool],
        *,
        sort_by: SortBy,
    ) -> List[ToolboxTool]:
        """Return tools sorted using the requested key."""
        if sort_by == SortBy.ID:
            return sorted(tools, key=lambda tool: tool.id)

        if sort_by == SortBy.NAME:
            return sorted(tools, key=lambda tool: tool.name)

        if sort_by == SortBy.ALIAS:
            return sorted(tools, key=lambda tool: tool.alias)

        raise ToolboxSortingError("tool", sort_by)

    def _set_state(
        self,
        state: ToolsManagerState,
        error: Optional[ToolboxError] = None,
    ) -> None:
        if self._state == state and self._error == error:
            return

        self._state = state
        self._error = error

        self.state_changed.emit(state)
