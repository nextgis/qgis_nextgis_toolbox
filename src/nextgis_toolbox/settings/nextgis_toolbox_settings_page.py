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
from typing import List, Optional

from qgis.gui import QgsOptionsPageWidget, QgsOptionsWidgetFactory
from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from nextgis_toolbox.core.constants import COMPANY_NAME, DEFAULT_API_ENDPOINT
from nextgis_toolbox.core.exceptions import ToolboxUiLoadError
from nextgis_toolbox.core.logging import logger, update_logging_level
from nextgis_toolbox.nextgis_toolbox_interface import (
    NextgisToolboxInterface,
)
from nextgis_toolbox.settings.nextgis_toolbox_settings import (
    NextgisToolboxSettings,
)
from nextgis_toolbox.shared.ui.input_field import (
    EditorType,
    FieldsForm,
    InputField,
    UrlValidator,
    UuidValidator,
)
from nextgis_toolbox.ui.icon import plugin_icon


class NextgisToolboxSettingsPage(QgsOptionsPageWidget):
    """Integrate the NextGIS Toolbox settings page into QGIS options."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialize the settings page widget.

        :param parent: Optional parent widget.
        """
        super().__init__(parent)
        self._initialize_ui()

    def apply(self) -> None:
        """Save current settings when the user confirms changes."""
        if not self._settings_form.save():
            return

        settings = NextgisToolboxSettings()
        settings.endpoint = self._endpoint_field.value
        settings.authentication_token = self._api_key_field.value

        old_debug_enabled = settings.is_debug_logs_enabled
        new_debug_enabled = self._widget.debug_checkbox.isChecked()
        settings.is_debug_logs_enabled = new_debug_enabled
        if old_debug_enabled != new_debug_enabled:
            debug_state = "enabled" if new_debug_enabled else "disabled"
            update_logging_level()
            logger.warning(f"Debug messages were {debug_state}")

        settings.is_experimental_qgis_integration_enabled = (
            self._widget.experimental_qgis_integration_checkbox.isChecked()
        )

        plugin = NextgisToolboxInterface.instance()
        plugin.settings_changed.emit()

    def cancel(self) -> None:
        """Cancel changes made in the settings page."""

    def _initialize_ui(self) -> None:
        """Initialize the settings page user interface."""
        self._load_ui()
        self._create_settings_form()
        self._load_other_settings()
        self._widget.experimental_qgis_integration_checkbox.setToolTip(
            self.tr(
                "Enable experimental semantic-driven QGIS integration for "
                "Toolbox parameters and outputs."
            )
        )

        page_layout = QHBoxLayout()
        page_layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(page_layout)
        page_layout.addWidget(self._widget)

    def _load_ui(self) -> None:
        """Load the designer UI and prepare its root widget."""
        plugin_path = Path(__file__).parents[1]
        widget: Optional[QWidget] = None
        try:
            widget = uic.loadUi(
                str(
                    plugin_path
                    / "ui"
                    / "nextgis_toolbox_settings_page_base.ui"
                )
            )  # type: ignore
        except FileNotFoundError as error:
            message = self.tr("Failed to load settings UI")
            logger.exception(message)
            raise ToolboxUiLoadError(
                log_message=message,
                user_message=message,
            ) from error

        if widget is None:
            log_message = "Settings UI loading returned no widget"
            user_message = self.tr("Failed to load settings UI")
            logger.error(log_message)
            raise ToolboxUiLoadError(
                log_message=log_message,
                user_message=user_message,
            )

        self._widget = widget
        self._widget.setParent(self)

    def _create_settings_form(self) -> None:
        """Create input fields initialized from persisted settings."""
        settings = NextgisToolboxSettings()
        self._endpoint_field = InputField(
            title=self.tr("Endpoint"),
            editor_type=EditorType.TEXT_EDITOR,
            value=settings.endpoint,
            default_value=DEFAULT_API_ENDPOINT,
            placeholder=DEFAULT_API_ENDPOINT,
            tooltip=self.tr("Set the base endpoint for NextGIS Toolbox API."),
            is_required=True,
            required_message=self.tr("Enter the NextGIS Toolbox API endpoint"),
            invalid_message=self.tr("Enter a valid HTTP or HTTPS URL"),
        )
        self._api_key_field = InputField(
            title=self.tr("Toolbox API Key"),
            editor_type=EditorType.TEXT_EDITOR,
            value=settings.authentication_token,
            default_value="",
            tooltip=self.tr("Set the API key used to access NextGIS Toolbox."),
            invalid_message=self.tr("Enter a valid API key UUID"),
        )
        self._settings_form = FieldsForm(
            parent=self._widget.nextgis_toolbox_token_group_box,
            orientation=Qt.Orientation.Horizontal,
        )
        self._settings_form.add_field(
            self._endpoint_field,
            validator=UrlValidator(),
        )
        self._settings_form.add_field(
            self._api_key_field,
            validator=UuidValidator(),
        )
        self._widget.authentication_layout.insertWidget(
            0,
            self._settings_form,
        )

    def _load_other_settings(self) -> None:
        """Load settings that are not represented by input fields."""
        settings = NextgisToolboxSettings()
        self._widget.debug_checkbox.setChecked(settings.is_debug_logs_enabled)
        self._widget.experimental_qgis_integration_checkbox.setChecked(
            settings.is_experimental_qgis_integration_enabled
        )


class NextgisToolboxSettingsErrorPage(QgsOptionsPageWidget):
    """Show a fallback page when settings UI loading fails."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialize the error page widget.

        :param parent: Optional parent widget.
        """
        super().__init__(parent)
        self.widget = QLabel(
            self.tr("An error occurred while loading settings page"), self
        )
        self.widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.addWidget(self.widget)

    def apply(self) -> None:
        """Apply changes as a no-op for the error page."""

    def cancel(self) -> None:
        """Cancel changes as a no-op for the error page."""


class NextgisToolboxSettingsPageFactory(QgsOptionsWidgetFactory):
    """Register the plugin options page under QGIS settings."""

    def __init__(self) -> None:
        """Initialize the settings page factory."""
        super().__init__("NextGIS Toolbox", plugin_icon())

    def path(self) -> List[str]:
        """Return the settings page path.

        :returns: List of path elements.
        """
        return [COMPANY_NAME]

    def createWidget(
        self,
        parent: Optional[QWidget] = None,
    ) -> Optional[QgsOptionsPageWidget]:
        """Create the settings widget or a fallback error page.

        :param parent: Optional parent widget.
        :returns: Initialized settings or error page.
        """
        try:
            return NextgisToolboxSettingsPage(parent)
        except Exception:
            logger.exception("An error occurred while loading settings page")
            return NextgisToolboxSettingsErrorPage(parent)
