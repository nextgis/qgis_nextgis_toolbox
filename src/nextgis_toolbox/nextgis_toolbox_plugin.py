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

from typing import Optional

from qgis.core import Qgis, QgsApplication, QgsTaskManager
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import pyqtSlot

from nextgis_toolbox.api.authentication import (
    ToolboxAuthentication,
    ToolboxTokenAuthentication,
)
from nextgis_toolbox.api.client import ToolboxApiClient
from nextgis_toolbox.core.exceptions import ToolboxError
from nextgis_toolbox.core.logging import logger
from nextgis_toolbox.core.utils import assert_not_none
from nextgis_toolbox.nextgis_toolbox_interface import (
    NextgisToolboxInterface,
)
from nextgis_toolbox.processing.nextgis_toolbox_processing_provider import (
    NextgisToolboxProcessingProvider,
)
from nextgis_toolbox.settings.nextgis_toolbox_settings import (
    AuthenticationType,
    NextgisToolboxSettings,
)
from nextgis_toolbox.tasks.api import TasksApi
from nextgis_toolbox.tasks.tasks_interface import (
    TasksInterface,
)
from nextgis_toolbox.tasks.tasks_manager import TasksManager
from nextgis_toolbox.tools.api import ToolsApi
from nextgis_toolbox.tools.tools_interface import (
    ToolsInterface,
)
from nextgis_toolbox.tools.tools_manager import ToolsManager
from nextgis_toolbox.ui.plugin_ui_manager import PluginUiManager


