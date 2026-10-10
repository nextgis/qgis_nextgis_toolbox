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
from qgis.PyQt.QtWidgets import QMenu, QProgressBar

from nextgis_toolbox.tools.models import ToolsManagerState


def _prepare_plugin_import_path() -> None:
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


def _import_ui_manager_module():
    _prepare_plugin_import_path()
    return importlib.import_module("nextgis_toolbox.ui.plugin_ui_manager")


def _import_progress_manager_module():
    _prepare_plugin_import_path()
    return importlib.import_module(
        "nextgis_toolbox.ui.catalog_refresh_progress_manager"
    )


def _import_dialog_manager_module():
    _prepare_plugin_import_path()
    return importlib.import_module(
        "nextgis_toolbox.processing.ui.algorithm_dialog_manager"
    )


def _create_plugin_ui_manager(manager_module, qgis_iface):
    return manager_module.PluginUiManager(
        qgis_iface=qgis_iface,
        notifier=Mock(),
        api_client=Mock(),
        tools_manager=Mock(),
        tasks_manager=Mock(),
        processing_provider=Mock(id=Mock(return_value="provider")),
    )


def test_processing_ui_compat_imports_algorithm_dialog_class(qgis_app) -> None:
    del qgis_app

    _prepare_plugin_import_path()
    compat_module = importlib.import_module(
        "nextgis_toolbox.processing.ui.compat"
    )

    if not compat_module.IS_DESKTOP_PLATFORM:
        assert compat_module.AlgorithmDialog is object
        return

    assert compat_module.AlgorithmDialog is not object
    assert compat_module.AlgorithmDialog.__name__ in (
        "AlgorithmDialog",
        "AlgorithmWidget",
    )


def test_progress_manager_first_loading_resets_progress_state(
    qgis_iface,
    qgis_app,
) -> None:
    del qgis_app

    manager_module = _import_progress_manager_module()
    manager = manager_module.CatalogRefreshProgressManager(qgis_iface, Mock())
    manager._catalog_progress_value = 73
    manager._schedule_catalog_progress_message = Mock()

    manager.on_runtime_state_changed(ToolsManagerState.LOADING)

    assert manager._catalog_progress_value == 0
    manager._schedule_catalog_progress_message.assert_called_once_with()


def test_progress_manager_first_loading_delays_feedback(
    qgis_iface,
    qgis_app,
) -> None:
    del qgis_app

    manager_module = _import_progress_manager_module()
    manager = manager_module.CatalogRefreshProgressManager(qgis_iface, Mock())
    manager._schedule_catalog_progress_message = Mock()

    manager.on_runtime_state_changed(ToolsManagerState.LOADING)

    assert manager._show_catalog_progress_immediately is False


def test_progress_manager_second_loading_enables_immediate_progress(
    qgis_iface,
    qgis_app,
) -> None:
    del qgis_app

    manager_module = _import_progress_manager_module()
    manager = manager_module.CatalogRefreshProgressManager(qgis_iface, Mock())
    manager._schedule_catalog_progress_message = Mock()

    manager.on_runtime_state_changed(ToolsManagerState.LOADING)
    manager.on_runtime_state_changed(ToolsManagerState.LOADED)
    manager._schedule_catalog_progress_message.reset_mock()
    manager.on_runtime_state_changed(ToolsManagerState.LOADING)

    manager._schedule_catalog_progress_message.assert_called_once_with()
    assert manager._show_catalog_progress_immediately is True


def test_progress_manager_tracks_catalog_progress_before_bar_is_shown(
    qgis_iface,
    qgis_app,
) -> None:
    del qgis_app

    manager_module = _import_progress_manager_module()
    manager = manager_module.CatalogRefreshProgressManager(qgis_iface, Mock())

    manager.on_catalog_load_progress_changed(42.6)

    assert manager._catalog_progress_value == 42.6


def test_progress_manager_show_catalog_progress_message_keeps_existing_bar(
    qgis_iface,
    qgis_app,
) -> None:
    del qgis_app

    manager_module = _import_progress_manager_module()
    manager = manager_module.CatalogRefreshProgressManager(qgis_iface, Mock())
    existing_progress_bar = Mock()
    manager._catalog_progress_generation = 4
    manager._catalog_progress_bar = existing_progress_bar
    manager._catalog_progress_message_id = "message-id"
    manager._tools_state = ToolsManagerState.LOADING

    manager._show_catalog_progress_message(4)

    assert manager._catalog_progress_bar is existing_progress_bar
    assert manager._catalog_progress_message_id == "message-id"


