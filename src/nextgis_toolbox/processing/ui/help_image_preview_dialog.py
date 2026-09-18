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

from pathlib import Path
from typing import Optional

from qgis.gui import QgsExternalResourceWidget
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class HelpImagePreviewWidget(QWidget):
    def __init__(
        self,
        image_path: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self._viewer = QgsExternalResourceWidget(self)
        self._viewer.setDocumentViewerContent(
            QgsExternalResourceWidget.DocumentViewerContent.Image
        )
        self._viewer.setFileWidgetVisible(False)
        self._viewer.setDocumentViewerWidth(0)
        self._viewer.setDocumentViewerHeight(0)
        self._viewer.setReadOnly(True)
        self._viewer.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._viewer)

        self.set_image_path(image_path)

    def set_image_path(self, image_path: str) -> None:
        image_file = Path(image_path)
        if image_file.is_file():
            self._viewer.setDocumentPath(str(image_file))
            return

        self._viewer.setDocumentPath("")


class HelpImagePreviewDialog(QDialog):
    def __init__(
        self,
        image_path: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Image preview"))
        self.resize(900, 700)

        self._preview_widget = HelpImagePreviewWidget(image_path, self)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close,
            self,
        )
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._preview_widget)
        layout.addWidget(buttons)
