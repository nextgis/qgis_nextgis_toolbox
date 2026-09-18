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

from concurrent.futures import (
    FIRST_COMPLETED,
    Future,
    ThreadPoolExecutor,
    wait,
)
from typing import Any, Dict, List, Optional, Tuple

from qgis.core import QgsFeedback

from nextgis_toolbox.core.logging import logger
from nextgis_toolbox.core.utils import PluginRuntimeProfiler
from nextgis_toolbox.settings.nextgis_toolbox_settings import (
    NextgisToolboxSettings,
)
from nextgis_toolbox.tools.api import ToolsApi
from nextgis_toolbox.tools.models import (
    ToolboxTag,
    ToolboxTool,
)
from nextgis_toolbox.tools.semantics import ToolSemanticsCatalog


class ToolsRepository:
    """Repository for Toolbox tool models."""

    _MAX_CONCURRENT_TOOL_REQUESTS = 4

    def __init__(
        self,
        api: ToolsApi,
        *,
        is_semantic_enrichment_enabled: Optional[bool] = None,
        semantics_catalog: Optional[ToolSemanticsCatalog] = None,
    ) -> None:
        """Initialize repository.

        :param api: Tools API gateway.
        """
        self._api = api
        if is_semantic_enrichment_enabled is None:
            is_semantic_enrichment_enabled = NextgisToolboxSettings().is_experimental_qgis_integration_enabled
        self._is_semantic_enrichment_enabled = is_semantic_enrichment_enabled
        self._semantics_catalog = semantics_catalog or ToolSemanticsCatalog()

    @property
    def is_semantic_enrichment_enabled(self) -> bool:
        return self._is_semantic_enrichment_enabled

    def set_semantic_enrichment_enabled(self, value: bool) -> None:
        self._is_semantic_enrichment_enabled = value

    def set_api(self, api: ToolsApi) -> None:
        """Set API gateway instance.

        :param api: Tools API gateway.
        """
        self._api = api

    def fetch_tools(
        self, feedback: Optional[QgsFeedback] = None
    ) -> List[ToolboxTool]:
        """Fetch tool models from the API.

        :returns: List of Toolbox tool models.
        """
        logger.debug("Fetching Toolbox tools catalog")

        is_developer_mode = NextgisToolboxSettings().is_developer_mode

        unfiltered_tools: List[Dict[str, Any]] = []
        with PluginRuntimeProfiler.download("fetching tools summaries"):
            unfiltered_tools = self._api.fetch_tools()

        self._set_progress(feedback, 5)

        logger.debug(f"Fetched {len(unfiltered_tools)} tools")

        tools = []
        with PluginRuntimeProfiler.download(
            "fetching tools details and presets"
        ):
            tools = self._fetch_all_tools_data(
                unfiltered_tools,
                feedback,
                is_developer_mode,
            )

        self._set_progress(feedback, 100)

        if self._is_canceled(feedback):
            return []

        logger.debug(f"Processed {len(tools)} available tools")
        return tools

    def set_tool_favorite(
        self,
        tool_name: str,
        is_favorite: bool,
    ) -> None:
        self._api.set_tool_favorite(tool_name, is_favorite)

    def _fetch_all_tools_data(
        self,
        unfiltered_tools: List[Dict[str, Any]],
        feedback: Optional[QgsFeedback],
        is_developer_mode: bool,
    ) -> List[ToolboxTool]:
        percent_progress_per_tool = (
            (95 / len(unfiltered_tools)) if unfiltered_tools else 0
        )
        available_tools = self._available_tools(
            unfiltered_tools,
            is_developer_mode,
        )

        if self._is_canceled(feedback):
            logger.debug("Tools fetching canceled by user")
            return []

        tools_by_index = self._fetch_available_tools_data(
            available_tools,
            feedback,
            percent_progress_per_tool,
        )
        if tools_by_index is None:
            return []

        return [tools_by_index[index] for index, _ in available_tools]

    def _available_tools(
        self,
        unfiltered_tools: List[Dict[str, Any]],
        is_developer_mode: bool,
    ) -> List[Tuple[int, Dict[str, Any]]]:
        return [
            (index, tool_data)
            for index, tool_data in enumerate(unfiltered_tools, start=1)
            if self._is_tool_available(tool_data, is_developer_mode)
        ]

    def _fetch_available_tools_data(
        self,
        available_tools: List[Tuple[int, Dict[str, Any]]],
        feedback: Optional[QgsFeedback],
        percent_progress_per_tool: float,
    ) -> Optional[Dict[int, ToolboxTool]]:
        tools_by_index: Dict[int, ToolboxTool] = {}
        futures: Dict[Future, int] = {}
        next_tool_index = 0
        highest_progress = 5.0

        with ThreadPoolExecutor(
            max_workers=self._MAX_CONCURRENT_TOOL_REQUESTS,
        ) as executor:
            next_tool_index = self._submit_tool_fetches(
                executor,
                available_tools,
                next_tool_index,
                futures,
            )

            while futures:
                is_canceled, highest_progress = self._collect_tool_fetches(
                    futures,
                    tools_by_index,
                    feedback,
                    percent_progress_per_tool,
                    highest_progress,
                )
                if is_canceled:
                    return None

                next_tool_index = self._submit_tool_fetches(
                    executor,
                    available_tools,
                    next_tool_index,
                    futures,
                )

        return tools_by_index

    def _submit_tool_fetches(
        self,
        executor: ThreadPoolExecutor,
        available_tools: List[Tuple[int, Dict[str, Any]]],
        next_tool_index: int,
        futures: Dict[Future, int],
    ) -> int:
        while (
            next_tool_index < len(available_tools)
            and len(futures) < self._MAX_CONCURRENT_TOOL_REQUESTS
        ):
            index, tool_data = available_tools[next_tool_index]
            futures[executor.submit(self._fetch_all_tool_data, tool_data)] = (
                index
            )
            next_tool_index += 1

        return next_tool_index

    def _collect_tool_fetches(
        self,
        futures: Dict[Future, int],
        tools_by_index: Dict[int, ToolboxTool],
        feedback: Optional[QgsFeedback],
        percent_progress_per_tool: float,
        highest_progress: float,
    ) -> Tuple[bool, float]:
        completed_futures, _ = wait(
            futures,
            return_when=FIRST_COMPLETED,
        )

        for future in completed_futures:
            index = futures.pop(future)
            tools_by_index[index] = future.result()
            highest_progress = max(
                highest_progress,
                5 + index * percent_progress_per_tool,
            )
            self._set_progress(feedback, highest_progress)

        if not self._is_canceled(feedback):
            return False, highest_progress

        logger.debug("Tools fetching canceled by user")
        return True, highest_progress

    def _fetch_all_tool_data(self, tool_data: Dict[str, Any]) -> ToolboxTool:
        tool_name = tool_data["name"]
        tool_details = self._fetch_tool_details(tool_name)
        tool_presets = self._fetch_tool_presets(tool_name)
        merged_tool_data = self._merge_tool_data(
            tool_data,
            tool_details,
            tool_presets,
        )
        if self._is_semantic_enrichment_enabled:
            merged_tool_data = self._semantics_catalog.enrich_tool_data(
                merged_tool_data
            )
        return ToolboxTool.from_json(merged_tool_data)

    def _fetch_tool_details(self, tool_name: str) -> Dict[str, Any]:
        logger.debug(f"Fetching tool details: {tool_name}")
        return self._api.fetch_tool(tool_name)

    def _fetch_tool_presets(self, tool_name: str) -> List[Dict[str, Any]]:
        logger.debug(f"Fetching tool presets: {tool_name}")
        return self._api.fetch_tool_presets(tool_name)

    def _merge_tool_data(
        self,
        tool_data: Dict[str, Any],
        tool_details: Dict[str, Any],
        tool_presets: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        merged_tool_data = dict(tool_details)
        merged_tool_data.update(tool_data)
        merged_tool_data["presets"] = tool_presets

        return merged_tool_data

    def _is_tool_available(
        self,
        tool_data: Dict[str, Any],
        is_developer_mode: bool,
    ) -> bool:
        """Check whether a tool should be exposed to the plugin."""
        if tool_data.get("is_dev", False) and not is_developer_mode:
            return False

        return True

    def _is_canceled(self, feedback: Optional[QgsFeedback]) -> bool:
        return feedback is not None and feedback.isCanceled()

    def _set_progress(
        self, feedback: Optional[QgsFeedback], progress: float
    ) -> None:
        if feedback is None:
            return
        feedback.setProgress(progress)


class TagsRepository:
    """Repository for Toolbox tag models."""

    def __init__(self, api: ToolsApi) -> None:
        """Initialize repository.

        :param api: Tools API gateway.
        """
        self._api = api

    def set_api(self, api: ToolsApi) -> None:
        """Set API gateway instance.

        :param api: Tools API gateway.
        """
        self._api = api

    def fetch_tags(self) -> List[ToolboxTag]:
        """Fetch tag models from the API.

        :returns: List of Toolbox tag models.
        """
        tags: List[ToolboxTag] = []

        with PluginRuntimeProfiler.download("fetching tags"):
            tags = [
                ToolboxTag.from_json(tag_data)
                for tag_data in self._api.fetch_tags()
            ]

        logger.debug(f"Fetched {len(tags)} tags")
        return tags
