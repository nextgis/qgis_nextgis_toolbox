import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, cast
from urllib.parse import urlsplit

# QGIS adds its bundled plugin directory to sys.path at desktop startup.
import processing  # pyright: ignore[reportMissingImports]
import qgis.utils
from qgis.core import (
    QgsApplication,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProject,
)
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import QAction

if TYPE_CHECKING:
    from nextgis_toolbox.nextgis_toolbox_plugin import NextgisToolboxPlugin


class DesktopTools:
    """Small script API, also usable directly through QGIS MCP."""

    def __init__(self, iface: QgisInterface, root: Path) -> None:
        self.iface = iface
        self.root = Path(root)
        self.dialog = None

    @property
    def plugin(self) -> "NextgisToolboxPlugin":
        return cast(
            "NextgisToolboxPlugin", qgis.utils.plugins["nextgis_toolbox"]
        )

    def state(self) -> Dict[str, Any]:
        if self.plugin.mode == self.plugin.Mode.ERROR:
            return {
                "state": "error",
                "catalog_error": "Plugin initialization failed; see messages.log",
            }
        manager = self.plugin.tools_manager
        provider = QgsApplication.processingRegistry().providerById(
            "nextgis_toolbox"
        )
        return {
            "state": str(manager.state),
            "catalog_error": str(manager.error) if manager.error else None,
            "plugin_path": qgis.utils.plugins["nextgis_toolbox"].__module__,
            "source_path": __import__("nextgis_toolbox").__file__,
            "provider": provider is self.plugin.processing_provider,
            "tools": len(manager.tools()),
            "algorithms": len(provider.algorithms()) if provider else 0,
            "menu": self.plugin._ui_manager is not None
            and self.plugin._ui_manager._settings_action is not None,
        }

    def catalog(self) -> List[Dict[str, Any]]:
        """Return tool names, demo availability and account execution access."""
        return [
            {
                "name": tool.name,
                "demo": tool.demo_preset() is not None,
                "can_run": tool.can_run,
            }
            for tool in self.plugin.tools_manager.tools()
        ]

    def ui(self) -> Dict[str, Any]:
        # Inspect actual registered objects, not translated label snapshots.
        manager = self.plugin._ui_manager
        assert manager is not None, "Desktop UI manager is missing"
        actions = [
            manager._refresh_tools_action,
            manager._settings_action,
            manager._about_action,
            manager._tasks_history_action,
            manager._open_website_action,
        ]
        assert all(isinstance(action, QAction) for action in actions)
        assert all(
            action in manager._plugin_menu.actions() for action in actions
        )
        assert manager._options_factory is not None
        assert (
            manager._show_help_action in self.iface.pluginHelpMenu().actions()
        )
        assert (
            manager._plugin_menu.menuAction()
            in manager._find_processing_menu().actions()
        )
        assert manager._tools_menu.actions(), "Tools menu is empty"
        return {"actions": len(actions), "settings": True, "help": True}

    def refresh(self) -> str:
        """Trigger the real refresh action and return its immediate state."""
        self.plugin._ui_manager._refresh_tools_action.trigger()
        return str(self.plugin.tools_manager.state)

    def open_dialog(self, name: str) -> str:
        """Open a non-modal Processing dialog, replacing only the owned dialog."""
        self.close_dialog()
        algorithm_id = "nextgis_toolbox:" + name
        assert QgsApplication.processingRegistry().algorithmById(
            algorithm_id
        ), algorithm_id
        self.dialog = processing.createAlgorithmDialog(algorithm_id)
        assert self.dialog is not None, algorithm_id
        self.dialog.show()
        return algorithm_id

    def dialog_state(self) -> Dict[str, Any]:
        assert self.dialog is not None
        algorithm = self.dialog.algorithm()
        from nextgis_toolbox.processing.ui.dialog_patches.demo_button import (
            DemoButton,
        )

        return {
            "visible": self.dialog.isVisible(),
            "main_widget": self.dialog.mainWidget() is not None,
            "algorithm": algorithm.name(),
            "help": bool(algorithm.shortHelpString()),
            "demo_button": bool(self.dialog.findChildren(DemoButton)),
            "expected_demo": algorithm.tool.demo_preset() is not None,
        }

    def close_dialog(self) -> None:
        """Close the dialog owned by this probe, leaving other QGIS windows alone."""
        if self.dialog is not None:
            self.dialog.close()
            self.dialog.deleteLater()
            self.dialog = None

    def screenshot(self, name: str = "desktop.png") -> str:
        """Save the owned dialog or main window for failure diagnosis."""
        directory = self.root / "screenshots"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / Path(name).name
        widget = self.dialog or self.iface.mainWindow()
        assert widget.grab().save(str(path)), str(path)
        return str(path)

    def run_demo(self, name: str, timeout: int = 300) -> Dict[str, Any]:
        """Prepare the first demo preset and execute it through Processing.

        Remote submission requires an exact endpoint authorization in the
        environment. Output files stay in this session's artifact directory.
        """
        from nextgis_toolbox.processing.parameters import (
            PresetPreparationContext,
        )
        from nextgis_toolbox.processing.parameters.controls import (
            ADD_RESULTS_TO_PROJECT_PARAMETER_NAME,
            EMAIL_NOTIFICATION_PARAMETER_NAME,
        )
        from nextgis_toolbox.processing.toolbox_algorithm import (
            ToolboxAlgorithm,
        )
        from nextgis_toolbox.tools.models import OutputParameterType

        endpoint = self.plugin.api_client.endpoint
        if urlsplit(endpoint).hostname not in (
            "localhost",
            "127.0.0.1",
            "::1",
        ):
            assert (
                os.environ.get("TOOLBOX_TEST_ALLOW_REMOTE_DEMOS") == endpoint
            ), "Remote demo submission is not authorized"

        tool = self.plugin.tools_manager.tool(name=name)
        preset = tool.demo_preset()
        assert preset is not None, "No demo preset: " + name
        assert tool.can_run, "Tool cannot run with this account: " + name
        algorithm = cast(
            ToolboxAlgorithm,
            QgsApplication.processingRegistry().createAlgorithmById(
                "nextgis_toolbox:" + name
            ),
        )
        output_root = self.root / "outputs" / name
        output_root.mkdir(parents=True, exist_ok=True)
        preset_context = PresetPreparationContext(
            client=self.plugin.api_client,
            algorithm_name=name,
            preset_alias=preset.alias,
            download_root=self.root / "inputs",
        )
        parameters = {}
        for parameter in tool.inputs:
            if parameter.name in preset.inputs:
                parameters.update(
                    algorithm.parameter_registry.prepare_input_preset_values(
                        parameter,
                        preset.inputs[parameter.name],
                        preset_context,
                    )
                )
        for parameter in tool.outputs:
            if parameter.parameter_type == OutputParameterType.FILE:
                parameters[parameter.name] = str(
                    output_root / (parameter.name + ".file")
                )
        parameters[EMAIL_NOTIFICATION_PARAMETER_NAME] = False
        if algorithm.parameterDefinition(
            ADD_RESULTS_TO_PROJECT_PARAMETER_NAME
        ):
            parameters[ADD_RESULTS_TO_PROJECT_PARAMETER_NAME] = False
        context = QgsProcessingContext()
        context.setProject(QgsProject.instance())
        valid, message = algorithm.checkParameterValues(parameters, context)
        assert valid, message
        feedback = QgsProcessingFeedback()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(feedback.cancel)
        timer.start(int(timeout * 1000))
        try:
            results = processing.run(
                algorithm, parameters, context=context, feedback=feedback
            )
            assert not feedback.isCanceled(), "Demo exceeded deadline: " + name
            for parameter in tool.outputs:
                if not parameter.required and parameter.name not in results:
                    continue
                assert parameter.name in results, (
                    "Missing output: " + parameter.name
                )
                if parameter.parameter_type == OutputParameterType.FILE:
                    path = Path(results[parameter.name])
                    assert path.is_file() and path.stat().st_size > 0, str(
                        path
                    )
            return {"tool": name, "outputs": results}
        finally:
            timer.stop()
