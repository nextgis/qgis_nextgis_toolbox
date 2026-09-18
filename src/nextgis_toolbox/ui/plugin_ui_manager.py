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

from typing import TYPE_CHECKING, Optional

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QObject, QTimer, QUrl, pyqtSlot

from nextgis_toolbox.core.constants import PACKAGE_NAME, PLUGIN_NAME
from nextgis_toolbox.core.exceptions import ToolboxProcessingRequiredWarning
from nextgis_toolbox.core.logging import logger
from nextgis_toolbox.core.utils import PluginRuntimeProfiler, assert_not_none
from nextgis_toolbox.processing.ui.provider_ui import ToolboxProviderUi
from nextgis_toolbox.ui.catalog_refresh_progress_manager import (
    CatalogRefreshProgressManager,
)

if TYPE_CHECKING:
    from qgis.gui import QgisInterface

    from nextgis_toolbox.api.client import ToolboxApiClient
    from nextgis_toolbox.notifier.notifier_interface import (
        NotifierInterface,
    )
    from nextgis_toolbox.processing.nextgis_toolbox_processing_provider import (
        NextgisToolboxProcessingProvider,
    )
    from nextgis_toolbox.tasks.tasks_interface import (
        TasksInterface,
    )
    from nextgis_toolbox.tools.tools_interface import (
        ToolsInterface,
    )

IS_DESKTOP_PLATFORM = QgsApplication.platform() == "desktop"

if TYPE_CHECKING or IS_DESKTOP_PLATFORM:
    from qgis.PyQt.QtGui import QDesktopServices
    from qgis.PyQt.QtWidgets import QAction, QMenu

    from nextgis_toolbox.settings.nextgis_toolbox_settings_page import (
        NextgisToolboxSettingsPageFactory,
    )
    from nextgis_toolbox.ui.about_dialog import AboutDialog
    from nextgis_toolbox.ui.icon import plugin_icon, qgis_icon
else:
    AboutDialog = object
    NextgisToolboxSettingsPageFactory = object
    QDesktopServices = object
    QAction = object
    QMenu = object

    def plugin_icon(*_args, **_kwargs) -> object:
        return object()

    def qgis_icon(*_args, **_kwargs) -> object:
        return object()


