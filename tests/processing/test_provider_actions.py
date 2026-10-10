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
from qgis.PyQt.QtCore import QUrl

from nextgis_toolbox.processing.parameters import (
    create_default_parameter_registry,
)
from nextgis_toolbox.settings.nextgis_toolbox_settings import (
    AuthenticationType,
    NextgisToolboxSettings,
)
from nextgis_toolbox.tools.models import ToolsManagerState


def _import_processing_modules():
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

    actions_module = importlib.import_module(
        "nextgis_toolbox.processing.ui.provider_actions"
    )
    interface_module = importlib.import_module(
        "nextgis_toolbox.nextgis_toolbox_interface"
    )
    provider_module = importlib.import_module(
        "nextgis_toolbox.processing.nextgis_toolbox_processing_provider"
    )
    provider_actions_module = importlib.import_module(
        "processing.gui.ProviderActions"
    )

    return (
        actions_module,
        interface_module,
        provider_module,
        provider_actions_module,
    )


def _create_algorithm():
    algorithm_module = importlib.import_module(
        "nextgis_toolbox.processing.toolbox_algorithm"
    )
    models_module = importlib.import_module("nextgis_toolbox.tools.models")

    tool = models_module.ToolboxTool(
        alias="Demo Tool",
        can_run=True,
        description="Description",
        help="<p>Docs</p>",
        id=1,
        is_dev=False,
        is_featured=False,
        is_free=True,
        is_new=False,
        name="demo-tool",
        tag_ids=[],
    )

    tasks_manager = Mock()
    tasks_manager.api.return_value.api_client.endpoint = (
        "https://toolbox.nextgis.com"
    )
    return algorithm_module.ToolboxAlgorithm(
        tool,
        tasks_manager,
        parameter_registry=create_default_parameter_registry(),
    )


def test_provider_browser_action_opens_configured_toolbox_page(
    monkeypatch,
    qgis_app,
) -> None:
    del qgis_app

    actions_module, interface_module, _, _ = _import_processing_modules()
    settings = NextgisToolboxSettings()
    settings.endpoint = "https://sandbox.nextgis.test"
    plugin = Mock()
    plugin.api_client.endpoint = settings.endpoint
    monkeypatch.setattr(
        interface_module.NextgisToolboxInterface,
        "instance",
        classmethod(lambda cls: plugin),
    )

    opened_urls = []
    monkeypatch.setattr(
        actions_module.QDesktopServices,
        "openUrl",
        lambda url: opened_urls.append(url.toString()),
    )
    action = actions_module.OpenProviderInBrowserAction()

    action.execute()

    assert opened_urls == ["https://sandbox.nextgis.test"]
    assert not action.getIcon().isNull()


def test_provider_tasks_history_action_opens_configured_orders_page(
    monkeypatch,
    qgis_app,
) -> None:
    del qgis_app

    actions_module, interface_module, _, _ = _import_processing_modules()
    settings = NextgisToolboxSettings()
    settings.endpoint = "https://sandbox.nextgis.test"
    plugin = Mock()
    plugin.tasks_manager.api.return_value.tasks_history_url.return_value = (
        QUrl(settings.endpoint + "/orders")
    )
    monkeypatch.setattr(
        interface_module.NextgisToolboxInterface,
        "instance",
        classmethod(lambda cls: plugin),
    )

    opened_urls = []
    monkeypatch.setattr(
        actions_module.QDesktopServices,
        "openUrl",
        lambda url: opened_urls.append(url.toString()),
    )
    action = actions_module.OpenProviderTasksHistoryAction()

    action.execute()

    assert opened_urls == ["https://sandbox.nextgis.test/orders"]
    assert not action.getIcon().isNull()


def test_provider_settings_action_opens_plugin_settings(
    monkeypatch,
    qgis_app,
) -> None:
    del qgis_app

    actions_module, interface_module, _, _ = _import_processing_modules()

    plugin_mock = Mock()
    monkeypatch.setattr(
        interface_module.NextgisToolboxInterface,
        "instance",
        classmethod(lambda cls: plugin_mock),
    )
    action = actions_module.OpenProviderSettingsAction()

    action.execute()

    plugin_mock.open_settings.assert_called_once_with()
    assert not action.getIcon().isNull()


def test_provider_about_action_opens_about_dialog(
    monkeypatch,
    qgis_app,
) -> None:
    del qgis_app

    actions_module, interface_module, _, _ = _import_processing_modules()

    plugin_mock = Mock()
    monkeypatch.setattr(
        interface_module.NextgisToolboxInterface,
        "instance",
        classmethod(lambda cls: plugin_mock),
    )
    action = actions_module.OpenProviderAboutAction()

    action.execute()

    plugin_mock.open_about_dialog.assert_called_once_with()
    assert not action.getIcon().isNull()