def test_progress_manager_show_catalog_progress_message_uses_smooth_bar(
    qgis_iface,
    qgis_app,
    monkeypatch,
) -> None:
    del qgis_app

    manager_module = _import_progress_manager_module()

    class FakeMessageBarNotifier:
        def display_message(self, *_args, **_kwargs) -> str:
            return "message-id"

        def dismiss_message(self, _message_id: str) -> None:
            return None

    notifier = FakeMessageBarNotifier()

    monkeypatch.setattr(
        manager_module,
        "MessageBarNotifier",
        FakeMessageBarNotifier,
    )
    monkeypatch.setattr(manager_module, "QProgressBar", QProgressBar)

    manager = manager_module.CatalogRefreshProgressManager(
        qgis_iface,
        notifier,
    )
    manager._catalog_progress_generation = 2
    manager._catalog_progress_value = 42.6
    manager._tools_state = ToolsManagerState.LOADING

    manager._show_catalog_progress_message(2)

    assert manager._catalog_progress_bar is not None
    assert (
        manager._catalog_progress_bar.styleSheet()
        == "QProgressBar::chunk { width: 1px; margin: 0px; }"
    )
    assert manager._catalog_progress_bar.value() == 43


def test_progress_manager_reset_feedback_delay_delays_next_loading(
    qgis_iface,
    qgis_app,
) -> None:
    del qgis_app

    manager_module = _import_progress_manager_module()
    manager = manager_module.CatalogRefreshProgressManager(qgis_iface, Mock())
    manager._schedule_catalog_progress_message = Mock()

    manager.on_runtime_state_changed(ToolsManagerState.LOADING)
    manager.on_runtime_state_changed(ToolsManagerState.LOADED)
    manager.on_runtime_state_changed(ToolsManagerState.LOADING)
    manager.reset_refresh_feedback_delay()
    manager.on_runtime_state_changed(ToolsManagerState.LOADED)
    manager.on_runtime_state_changed(ToolsManagerState.LOADING)

    assert manager._show_catalog_progress_immediately is False


def test_ui_manager_reset_refresh_feedback_delay_delegates_to_progress_manager(
    qgis_iface,
    qgis_app,
) -> None:
    del qgis_app

    manager_module = _import_ui_manager_module()
    manager = _create_plugin_ui_manager(manager_module, qgis_iface)
    manager._progress_manager = Mock()

    manager.reset_refresh_feedback_delay()

    manager._progress_manager.reset_refresh_feedback_delay.assert_called_once_with()


def test_ui_manager_initialize_ui_retries_until_processing_menu_available(
    qgis_iface,
    qgis_app,
) -> None:
    del qgis_app

    manager_module = _import_ui_manager_module()
    manager = _create_plugin_ui_manager(manager_module, qgis_iface)
    manager._plugin_menu = None
    manager._find_processing_menu = Mock(return_value=None)
    manager._schedule_update_ui = Mock(return_value=True)
    manager._handle_missing_processing_plugin = Mock()

    manager._delayed_updating_ui()

    manager._schedule_update_ui.assert_called_once_with()
    manager._handle_missing_processing_plugin.assert_not_called()


def test_ui_manager_finds_processing_menu_by_object_name(
    qgis_iface,
    qgis_app,
) -> None:
    del qgis_app

    manager_module = _import_ui_manager_module()
    manager = _create_plugin_ui_manager(manager_module, qgis_iface)

    processing_menu = QMenu("Processing", qgis_iface.mainWindow())
    processing_menu.setObjectName("processing")

    assert manager._find_processing_menu() is processing_menu


def test_dialog_manager_patches_only_matching_algorithm_dialog(
    qgis_app,
) -> None:
    del qgis_app

    manager_module = _import_dialog_manager_module()
    manager = manager_module.AlgorithmDialogManager()
    manager._dialog_patcher = Mock()

    matching_algorithm = Mock()
    other_dialog = Mock()
    other_dialog.algorithm.return_value = Mock()
    matching_dialog = Mock()
    matching_dialog.algorithm.return_value = matching_algorithm
    manager._find_algorithm_dialogs = Mock(
        return_value=[other_dialog, matching_dialog]
    )

    manager._patch_dialog(id(matching_algorithm))

    manager._dialog_patcher.patch.assert_called_once_with(matching_dialog)


def test_dialog_manager_retries_until_dialog_is_found(
    monkeypatch,
    qgis_app,
) -> None:
    del qgis_app

    manager_module = _import_dialog_manager_module()
    monkeypatch.setattr(
        manager_module.QTimer,
        "singleShot",
        lambda _timeout, callback: callback(),
    )

    manager = manager_module.AlgorithmDialogManager()
    manager._dialog_patcher = Mock()

    matching_algorithm = Mock()
    matching_algorithm.name.return_value = "demo-tool"
    matching_dialog = Mock()
    matching_dialog.algorithm.return_value = matching_algorithm
    manager._find_algorithm_dialogs = Mock(side_effect=[[], [matching_dialog]])

    manager.on_algorithm_instance_created(matching_algorithm)

    manager._dialog_patcher.patch.assert_called_once_with(matching_dialog)
