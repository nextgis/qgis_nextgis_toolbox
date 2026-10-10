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

from unittest.mock import Mock

from nextgis_toolbox.processing.ui.favorite_tools_sync import (
    FavoriteToolsSync,
)
from nextgis_toolbox.settings.nextgis_toolbox_settings import (
    AuthenticationType,
)
from nextgis_toolbox.tools.models import ToolboxTool


class FakeFavoriteManager:
    def __init__(self, favorites):
        self.changed = Mock()
        self._favorites = set(favorites)

    def add(self, algorithm_id):
        self._favorites.add(algorithm_id)

    def remove(self, algorithm_id):
        self._favorites.discard(algorithm_id)

    def favoriteAlgorithmIds(self):
        return list(self._favorites)


def build_tool(name, *, is_favorite=False):
    return ToolboxTool(
        alias=name,
        can_run=True,
        description=name,
        id=1,
        is_dev=False,
        is_featured=False,
        is_free=True,
        is_favorite=is_favorite,
        is_new=False,
        name=name,
        tag_ids=[],
    )


def test_favorite_sync_replaces_provider_favorites_on_start() -> None:
    favorite_manager = FakeFavoriteManager(
        [
            "nextgis_toolbox:obsolete-tool",
            "other:keep-me",
        ]
    )
    api_client = Mock()
    api_client.authentication_type = AuthenticationType.NONE
    tools_manager = Mock()
    tools_manager.tools.return_value = [
        build_tool("favorite-tool", is_favorite=True),
        build_tool("regular-tool", is_favorite=False),
    ]

    favorite_sync = FavoriteToolsSync(
        api_client=api_client,
        tools_manager=tools_manager,
        provider_id="nextgis_toolbox",
    )
    favorite_sync._favorite_manager = Mock(return_value=favorite_manager)

    favorite_sync.start()

    assert set(favorite_manager.favoriteAlgorithmIds()) == {
        "nextgis_toolbox:favorite-tool",
        "other:keep-me",
    }
    favorite_manager.changed.connect.assert_called_once_with(
        favorite_sync._on_favorites_changed
    )
