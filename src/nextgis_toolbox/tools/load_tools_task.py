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

from typing import Callable, List, Optional, cast

from qgis.core import QgsFeedback, QgsTask

from nextgis_toolbox.core.exceptions import ToolboxError
from nextgis_toolbox.core.logging import logger
from nextgis_toolbox.core.utils import PluginRuntimeProfiler
from nextgis_toolbox.tools.models import (
    ToolboxTag,
    ToolboxTool,
)
from nextgis_toolbox.tools.repository import (
    TagsRepository,
    ToolsRepository,
)


class LoadToolsTask(QgsTask):
    _TAGS_PROGRESS_WEIGHT = 5

    def __init__(
        self,
        tags_repository: TagsRepository,
        tools_repository: ToolsRepository,
        on_finished: Callable[["LoadToolsTask", bool], None],
    ) -> None:
        super().__init__(
            "Load NextGIS Toolbox catalog",
            cast(
                QgsTask.Flag,
                QgsTask.Flag.CanCancel
                | QgsTask.Flag.CancelWithoutPrompt
                | QgsTask.Flag.Hidden,
            ),
        )
        self._tags_repository = tags_repository
        self._tools_repository = tools_repository
        self._on_finished = on_finished
        self._error: Optional[ToolboxError] = None
        self._tags: List[ToolboxTag] = []
        self._tools: List[ToolboxTool] = []
        self._feedback = QgsFeedback(self)
        self._feedback.progressChanged.connect(self.setProgress)

    def cancel(self) -> None:
        self._feedback.cancel()
        super().cancel()

    @property
    def error(self) -> Optional[ToolboxError]:
        return self._error

    @property
    def tags(self) -> List[ToolboxTag]:
        return self._tags

    @property
    def tools(self) -> List[ToolboxTool]:
        return self._tools

    @PluginRuntimeProfiler.wrap("load NextGIS Toolbox catalog")
    def run(self) -> bool:
        try:
            self._tags = self._tags_repository.fetch_tags(self._feedback)
            if self.isCanceled():
                return False

            self.setProgress(self._TAGS_PROGRESS_WEIGHT)
            self._tools = self._tools_repository.fetch_tools(self._feedback)
            self.setProgress(100)

        except ToolboxError as error:
            if self.isCanceled():
                return False

            self._error = error
            logger.error(
                "Failed to load NextGIS Toolbox catalog: %s",
                error,
                exc_info=error,
            )
            return False

        except Exception as error:
            if self.isCanceled():
                return False

            self._error = ToolboxError(
                "An unexpected error occurred while loading the catalog."
            )
            self._error.__cause__ = error

            logger.exception(
                "Failed to load NextGIS Toolbox catalog",
                exc_info=error,
            )
            return False

        return not self.isCanceled()

    def finished(self, result: bool) -> None:
        self._on_finished(self, result)
