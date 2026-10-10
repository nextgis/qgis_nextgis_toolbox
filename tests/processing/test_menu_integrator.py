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
from qgis.PyQt.QtCore import QObject
from qgis.PyQt.QtWidgets import QMainWindow, QMenu

from nextgis_toolbox.tools.models import (
    ToolboxTag,
    ToolboxTool,
    ToolsManagerState,
)


def _import_menu_integrator_module():
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

    return importlib.import_module(
        "nextgis_toolbox.processing.ui.menu_bar_actions_integrator"
    )


def build_tool(name, tag_ids):
    return ToolboxTool(
        alias=name,
        can_run=True,
        description=f"Description for {name}",
        id=1,
        is_dev=False,
        is_featured=False,
        is_free=True,
        is_new=False,
        name=name,
        tag_ids=tag_ids,
    )


class _MenuIntegratorParent(QObject):
    def __init__(self, qgis_iface) -> None:
        super().__init__()
        self.qgis_iface = qgis_iface


def _create_menu_integrator(menu_integrator_module, qgis_iface, **kwargs):
    parent = _MenuIntegratorParent(qgis_iface)
    menu_integrator = menu_integrator_module.ToolboxMenuBarIntegrator(
        qgis_iface=qgis_iface,
        parent=parent,
        **kwargs,
    )
    menu_integrator._test_parent = parent
    return menu_integrator


def test_menu_integrator_uses_processing_setting_before_default(qgis_iface):
    menu_integrator_module = _import_menu_integrator_module()
    menu_integrator = _create_menu_integrator(
        menu_integrator_module,
        qgis_iface,
        tools_manager=Mock(
            state=ToolsManagerState.LOADED,
            error=None,
        ),
        provider_id="nextgis_toolbox",
        start_tool_callback=Mock(),
    )
    tool = build_tool("tool", [10])

    menu_integrator._default_menu_path = Mock(return_value="web/NextGIS Web")
    menu_integrator._algorithm_exists = Mock(return_value=True)
    menu_integrator._add_processing_menu_entry = Mock()

    import processing.core.ProcessingConfig as config_module

    original_get_setting = config_module.ProcessingConfig.getSetting
    original_add_setting = config_module.ProcessingConfig.addSetting

    config_module.ProcessingConfig.addSetting = Mock()
    config_module.ProcessingConfig.getSetting = Mock(
        side_effect=lambda name: (
            "Vector/Custom" if name == "MENU_nextgis_toolbox:tool" else None
        )
    )

    try:
        menu_integrator.integrate_tool(tool)
    finally:
        config_module.ProcessingConfig.getSetting = original_get_setting
        config_module.ProcessingConfig.addSetting = original_add_setting

    menu_integrator._add_processing_menu_entry.assert_called_once_with(
        "nextgis_toolbox:tool",
        "Vector/Custom",
    )


def test_menu_integrator_populates_dynamic_sections(
    qgis_iface, qgis_app
) -> None:
    del qgis_app

    menu_integrator_module = _import_menu_integrator_module()

    main_window = qgis_iface.mainWindow()
    if not isinstance(main_window, QMainWindow):
        main_window = QMainWindow()
        qgis_iface.mainWindow.return_value = main_window

    tools_menu = QMenu("Tools", main_window)
    favorite_tool = build_tool("favorite", [1])
    favorite_tool.is_favorite = True
    featured_tool = build_tool("featured", [2])
    featured_tool.is_featured = True
    tag = ToolboxTag(id=3, alias="Tag", icon="", tool_ids=[])

    tools_manager = Mock()
    tools_manager.tags.return_value = [tag]
    tools_manager.find_tools.side_effect = lambda **kwargs: {
        "is_favorite": [favorite_tool],
        "is_featured": [featured_tool],
        "tag": [favorite_tool, featured_tool],
    }[next(iter(kwargs.keys()))]

    menu_integrator = _create_menu_integrator(
        menu_integrator_module,
        qgis_iface,
        tools_manager=tools_manager,
        provider_id="nextgis_toolbox",
        start_tool_callback=Mock(),
    )
    tools_manager.state = ToolsManagerState.LOADED
    tools_manager.error = None
    menu_integrator._algorithm_exists = Mock(return_value=True)

    menu_integrator.populate_toolbox_menu(tools_menu)

    submenu_titles = [
        action.menu().title()
        for action in tools_menu.actions()
        if action.menu() is not None
    ]
    assert submenu_titles[:2] == ["Favorites", "Recommendations"]
    assert "Tag" in submenu_titles

    favorite_section = tools_menu.actions()[0].menu()
    assert favorite_section is not None
    assert not favorite_section.actions()[0].icon().isNull()