class PluginUiManager(QObject):
    """Own desktop UI setup and runtime GUI reactions for the plugin."""

    def __init__(
        self,
        qgis_iface: "QgisInterface",
        notifier: "NotifierInterface",
        api_client: "ToolboxApiClient",
        tools_manager: "ToolsInterface",
        tasks_manager: "TasksInterface",
        processing_provider: "NextgisToolboxProcessingProvider",
        parent: Optional[QObject] = None,
    ) -> None:
        """Initialize the desktop UI manager."""
        super().__init__(parent)
        self._qgis_iface = qgis_iface
        self._notifier = notifier
        self._api_client = api_client
        self._tools_manager = tools_manager
        self._tasks_manager = tasks_manager
        self._processing_provider = processing_provider
        self._options_factory = None
        self._plugin_menu = None
        self._tools_menu = None
        self._about_action = None
        self._open_website_action = None
        self._tasks_history_action = None
        self._refresh_tools_action = None
        self._settings_action = None
        self._show_help_action = None
        self._processing_menu_retry_count = 0
        self._progress_manager = CatalogRefreshProgressManager(
            qgis_iface=qgis_iface,
            notifier=notifier,
            parent=self,
        )
        self._progress_manager.connect_tools_manager(tools_manager)
        self._processing_ui = ToolboxProviderUi(
            provider=processing_provider,
            qgis_iface=qgis_iface,
            api_client=api_client,
            tools_manager=tools_manager,
            parent=self,
        )
        self._processing_provider.set_provider_ui(self._processing_ui)

    def load(self) -> None:
        """Initialize desktop UI objects and register QGIS integrations."""
        self._processing_ui.load()
        self._load_settings_page()
        self.reset_refresh_feedback_delay()
        self._schedule_update_ui()

    def unload(self) -> None:
        """Release desktop UI objects and unregister QGIS integrations."""
        self._unregister_plugin_menu()
        self._unregister_help_action()
        self._unload_settings_page()
        self._delete_actions()
        self._processing_ui.unload()

    @pyqtSlot()
    def open_about_dialog(self) -> None:
        """Open the plugin about dialog."""
        if AboutDialog is None:
            self._notifier.display_message(
                self.tr("About dialog is unavailable."),
            )
            return

        dialog = AboutDialog(PACKAGE_NAME)
        dialog.exec()

    @pyqtSlot()
    def reset_refresh_feedback_delay(self) -> None:
        """Delay the progress popup for the next automatic refresh."""
        self._progress_manager.reset_refresh_feedback_delay()

    @PluginRuntimeProfiler.wrap("updating ui")
    def _delayed_updating_ui(self) -> None:
        if self._plugin_menu is not None:
            return

        processing_menu = self._find_processing_menu()
        if processing_menu is None:
            if self._schedule_update_ui():
                return

            self._handle_missing_processing_plugin()
            return

        self._processing_menu_retry_count = 0
        self._create_plugin_menu()
        self._create_toolbox_menu()
        self._create_refresh_tools_action()
        self._create_open_website_action()
        self._create_tasks_history_action()
        self._create_settings_action()
        self._create_about_action()
        self._create_help_action()
        self._register_plugin_menu(processing_menu)
        self._register_help_action()

    def _find_processing_menu(self) -> Optional[QMenu]:
        main_window = self._qgis_iface.mainWindow()
        for menu in main_window.findChildren(QMenu):
            if menu.objectName() == "processing":
                return menu

        return None

    def _schedule_update_ui(self) -> bool:
        if self._processing_menu_retry_count >= 20:
            return False

        self._processing_menu_retry_count += 1
        QTimer.singleShot(250, self._delayed_updating_ui)
        return True

    def _handle_missing_processing_plugin(self) -> None:
        self._notifier.display_exception(ToolboxProcessingRequiredWarning())
        logger.debug(
            "<b>Processing plugin is not enabled. "
            "NextGIS Toolbox initialization skipped</b>"
        )

    def _create_plugin_menu(self) -> None:
        icon = plugin_icon()
        self._plugin_menu = QMenu(self._qgis_iface.mainWindow())
        self._plugin_menu.setTitle(self.tr("NextGIS Toolbox"))
        self._plugin_menu.setIcon(icon)

    def _create_toolbox_menu(self) -> None:
        plugin_menu = assert_not_none(
            self._plugin_menu,
            "Plugin menu is not initialized",
        )
        self._tools_menu = self._processing_ui.create_tools_menu(plugin_menu)

    def _create_refresh_tools_action(self) -> None:
        plugin_menu = assert_not_none(
            self._plugin_menu,
            "Plugin menu is not initialized",
        )
        self._refresh_tools_action = QAction(
            qgis_icon("mActionRefresh.svg"),
            self.tr("Refresh tools"),
            self._qgis_iface.mainWindow(),
        )
        self._refresh_tools_action.triggered.connect(
            lambda _checked=False: self._tools_manager.refresh(
                clear_cache=True
            )
        )
        self._processing_ui.set_refresh_action(self._refresh_tools_action)
        plugin_menu.addAction(self._refresh_tools_action)

    def _create_about_action(self) -> None:
        plugin_menu = assert_not_none(
            self._plugin_menu,
            "Plugin menu is not initialized",
        )
        self._about_action = QAction(
            qgis_icon("mActionPropertiesWidget.svg"),
            self.tr("About plugin…"),
            self._qgis_iface.mainWindow(),
        )
        self._about_action.triggered.connect(self.open_about_dialog)
        plugin_menu.addAction(self._about_action)

    def _create_open_website_action(self) -> None:
        plugin_menu = assert_not_none(
            self._plugin_menu,
            "Plugin menu is not initialized",
        )
        plugin_menu.addSeparator()
        self._open_website_action = QAction(
            plugin_icon(),
            self.tr("Open in Browser"),
            self._qgis_iface.mainWindow(),
        )
        self._open_website_action.triggered.connect(self._open_toolbox_website)
        plugin_menu.addAction(self._open_website_action)

    def _create_tasks_history_action(self) -> None:
        plugin_menu = assert_not_none(
            self._plugin_menu,
            "Plugin menu is not initialized",
        )
        self._tasks_history_action = QAction(
            qgis_icon("mIconHistory.svg"),
            self.tr("Tasks history"),
            self._qgis_iface.mainWindow(),
        )
        self._tasks_history_action.triggered.connect(self._open_tasks_history)
        plugin_menu.addAction(self._tasks_history_action)

    def _create_settings_action(self) -> None:
        plugin_menu = assert_not_none(
            self._plugin_menu,
            "Plugin menu is not initialized",
        )
        self._settings_action = QAction(
            qgis_icon("mActionOptions.svg"),
            self.tr("Settings…"),
            self._qgis_iface.mainWindow(),
        )
        self._settings_action.triggered.connect(self._open_settings)
        plugin_menu.addAction(self._settings_action)

    def _create_help_action(self) -> None:
        self._show_help_action = QAction(plugin_icon(), PLUGIN_NAME)
        self._show_help_action.triggered.connect(self.open_about_dialog)

    def _register_plugin_menu(self, processing_menu: QMenu) -> None:
        processing_menu.addMenu(
            assert_not_none(
                self._plugin_menu,
                "Plugin menu is not initialized",
            )
        )

    def _register_help_action(self) -> None:
        plugin_help_menu = assert_not_none(
            self._qgis_iface.pluginHelpMenu(),
            "Plugin help menu is unavailable",
        )
        plugin_help_menu.addAction(self._show_help_action)

    def _unregister_plugin_menu(self) -> None:
        if self._plugin_menu is None:
            return

        processing_menu = self._find_processing_menu()
        if processing_menu is None:
            return

        processing_menu.removeAction(self._plugin_menu.menuAction())

    def _unregister_help_action(self) -> None:
        if self._show_help_action is None:
            return

        plugin_help_menu = assert_not_none(
            self._qgis_iface.pluginHelpMenu(),
            "Plugin help menu is unavailable",
        )
        plugin_help_menu.removeAction(self._show_help_action)

    def _delete_actions(self) -> None:
        self._tools_menu = None

        if self._plugin_menu is not None:
            self._plugin_menu.deleteLater()
            self._plugin_menu = None

        if self._about_action is not None:
            self._about_action.deleteLater()
            self._about_action = None

        if self._open_website_action is not None:
            self._open_website_action.deleteLater()
            self._open_website_action = None

        if self._tasks_history_action is not None:
            self._tasks_history_action.deleteLater()
            self._tasks_history_action = None

        if self._refresh_tools_action is not None:
            self._refresh_tools_action.deleteLater()
            self._refresh_tools_action = None

        if self._settings_action is not None:
            self._settings_action.deleteLater()
            self._settings_action = None

        if self._show_help_action is not None:
            self._show_help_action.deleteLater()
            self._show_help_action = None

    def _load_settings_page(self) -> None:
        if NextgisToolboxSettingsPageFactory is None:
            logger.debug("Settings page factory is unavailable")
            return

        self._options_factory = NextgisToolboxSettingsPageFactory()
        self._qgis_iface.registerOptionsWidgetFactory(self._options_factory)

    def _unload_settings_page(self) -> None:
        if self._options_factory is None:
            return

        self._qgis_iface.unregisterOptionsWidgetFactory(self._options_factory)
        self._options_factory.deleteLater()
        self._options_factory = None

    @pyqtSlot()
    def _open_toolbox_website(self) -> None:
        QDesktopServices.openUrl(QUrl(self._api_client.endpoint))

    @pyqtSlot()
    def _open_tasks_history(self) -> None:
        QDesktopServices.openUrl(self._tasks_manager.api().tasks_history_url())

    @pyqtSlot()
    def _open_settings(self) -> None:
        self._qgis_iface.showOptionsDialog(
            self._qgis_iface.mainWindow(),
            PLUGIN_NAME,
        )
