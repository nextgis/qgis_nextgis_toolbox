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

from qgis.PyQt.QtCore import QCoreApplication, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QIcon

from nextgis_toolbox.nextgis_toolbox_interface import (
    NextgisToolboxInterface,
)
from nextgis_toolbox.processing.toolbox_algorithm import (
    ToolboxAlgorithm,
)
from nextgis_toolbox.processing.ui.compat import ProcessingToolbox
from nextgis_toolbox.tools.models import ToolsManagerState
from nextgis_toolbox.ui.icon import plugin_icon, qgis_icon


class ContextAction:
    def __init__(self) -> None:
        self.name = None
        self.is_separator = False
        self.itemData: Optional[object] = None
        self.toolbox: Optional[ProcessingToolbox] = None

    def setData(  # noqa: N802
        self,
        itemData: object,
        toolbox: ProcessingToolbox,
    ) -> None:
        self.itemData = itemData
        self.toolbox = toolbox

    def tr(self, string: str, context: str = "") -> str:
        if context == "":
            context = self.__class__.__name__
        return QCoreApplication.translate(context, string)

    def icon(self) -> QIcon:
        return QIcon()

    def isEnabled(self) -> bool:  # noqa: N802
        return True

    def execute(self) -> None:
        pass


class ToolboxAction:
    def __init__(self) -> None:
        self.name = ""
        self.toolbox: Optional[ProcessingToolbox] = None

    def setData(self, toolbox: ProcessingToolbox) -> None:  # noqa: N802
        self.toolbox = toolbox

    def getIcon(self) -> QIcon:  # noqa: N802
        return QIcon()

    def isEnabled(self) -> bool:  # noqa: N802
        return True

    def tr(self, string: str, context: str = "") -> str:
        if context == "":
            context = self.__class__.__name__
        return QCoreApplication.translate(context, string)

    def execute(self) -> None:
        pass


class _ToolAlgorithmAction(ContextAction):
    def __init__(self, action_name: str) -> None:
        super().__init__()
        self.name = action_name

    def icon(self) -> QIcon:
        return plugin_icon()

    def isEnabled(self) -> bool:
        return self._algorithm() is not None

    def _algorithm(self) -> Optional[ToolboxAlgorithm]:
        if isinstance(self.itemData, ToolboxAlgorithm):
            algorithm = self.itemData
            return algorithm

        return None

    def _open_url(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))


class _ProviderAction(ToolboxAction):
    def __init__(self, action_name: str) -> None:
        super().__init__()
        self.name = action_name


class _ProviderBrowserAction(_ProviderAction):
    def getIcon(self) -> QIcon:
        return plugin_icon()

    def _open_url(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))


class OpenProviderInBrowserAction(_ProviderBrowserAction):
    def __init__(self) -> None:
        super().__init__(self.tr("Open in Browser"))

    def execute(self) -> None:
        plugin = NextgisToolboxInterface.instance()
        self._open_url(plugin.api_client.endpoint)


class OpenProviderTasksHistoryAction(_ProviderAction):
    def __init__(self) -> None:
        super().__init__(self.tr("Tasks history"))

    def getIcon(self) -> QIcon:
        return qgis_icon("mIconHistory.svg")

    def execute(self) -> None:
        plugin = NextgisToolboxInterface.instance()
        QDesktopServices.openUrl(
            plugin.tasks_manager.api().tasks_history_url()
        )


class RefreshProviderToolsAction(_ProviderAction):
    def __init__(self) -> None:
        super().__init__(self.tr("Refresh tools"))

    def getIcon(self) -> QIcon:
        return qgis_icon("mActionRefresh.svg")

    def isEnabled(self) -> bool:
        plugin = NextgisToolboxInterface.instance()
        return plugin.tools_manager.state != ToolsManagerState.LOADING

    def execute(self) -> None:
        plugin = NextgisToolboxInterface.instance()
        plugin.tools_manager.refresh(clear_cache=True)


class OpenProviderSettingsAction(_ProviderAction):
    def __init__(self) -> None:
        super().__init__(self.tr("Settings…"))

    def getIcon(self) -> QIcon:
        return qgis_icon("mActionOptions.svg")

    def execute(self) -> None:
        NextgisToolboxInterface.instance().open_settings()


class OpenProviderAboutAction(_ProviderAction):
    def __init__(self) -> None:
        super().__init__(self.tr("About…"))

    def getIcon(self) -> QIcon:
        return qgis_icon("mActionPropertiesWidget.svg")

    def execute(self) -> None:
        NextgisToolboxInterface.instance().open_about_dialog()


class OpenToolInBrowserAction(_ToolAlgorithmAction):
    def __init__(self) -> None:
        super().__init__(self.tr("Open Tool in Browser"))

    def execute(self) -> None:
        algorithm = self._algorithm()
        if algorithm is None:
            return

        self._open_url(algorithm.tool_web_url())


class OpenToolDocumentationAction(_ToolAlgorithmAction):
    def __init__(self) -> None:
        super().__init__(self.tr("Open Documentation"))

    def execute(self) -> None:
        algorithm = self._algorithm()
        if algorithm is None:
            return

        self._open_url(algorithm.helpUrl())