def test_provider_refresh_action_triggers_full_reload(
    monkeypatch,
    qgis_app,
) -> None:
    del qgis_app

    actions_module, interface_module, _, _ = _import_processing_modules()
    plugin_mock = Mock()
    plugin_mock.tools_manager.state = ToolsManagerState.LOADED
    monkeypatch.setattr(
        interface_module.NextgisToolboxInterface,
        "instance",
        classmethod(lambda cls: plugin_mock),
    )
    action = actions_module.RefreshProviderToolsAction()

    assert action.isEnabled() is True

    action.execute()

    plugin_mock.tools_manager.refresh.assert_called_once_with(clear_cache=True)
    assert not action.getIcon().isNull()


def test_tool_browser_action_opens_tool_page(monkeypatch, qgis_app) -> None:
    del qgis_app

    actions_module, _, _, _ = _import_processing_modules()
    algorithm = _create_algorithm()

    opened_urls = []
    monkeypatch.setattr(
        actions_module.QDesktopServices,
        "openUrl",
        lambda url: opened_urls.append(url.toString()),
    )

    action = actions_module.OpenToolInBrowserAction()
    action.setData(algorithm, Mock())

    assert action.isEnabled() is True
    assert action.name == "Open Tool in Browser"

    action.execute()

    assert opened_urls == [algorithm.tool_web_url()]
    assert not action.icon().isNull()


def test_tool_documentation_action_opens_tool_docs(
    monkeypatch,
    qgis_app,
) -> None:
    del qgis_app

    actions_module, _, _, _ = _import_processing_modules()
    algorithm = _create_algorithm()

    opened_urls = []
    monkeypatch.setattr(
        actions_module.QDesktopServices,
        "openUrl",
        lambda url: opened_urls.append(url.toString()),
    )

    action = actions_module.OpenToolDocumentationAction()
    action.setData(algorithm, Mock())

    assert action.isEnabled() is True

    action.execute()

    assert opened_urls == [algorithm.helpUrl()]
    assert not action.icon().isNull()


def test_processing_provider_registers_and_unregisters_actions(
    monkeypatch,
    qgis_app,
) -> None:
    del qgis_app

    _, _, provider_module, provider_actions_module = (
        _import_processing_modules()
    )
    from nextgis_toolbox.processing.ui.panel_actions_integrator import (
        PanelActionsIntegrator,
    )

    qgis.utils.iface.messageBar.return_value.items.return_value = []

    tools_manager = Mock()
    tools_manager.tools.return_value = []
    tools_manager.state = ToolsManagerState.LOADED

    tasks_manager = Mock()
    tasks_manager.error_message = ""
    tasks_manager.api.return_value.api_client.authentication_type = (
        AuthenticationType.TOKEN
    )

    provider = provider_module.NextgisToolboxProcessingProvider(
        tools_manager=tools_manager,
        tasks_manager=tasks_manager,
    )
    integrator = PanelActionsIntegrator(qgis.utils.iface, provider)
    integrator.load()
    assert len(integrator._button_actions) == 5
    assert len(integrator._tool_actions) == 2
    for action in integrator._tool_actions:
        assert (
            action
            in provider_actions_module.ProviderContextMenuActions.actions
        )

    integrator.unload()
    for action in integrator._tool_actions:
        assert (
            action
            not in provider_actions_module.ProviderContextMenuActions.actions
        )


def test_processing_provider_loads_status_stub_while_catalog_is_loading(
    qgis_app,
) -> None:
    del qgis_app

    _, _, provider_module, _ = _import_processing_modules()

    tools_manager = Mock()
    tools_manager.state = ToolsManagerState.LOADING

    tasks_manager = Mock()
    tasks_manager.error_message = ""
    tasks_manager.api.return_value.api_client.authentication_type = (
        AuthenticationType.TOKEN
    )

    provider = provider_module.NextgisToolboxProcessingProvider(
        tools_manager=tools_manager,
        tasks_manager=tasks_manager,
    )
    provider.addAlgorithm = Mock()

    provider.loadAlgorithms()

    status_algorithm = provider.addAlgorithm.call_args[0][0]
    assert status_algorithm.displayName() == "Loading tools…"


def test_processing_provider_emits_algorithm_instance_created_signal(
    qgis_app,
) -> None:
    del qgis_app

    _, _, provider_module, _ = _import_processing_modules()

    tools_manager = Mock()
    tools_manager.tools.return_value = []
    tools_manager.state = ToolsManagerState.LOADED

    tasks_manager = Mock()
    tasks_manager.error_message = ""
    provider = provider_module.NextgisToolboxProcessingProvider(
        tools_manager=tools_manager,
        tasks_manager=tasks_manager,
    )
    signal_handler = Mock()
    provider.algorithm_instance_created.connect(signal_handler)

    provider.load()
    algorithm = _create_algorithm()
    assert provider.addAlgorithm(algorithm)

    clone = algorithm.createInstance()

    signal_handler.assert_called_once_with(clone)


def test_processing_provider_warning_uses_saved_token(
    qgis_app,
) -> None:
    del qgis_app

    settings = NextgisToolboxSettings()
    settings.authentication_type = AuthenticationType.NONE
    settings.authentication_token = "secret-token"

    assert settings.authentication_type == AuthenticationType.TOKEN
