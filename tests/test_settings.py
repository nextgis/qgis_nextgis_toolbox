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

from qgis.core import QgsSettings

from nextgis_toolbox.settings.nextgis_toolbox_settings import (
    AuthenticationType,
    NextgisToolboxSettings,
)
from nextgis_toolbox.settings.nextgis_toolbox_settings_page import (
    NextgisToolboxSettingsPage,
)


def test_settings_restore_saved_authentication_type(qgis_app) -> None:
    del qgis_app

    settings = NextgisToolboxSettings()
    settings.authentication_type = AuthenticationType.NONE

    assert settings.authentication_type == AuthenticationType.NONE


def test_settings_token_forces_token_authentication(qgis_app) -> None:
    del qgis_app

    settings = NextgisToolboxSettings()
    settings.authentication_type = AuthenticationType.NONE
    settings.authentication_token = "secret-token"

    assert settings.authentication_type == AuthenticationType.TOKEN


def test_settings_persists_endpoint(qgis_app) -> None:
    del qgis_app

    settings = NextgisToolboxSettings()
    settings.endpoint = "https://sandbox.nextgis.test"

    assert settings.endpoint == "https://sandbox.nextgis.test"


def test_settings_disable_experimental_qgis_integration_by_default(
    qgis_app,
) -> None:
    del qgis_app

    settings = NextgisToolboxSettings()
    QgsSettings().remove(settings.KEY_IS_EXPERIMENTAL_QGIS_INTEGRATION_ENABLED)

    assert settings.is_experimental_qgis_integration_enabled is False


def test_settings_persist_experimental_qgis_integration(qgis_app) -> None:
    del qgis_app

    settings = NextgisToolboxSettings()
    settings.is_experimental_qgis_integration_enabled = True

    assert settings.is_experimental_qgis_integration_enabled is True


def test_settings_page_shows_api_key_documentation_link(qgis_app) -> None:
    del qgis_app

    settings_page = NextgisToolboxSettingsPage()

    try:
        documentation_label = (
            settings_page._widget.toolbox_token_documentation_label
        )
        authentication_layout = settings_page._widget.authentication_layout

        assert authentication_layout.itemAt(0).widget() is (
            settings_page._settings_form
        )
        assert authentication_layout.itemAt(1).widget() is documentation_label
        assert documentation_label.openExternalLinks() is True
        assert (
            "https://docs.nextgis.com/docs_ngqgis/source/toolbox.html#api-key"
            in documentation_label.text()
        )
    finally:
        settings_page.deleteLater()
