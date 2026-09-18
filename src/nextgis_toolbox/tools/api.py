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

from typing import Any, Dict, List, Optional

from qgis.core import QgsFeedback

from nextgis_toolbox.api.client import ToolboxApiClient


class ToolsApi:
    """API gateway for NextGIS Toolbox tools endpoints."""

    def __init__(self, client: ToolboxApiClient) -> None:
        """Initialize API gateway.

        :param client: Low-level Toolbox API client.
        """
        self._client = client

    @property
    def client(self) -> ToolboxApiClient:
        """Low-level API client."""
        return self._client

    def fetch_tools(
        self,
        feedback: Optional[QgsFeedback] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch raw tool summary payloads.

        :returns: List of raw tool dictionaries.
        """
        response_data = self._client.get("tools/", feedback=feedback)
        return response_data["data"]

    def fetch_tags(
        self,
        feedback: Optional[QgsFeedback] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch raw tags payloads.

        :returns: List of raw tag dictionaries.
        """
        response_data = self._client.get("tags/", feedback=feedback)
        return response_data["data"]

    def invalidate_cache(self) -> None:
        """Invalidate cached tool payloads."""
        self._client.invalidate_cache()

    def fetch_tool(
        self,
        tool_name: str,
        feedback: Optional[QgsFeedback] = None,
    ) -> Dict[str, Any]:
        """Fetch raw tool details.

        :param tool_name: Toolbox tool identifier.

        :returns: Raw tool dictionary.
        """
        path = f"tools/{tool_name}"
        return self._client.get(path, feedback=feedback, cache_key=path)

    def fetch_tool_presets(
        self,
        tool_name: str,
        feedback: Optional[QgsFeedback] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch raw tool presets.

        :param tool_name: Toolbox tool identifier.

        :returns: List of raw tool preset dictionaries.
        """
        path = f"tools/{tool_name}/presets"
        response_data = self._client.get(
            path,
            feedback=feedback,
            cache_key=path,
        )
        return response_data["items"]

    def set_tool_favorite(
        self, tool_name: str, is_favorite: bool
    ) -> Dict[str, Any]:
        """Persist a favorite state for the current user.

        :param tool_name: Toolbox tool identifier.
        :param is_favorite: Requested favorite state.

        :returns: Raw update response.
        """
        result = self._client.post(
            f"tools/{tool_name}/favorite",
            {"new_value": int(is_favorite)},
        )
        self._client.invalidate_cache_entry(f"tools/{tool_name}")
        return result