def test_menu_integrator_refresh_clears_previous_processing_state(
    qgis_iface,
) -> None:
    menu_integrator_module = _import_menu_integrator_module()
    menu_integrator = _create_menu_integrator(
        menu_integrator_module,
        qgis_iface,
        tools_manager=Mock(
            state=ToolsManagerState.LOADED,
            error=None,
        ),
        provider_id="nextgis_toolbox",
        start_tool_callback=Mock(),
    )
    menu_integrator._clear_processing_menu_entries = Mock()
    menu_integrator._remove_registered_settings = Mock()
    menu_integrator._clear_patched_defaults = Mock()
    menu_integrator._refresh_processing_menu_entries = Mock()
    menu_integrator.refresh_tools_menu = Mock()

    menu_integrator.refresh()

    menu_integrator._clear_processing_menu_entries.assert_called_once_with()
    menu_integrator._remove_registered_settings.assert_called_once_with()
    menu_integrator._clear_patched_defaults.assert_called_once_with()
    menu_integrator._refresh_processing_menu_entries.assert_called_once_with()
    menu_integrator.refresh_tools_menu.assert_called_once_with()


def test_menu_integrator_adds_processing_icon_to_integrated_entry(
    monkeypatch,
    qgis_iface,
) -> None:
    menu_integrator_module = _import_menu_integrator_module()
    menu_integrator = _create_menu_integrator(
        menu_integrator_module,
        qgis_iface,
        tools_manager=Mock(
            state=ToolsManagerState.LOADED,
            error=None,
        ),
        provider_id="nextgis_toolbox",
        start_tool_callback=Mock(),
    )

    captured = {}
    fake_algorithm = Mock()
    monkeypatch.setattr(
        menu_integrator,
        "_processing_algorithm",
        Mock(return_value=fake_algorithm),
    )
    monkeypatch.setattr(
        menu_integrator_module.processing_menus,
        "addAlgorithmEntry",
        lambda algorithm, menu_name, submenu_name, icon=None: captured.update(
            {
                "algorithm": algorithm,
                "menu_name": menu_name,
                "submenu_name": submenu_name,
                "icon": icon,
            }
        ),
    )

    menu_integrator._add_processing_menu_entry(
        "nextgis_toolbox:tool",
        "Vector/Custom",
    )

    assert captured["algorithm"] is fake_algorithm
    assert captured["menu_name"] == "Vector"
    assert captured["submenu_name"] == "Custom"
    assert captured["icon"] is not None
    assert captured["icon"].isNull() is False


def test_menu_integrator_adds_loading_placeholders(
    qgis_iface,
    qgis_app,
) -> None:
    del qgis_app

    menu_integrator_module = _import_menu_integrator_module()
    main_window = qgis_iface.mainWindow()
    if not isinstance(main_window, QMainWindow):
        main_window = QMainWindow()
        qgis_iface.mainWindow.return_value = main_window

    tools_menu = QMenu("Tools", main_window)
    tools_manager = Mock()
    tools_manager.state = ToolsManagerState.LOADING
    tools_manager.error = None

    menu_integrator = _create_menu_integrator(
        menu_integrator_module,
        qgis_iface,
        tools_manager=tools_manager,
        provider_id="nextgis_toolbox",
        start_tool_callback=Mock(),
    )
    menu_integrator.bind_tools_menu(tools_menu)

    menu_integrator.refresh()

    assert tools_menu.actions()[0].isEnabled() is False
    assert tools_menu.actions()[0].text() == "Loading tools…"
    assert tools_menu.actions()[0].icon().isNull() is False
    assert len(menu_integrator._processing_placeholder_entries) == 1
    assert (
        menu_integrator._processing_placeholder_entries[0][1].isEnabled()
        is False
    )


def test_menu_integrator_ignores_deleted_placeholder_submenus(
    monkeypatch,
    qgis_iface,
) -> None:
    menu_integrator_module = _import_menu_integrator_module()
    menu_integrator = _create_menu_integrator(
        menu_integrator_module,
        qgis_iface,
        tools_manager=Mock(
            state=ToolsManagerState.LOADED,
            error=None,
        ),
        provider_id="nextgis_toolbox",
        start_tool_callback=Mock(),
    )
    deleted_submenu = Mock()
    action = Mock()
    menu_integrator._processing_placeholder_entries = [
        (deleted_submenu, action)
    ]

    monkeypatch.setattr(
        menu_integrator_module.sip,
        "isdeleted",
        lambda obj: obj is deleted_submenu,
    )

    menu_integrator._clear_processing_placeholder_entries()

    deleted_submenu.removeAction.assert_not_called()
    assert menu_integrator._processing_placeholder_entries == []