class NextgisToolboxPlugin(NextgisToolboxInterface):
    """NextGIS Toolbox"""

    _api_client: ToolboxApiClient
    _tools_manager: ToolsInterface
    _tasks_manager: TasksInterface
    _qgis_task_manager: QgsTaskManager
    _processing_provider: NextgisToolboxProcessingProvider
    _ui_manager: Optional[PluginUiManager]

    def __init__(self, iface: QgisInterface) -> None:
        super().__init__(iface)

        self._api_client = None  # type: ignore
        self._tools_manager = None  # type: ignore
        self._tasks_manager = None  # type: ignore
        self._qgis_task_manager = None  # pyright: ignore[reportAttributeAccessIssue]
        self._processing_provider = None  # pyright: ignore[reportAttributeAccessIssue]
        self._ui_manager = None

    @pyqtSlot()
    def open_about_dialog(self) -> None:
        if self._ui_manager is None:
            self.notifier.display_message(
                self.tr("About dialog is unavailable."),
                level=Qgis.MessageLevel.Warning,
            )
            return

        self._ui_manager.open_about_dialog()

    @property
    def tools_manager(self) -> ToolsInterface:
        """Return the tools feature manager.

        :returns: Tools feature interface instance.

        :raises NextgisToolboxError: If tools manager is not initialized.
        """
        return assert_not_none(
            self._tools_manager,
            "Tools manager is not initialized",
        )

    @property
    def tasks_manager(self) -> TasksInterface:
        """Return the tasks feature manager.

        :returns: Tasks feature interface instance.

        :raises NextgisToolboxError: If tasks manager is not initialized.
        """
        return assert_not_none(
            self._tasks_manager,
            "Tasks manager is not initialized",
        )

    @property
    def processing_provider(self) -> NextgisToolboxProcessingProvider:
        """Return the Processing provider instance.

        :returns: Processing provider instance.
        """
        return assert_not_none(
            self._processing_provider,
            "Processing provider is not initialized",
        )

    @property
    def api_client(self) -> ToolboxApiClient:
        return assert_not_none(
            self._api_client,
            "API client is not initialized",
        )

    @property
    def qgis_tasks_manager(self) -> QgsTaskManager:
        return assert_not_none(
            self._qgis_task_manager,
            "Plugin Task manager is not initialized",
        )

    def _load_ui(self) -> bool:
        """Initialize GUI elements."""
        self._ui_manager = PluginUiManager(
            qgis_iface=self.qgis_iface,
            notifier=self.notifier,
            api_client=self.api_client,
            tools_manager=self.tools_manager,
            tasks_manager=self.tasks_manager,
            processing_provider=self.processing_provider,
            parent=self,
        )
        self._ui_manager.load()

        self.tools_manager.refresh()

        self.settings_changed.connect(self._on_settings_changed)

        return True

    def _load_processing(self) -> bool:
        """
        Initialize and register the Processing provider.
        """
        self._qgis_task_manager = QgsTaskManager(self)

        self._api_client = self._create_api_client()

        self._tools_manager = ToolsManager(ToolsApi(self._api_client), self)
        self._tools_manager.load()

        self._tasks_manager = TasksManager(TasksApi(self._api_client), self)
        self._tasks_manager.load()

        if self.mode != self.Mode.GUI:
            self._tools_manager.refresh()

        self._processing_provider = NextgisToolboxProcessingProvider(
            tools_manager=self._tools_manager,
            tasks_manager=self._tasks_manager,
        )

        if not QgsApplication.processingRegistry().addProvider(
            self._processing_provider
        ):
            raise ToolboxError("Failed to register Processing provider")

        return True

    def _unload_ui(self) -> None:
        if self._ui_manager is None:
            return

        self._ui_manager.unload()
        self._ui_manager.deleteLater()
        self._ui_manager = None

    def _unload_processing(self) -> None:
        """
        Remove Processing provider from QGIS registry.
        """
        if self._processing_provider is not None:
            QgsApplication.processingRegistry().removeProvider(
                self._processing_provider
            )

            self._processing_provider = None  # pyright: ignore[reportAttributeAccessIssue]

        if self._tools_manager is not None:
            self._tools_manager.unload()

        if self._qgis_task_manager is not None:
            self._qgis_task_manager.cancelAll()
            for task in self._qgis_task_manager.activeTasks():
                task.waitForFinished(0)

        if self._tools_manager is not None:
            self._tools_manager.deleteLater()
            del self._tools_manager

        if self._tasks_manager is not None:
            self._tasks_manager.unload()
            self._tasks_manager.deleteLater()
            del self._tasks_manager

        if self._api_client is not None:
            self._api_client.deleteLater()
            del self._api_client

        if self._qgis_task_manager is not None:
            self._qgis_task_manager.deleteLater()
            del self._qgis_task_manager

    def _create_authentication(
        self,
        authentication_type: AuthenticationType,
        authentication_token: Optional[str],
    ) -> Optional[ToolboxAuthentication]:
        """Create an authentication object from current settings."""
        if authentication_type != AuthenticationType.TOKEN:
            return None

        token = authentication_token
        if not token:
            return None

        return ToolboxTokenAuthentication(token)

    def _is_authentication_changed(
        self,
        authentication_type: AuthenticationType,
        authentication_token: Optional[str],
    ) -> bool:
        """Check whether client authentication differs from saved settings."""
        new_auth = self._create_authentication(
            authentication_type, authentication_token
        )

        return self._api_client.authentication != new_auth

    def _create_api_client(self) -> ToolboxApiClient:
        """Create and configure API client based on current settings."""
        settings = NextgisToolboxSettings()
        authentication_type = settings.authentication_type
        authentication_token = settings.authentication_token

        authentication = self._create_authentication(
            authentication_type, authentication_token
        )

        return ToolboxApiClient(
            self,
            self._qgis_profile_name(),
            endpoint=settings.endpoint,
            authentication=authentication,
        )

    def _qgis_profile_name(self) -> str:
        user_profile_manager = self.qgis_iface.userProfileManager()
        if not user_profile_manager:
            return "default"

        user_profile = user_profile_manager.userProfile()
        if user_profile is None:
            return "default"

        profile_name = user_profile.name()

        return profile_name or "default"

    @pyqtSlot()
    def _on_settings_changed(self) -> None:
        if self._ui_manager is not None:
            self._ui_manager.reset_refresh_feedback_delay()

        self._update_api_client()

    @pyqtSlot()
    def _update_api_client(self) -> None:
        """Update the shared API client only when connection settings change."""
        settings = NextgisToolboxSettings()
        endpoint_changed = self._api_client.endpoint != settings.endpoint
        authentication_changed = self._is_authentication_changed(
            settings.authentication_type, settings.authentication_token
        )
        semantic_integration_changed = (
            self.tools_manager.is_semantic_enrichment_enabled
            != settings.is_experimental_qgis_integration_enabled
        )

        if (
            not endpoint_changed
            and not authentication_changed
            and not semantic_integration_changed
        ):
            logger.debug("Connection settings is unchanged")
            return

        if endpoint_changed:
            logger.debug("API client endpoint updated")
            self._api_client.endpoint = settings.endpoint

        if authentication_changed:
            logger.debug("API client authentication updated")
            self._api_client.authentication = self._create_authentication(
                settings.authentication_type, settings.authentication_token
            )

        if semantic_integration_changed:
            logger.debug("Experimental QGIS integration setting updated")
            self.tools_manager.set_semantic_enrichment_enabled(
                settings.is_experimental_qgis_integration_enabled
            )

        self.tools_manager.refresh(
            clear_cache=endpoint_changed or authentication_changed,
        )
