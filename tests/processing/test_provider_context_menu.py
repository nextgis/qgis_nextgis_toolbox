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

import pytest
import qgis.utils
from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QPoint, pyqtSignal
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMenu, QToolBar, QToolButton, QWidget


def _import_context_menu_module():
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
        "nextgis_toolbox.processing.ui.panel_actions_integrator"
    )


class FakeAlgorithmTree(QWidget):
    customContextMenuRequested = pyqtSignal(QPoint)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._index = Mock()
        self.algorithmForIndex = Mock(return_value=None)

    def indexAt(self, point: QPoint):
        del point
        return self._index

    def mapToGlobal(self, point: QPoint) -> QPoint:
        return point


class FakeToolbox(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.algorithmTree = FakeAlgorithmTree(self)
        self.processingToolbar = QToolBar(self)
        self.add_provider_actions_calls = 0

    def addProviderActions(self, provider) -> None:
        self.add_provider_actions_calls += 1

        button = QToolButton(self.processingToolbar)
        button.setObjectName(f"provideraction_{provider.id()}")
        menu = QMenu(provider.name(), button)
        for action in provider.actions:
            menu.addAction(QAction(action.name, menu))
        button.setMenu(menu)
        self.processingToolbar.addWidget(button)


class FakeProviderTreeModel:
    def __init__(self, provider_id: str) -> None:
        self._provider_id = provider_id

    def providerIdForIndex(self, index) -> str:  # noqa: N802
        del index
        return self._provider_id


def _add_toolbar_button(toolbox: FakeToolbox, object_name: str) -> None:
    button = QToolButton(toolbox.processingToolbar)
    button.setObjectName(object_name)
    toolbox.processingToolbar.addWidget(button)


def _provider_button_count(toolbox: FakeToolbox, provider_id: str) -> int:
    count = 0

    for toolbar_action in toolbox.processingToolbar.actions():
        widget = toolbox.processingToolbar.widgetForAction(toolbar_action)
        if not isinstance(widget, QToolButton):
            continue

        if widget.objectName() == f"provideraction_{provider_id}":
            count += 1

    return count


@pytest.fixture
def handler_factory(qgis_iface):
    handlers = []

    def create(provider):
        provider.icon.return_value = QIcon()
        for action in provider.actions:
            action.isEnabled.return_value = True
        handler = _import_context_menu_module().PanelActionsIntegrator(
            qgis_iface=qgis_iface, provider=provider
        )
        handler._button_actions = provider.actions
        handler.load()
        handlers.append(handler)
        return handler

    yield create
    for handler in handlers:
        handler.unload()


def test_provider_context_menu_binds_and_unbinds_toolbox(
    monkeypatch,
    qgis_app,
    handler_factory,
) -> None:
    del qgis_app

    provider = Mock()
    provider.id.return_value = "nextgis_toolbox"
    provider.name.return_value = "NextGIS Toolbox"

    action = Mock()
    action.name = "Open in Browser"
    action.getIcon.return_value = QIcon()
    provider.actions = [action]

    handler = handler_factory(provider)
    toolbox = FakeToolbox()

    show_menu = Mock()
    monkeypatch.setattr(handler, "_show_provider_context_menu", show_menu)

    handler._bind_toolbox(toolbox)

    assert toolbox.add_provider_actions_calls == 0
    assert _provider_button_count(toolbox, provider.id()) == 1

    toolbox.algorithmTree.customContextMenuRequested.emit(QPoint(10, 10))
    assert show_menu.call_count == 1

    handler._bind_toolbox(toolbox)

    assert toolbox.add_provider_actions_calls == 0
    assert _provider_button_count(toolbox, provider.id()) == 1

    handler.unload()
    assert _provider_button_count(toolbox, provider.id()) == 0

    toolbox.algorithmTree.customContextMenuRequested.emit(QPoint(20, 20))
    assert show_menu.call_count == 1


def test_provider_context_menu_syncs_toolbar_action_icons(
    qgis_app,
    handler_factory,
) -> None:
    del qgis_app

    provider = Mock()
    provider.id.return_value = "nextgis_toolbox"
    provider.name.return_value = "NextGIS Toolbox"

    icon = QIcon(":images/themes/default/mIconHistory.svg")
    action = Mock()
    action.name = "Tasks history"
    action.getIcon.return_value = icon
    provider.actions = [action]

    handler = handler_factory(provider)
    toolbox = FakeToolbox()

    handler._bind_toolbox(toolbox)

    button = toolbox.findChild(QToolButton, "provideraction_nextgis_toolbox")
    assert button is not None
    assert button.menu() is not None
    assert button.menu().actions()[0].icon().cacheKey() == icon.cacheKey()


def test_provider_context_menu_moves_provider_button_after_scripts(
    qgis_app,
    handler_factory,
) -> None:
    del qgis_app

    provider = Mock()
    provider.id.return_value = "nextgis_toolbox"
    provider.name.return_value = "NextGIS Toolbox"
    provider.actions = []

    handler = handler_factory(provider)
    toolbox = FakeToolbox()
    _add_toolbar_button(toolbox, "provideraction_model")
    _add_toolbar_button(toolbox, "provideraction_script")

    handler._bind_toolbox(toolbox)

    button_order = []
    for toolbar_action in toolbox.processingToolbar.actions():
        widget = toolbox.processingToolbar.widgetForAction(toolbar_action)
        if isinstance(widget, QToolButton):
            button_order.append(widget.objectName())

    assert button_order[:3] == [
        "provideraction_model",
        "provideraction_script",
        "provideraction_nextgis_toolbox",
    ]


def test_provider_context_menu_hides_menu_for_favorites_section(
    qgis_app,
    monkeypatch,
    handler_factory,
) -> None:
    del qgis_app

    provider = Mock()
    provider.id.return_value = "nextgis_toolbox"
    provider.name.return_value = "NextGIS Toolbox"
    provider.actions = []

    handler = handler_factory(provider)
    toolbox = FakeToolbox()
    toolbox.algorithmTree.algorithmForIndex = Mock(return_value=None)
    toolbox.algorithmTree.model = Mock(return_value=FakeProviderTreeModel(""))

    top_level_index = Mock()
    top_level_index.isValid.return_value = True
    top_level_parent = Mock()
    top_level_parent.isValid.return_value = False
    top_level_index.parent.return_value = top_level_parent

    top_level_index.data.return_value = "Favorites"
    toolbox.algorithmTree._index = top_level_index
    show_menu = Mock()
    monkeypatch.setattr(QMenu, "exec", show_menu)
    handler._show_provider_context_menu(toolbox, QPoint(1, 2))
    show_menu.assert_not_called()


def test_provider_context_menu_shows_menu_for_nested_provider_node(
    qgis_app,
    monkeypatch,
    handler_factory,
) -> None:
    del qgis_app

    provider = Mock()
    provider.id.return_value = "nextgis_toolbox"
    provider.name.return_value = "NextGIS Toolbox"
    provider.actions = []

    handler = handler_factory(provider)
    toolbox = FakeToolbox()
    toolbox.algorithmTree.algorithmForIndex = Mock(return_value=None)
    toolbox.algorithmTree.model = Mock(
        return_value=FakeProviderTreeModel(provider.id())
    )

    nested_index = Mock()
    nested_index.isValid.return_value = True
    nested_parent = Mock()
    nested_parent.isValid.return_value = True
    nested_index.parent.return_value = nested_parent

    nested_index.data.return_value = "NextGIS Toolbox"
    toolbox.algorithmTree._index = nested_index
    show_menu = Mock()
    monkeypatch.setattr(QMenu, "exec", show_menu)
    handler._show_provider_context_menu(toolbox, QPoint(1, 2))
    show_menu.assert_called_once()
