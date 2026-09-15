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

import importlib
import sys
from pathlib import Path
from unittest.mock import Mock

import qgis.utils
from qgis.core import QgsApplication


def _import_plugin_module():
    processing_plugin_root = (
        Path(QgsApplication.pkgDataPath()) / "python" / "plugins"
    )

    if processing_plugin_root.exists() and (
        str(processing_plugin_root) not in sys.path
    ):
        sys.path.insert(0, str(processing_plugin_root))

    if processing_plugin_root.exists() and (
        str(processing_plugin_root) not in qgis.utils.plugin_paths
    ):
        qgis.utils.plugin_paths.append(str(processing_plugin_root))

    return importlib.import_module("nextgis_toolbox.nextgis_toolbox_plugin")


def test_plugin_updates_runtime_components_for_loaded_catalog_state(
    qgis_app,
) -> None:
    del qgis_app

    plugin_module = _import_plugin_module()
    plugin = plugin_module.NextgisToolboxPlugin.__new__(
        plugin_module.NextgisToolboxPlugin
    )
    plugin._ui_manager = Mock()

    plugin.open_about_dialog()

    plugin._ui_manager.open_about_dialog.assert_called_once_with()


def test_plugin_on_settings_changed_resets_ui_before_update(
    qgis_app,
) -> None:
    del qgis_app

    plugin_module = _import_plugin_module()
    plugin = plugin_module.NextgisToolboxPlugin.__new__(
        plugin_module.NextgisToolboxPlugin
    )
    plugin._ui_manager = Mock()
    plugin._update_api_client = Mock()

    plugin._on_settings_changed()

    plugin._ui_manager.reset_refresh_feedback_delay.assert_called_once_with()
    plugin._update_api_client.assert_called_once_with()


def test_plugin_update_api_client_refreshes_tools_manager_on_change(
    qgis_app,
) -> None:
    del qgis_app

    plugin_module = _import_plugin_module()
    plugin = plugin_module.NextgisToolboxPlugin.__new__(
        plugin_module.NextgisToolboxPlugin
    )
    plugin._api_client = Mock(
        endpoint="https://old.nextgis.test",
        authentication=object(),
    )
    plugin._create_authentication = Mock(return_value="new-auth")
    plugin._is_authentication_changed = Mock(return_value=True)
    plugin._tools_manager = Mock(is_semantic_enrichment_enabled=False)

    original_settings_class = plugin_module.NextgisToolboxSettings

    class FakeSettings:
        endpoint = "https://new.nextgis.test"
        authentication_type = object()
        authentication_token = "token"
        is_experimental_qgis_integration_enabled = False

    plugin_module.NextgisToolboxSettings = FakeSettings

    try:
        plugin._update_api_client()
    finally:
        plugin_module.NextgisToolboxSettings = original_settings_class

    plugin._tools_manager.refresh.assert_called_once_with(clear_cache=True)


def test_plugin_update_api_client_refreshes_tools_on_semantic_toggle(
    qgis_app,
) -> None:
    del qgis_app

    plugin_module = _import_plugin_module()
    plugin = plugin_module.NextgisToolboxPlugin.__new__(
        plugin_module.NextgisToolboxPlugin
    )
    plugin._api_client = Mock(
        endpoint="https://same.nextgis.test",
        authentication="same-auth",
    )
    plugin._is_authentication_changed = Mock(return_value=False)
    plugin._tools_manager = Mock(is_semantic_enrichment_enabled=False)

    original_settings_class = plugin_module.NextgisToolboxSettings

    class FakeSettings:
        endpoint = "https://same.nextgis.test"
        authentication_type = object()
        authentication_token = "token"
        is_experimental_qgis_integration_enabled = True

    plugin_module.NextgisToolboxSettings = FakeSettings

    try:
        plugin._update_api_client()
    finally:
        plugin_module.NextgisToolboxSettings = original_settings_class

    plugin._tools_manager.set_semantic_enrichment_enabled.assert_called_once_with(
        True
    )
    plugin._tools_manager.refresh.assert_called_once_with(clear_cache=False)


def test_plugin_update_api_client_skips_unchanged_settings(
    qgis_app,
) -> None:
    del qgis_app

    plugin_module = _import_plugin_module()
    authentication = plugin_module.ToolboxTokenAuthentication(
        "fd5d5321-96fb-4d5e-b27b-0d2e13bc20c7"
    )
    plugin = plugin_module.NextgisToolboxPlugin.__new__(
        plugin_module.NextgisToolboxPlugin
    )
    plugin._api_client = Mock(
        endpoint="https://same.nextgis.test",
        authentication=authentication,
    )
    plugin._tools_manager = Mock(is_semantic_enrichment_enabled=False)

    original_settings_class = plugin_module.NextgisToolboxSettings

    class FakeSettings:
        endpoint = "https://same.nextgis.test"
        authentication_type = plugin_module.AuthenticationType.TOKEN
        authentication_token = "fd5d5321-96fb-4d5e-b27b-0d2e13bc20c7"
        is_experimental_qgis_integration_enabled = False

    plugin_module.NextgisToolboxSettings = FakeSettings

    try:
        plugin._update_api_client()
    finally:
        plugin_module.NextgisToolboxSettings = original_settings_class

    plugin._tools_manager.refresh.assert_not_called()
