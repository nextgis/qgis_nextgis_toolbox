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
from pathlib import Path
from unittest.mock import Mock

from qgis.core import Qgis, QgsProcessingParameterDefinition
from qgis.gui import QgsMessageBar
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QObject, Qt, QUrl
from qgis.PyQt.QtGui import QMovie
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import (
    QApplication,
    QDialogButtonBox,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from nextgis_toolbox.api.client import ToolboxApiClient
from nextgis_toolbox.processing.parameters import (
    create_default_parameter_registry,
)
from nextgis_toolbox.processing.parameters.controls import (
    ADD_RESULTS_TO_PROJECT_PARAMETER_NAME,
)
from nextgis_toolbox.processing.ui.dialog_patcher import AlgorithmDialogPatcher


def _import_dialog_patcher_module():
    return importlib.import_module(
        "nextgis_toolbox.processing.ui.dialog_patches"
    )


def _import_help_patches_module():
    return importlib.import_module(
        "nextgis_toolbox.processing.ui.dialog_patches.help_browser"
    )


def _import_message_bar_patches_module():
    return importlib.import_module(
        "nextgis_toolbox.processing.ui.dialog_patches.message_bar"
    )


def _import_tool_availability_patches_module():
    return importlib.import_module(
        "nextgis_toolbox.processing.ui.dialog_patches.tool_availability"
    )


def _import_demo_button_module():
    return importlib.import_module("nextgis_toolbox.processing.ui.demo_button")


class FakeWrapper:
    def __init__(self) -> None:
        self.value = None

    def setParameterValue(self, value, processing_context) -> None:
        del processing_context
        self.value = value


class FakeParametersPanel(QWidget):
    def __init__(self, algorithm, parent=None) -> None:
        super().__init__(parent)
        self._algorithm = algorithm
        self.processing_context = object()
        self.extra_parameters = {}
        self.wrappers = {
            parameter.name(): FakeWrapper()
            for parameter in algorithm.parameterDefinitions()
        }
        for parameter in algorithm.destinationParameterDefinitions():
            self.wrappers[parameter.name()] = FakeWrapper()

    def setParameters(self, parameters) -> None:
        self.extra_parameters.clear()
        hidden_flag = QgsProcessingParameterDefinition.Flag.FlagHidden

        for parameter in self._algorithm.parameterDefinitions():
            if parameter.name() not in parameters:
                continue

            if parameter.flags() & hidden_flag:
                self.extra_parameters[parameter.name()] = parameters[
                    parameter.name()
                ]
                continue

            wrapper = self.wrappers.get(parameter.name())
            if wrapper is None:
                continue

            wrapper.setParameterValue(
                parameters[parameter.name()],
                self.processing_context,
            )


def _parameter(
    name: str,
    parameter_type: str,
    *,
    required: bool = True,
    choices=None,
):
    models_module = importlib.import_module("nextgis_toolbox.tools.models")
    return models_module.ToolInputParameter(
        name=name,
        parameter_type=models_module.InputParameterType.from_json(
            parameter_type
        ),
        alias=name.replace("_", " ").title(),
        description=None,
        required=required,
        choices=choices,
    )


def _output_parameter(
    name: str,
    parameter_type: str,
    *,
    required: bool = True,
):
    models_module = importlib.import_module("nextgis_toolbox.tools.models")
    return models_module.ToolOutputParameter(
        name=name,
        parameter_type=models_module.OutputParameterType.from_json(
            parameter_type
        ),
        alias=name.replace("_", " ").title(),
        description=None,
        required=required,
    )


def _create_algorithm(
    *,
    can_run: bool,
    with_preset: bool,
    inputs=None,
    outputs=None,
    preset_inputs=None,
    preset_outputs=None,
    client=None,
):
    algorithm_module = importlib.import_module(
        "nextgis_toolbox.processing.toolbox_algorithm"
    )
    models_module = importlib.import_module("nextgis_toolbox.tools.models")

    presets = []
    if with_preset:
        presets.append(
            models_module.ToolPreset(
                alias="Demo preset",
                inputs=preset_inputs or {"source": "demo"},
                outputs=preset_outputs or {},
            )
        )

    tool = models_module.ToolboxTool(
        alias="Demo Tool",
        can_run=can_run,
        description="Description",
        help="<p>Docs</p>",
        id=1,
        is_dev=False,
        is_featured=False,
        is_free=True,
        is_new=False,
        inputs=inputs or [_parameter("source", "string")],
        outputs=outputs or [],
        name="demo-tool",
        tag_ids=[],
        presets=presets,
    )

    tasks_api = Mock()
    tasks_api.api_client = client or Mock(spec=ToolboxApiClient)
    tasks_manager = Mock()
    tasks_manager.api.return_value = tasks_api

    algorithm = algorithm_module.ToolboxAlgorithm(
        tool,
        tasks_manager,
        parameter_registry=create_default_parameter_registry(),
    )
    algorithm.initAlgorithm()
    return algorithm


class FakeAlgorithmDialog(QWidget):
    def __init__(
        self,
        algorithm,
        *,
        reorder_action_buttons_on_tab_change: bool = False,
        reorder_action_buttons_on_reset: bool = False,
    ) -> None:
        super().__init__()
        self._algorithm = algorithm
        self.block_controls_calls = 0
        self.cancel_clicks = 0
        self.feedback = None
        self.reset_additional_gui_calls = 0
        self.was_closed = False
        self.clear_progress_calls = 0
        self._main_widget = FakeParametersPanel(algorithm, self)
        self._message_bar = QgsMessageBar(self)
        self._help_browser = QTextBrowser(self)
        self._help_browser.setObjectName("textShortHelp")
        self._tab_widget = QTabWidget(self)
        self._progress_bar = QProgressBar(self)
        self._button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Close
            | QDialogButtonBox.StandardButton.Help,
            self,
        )
        self._advanced_button = QPushButton("Advanced", self)
        self._button_box.addButton(
            self._advanced_button,
            QDialogButtonBox.ButtonRole.ResetRole,
        )
        self._cancel_button = QPushButton("Cancel", self)
        self._cancel_button.setObjectName("buttonCancel")
        self._cancel_button.clicked.connect(self._record_cancel_click)
        self._parameters = None
        self._reorder_action_buttons_on_reset = reorder_action_buttons_on_reset

        parameters_tab = QWidget(self)
        parameters_layout = QVBoxLayout(parameters_tab)
        parameters_layout.addWidget(self._main_widget)
        self._tab_widget.addTab(parameters_tab, "Parameters")
        self._tab_widget.addTab(QWidget(self), "Log")
        if reorder_action_buttons_on_tab_change:
            self._tab_widget.currentChanged.connect(
                self._reorder_action_buttons
            )

        layout = QVBoxLayout(self)
        layout.addWidget(self._message_bar)
        layout.addWidget(self._help_browser)
        layout.addWidget(self._tab_widget)
        layout.addWidget(self._progress_bar)
        layout.addWidget(self._cancel_button)
        layout.addWidget(self._button_box)

    def algorithm(self):
        return self._algorithm

    def messageBar(self):
        return self._message_bar

    def buttonBox(self):
        return self._button_box

    def mainWidget(self):
        return self._main_widget

    def runButton(self):
        return self._button_box.button(QDialogButtonBox.StandardButton.Ok)

    def cancelButton(self):
        return self._cancel_button

    def setParameters(self, parameters):
        self._parameters = parameters
        self._main_widget.setParameters(parameters)

    def updateRunButtonVisibility(self) -> None:
        return

    def blockControlsWhileRunning(self) -> None:
        self.block_controls_calls += 1
        self._tab_widget.setEnabled(False)
        self._progress_bar.setEnabled(False)
        self.runButton().setEnabled(False)
        self._advanced_button.setEnabled(False)
        self.cancelButton().setEnabled(True)

    def resetAdditionalGui(self) -> None:
        self.reset_additional_gui_calls += 1
        self._tab_widget.setEnabled(True)
        self._progress_bar.setEnabled(True)
        self.runButton().setEnabled(True)
        self._advanced_button.setEnabled(True)
        self.cancelButton().setEnabled(True)
        if self._reorder_action_buttons_on_reset:
            self._reorder_action_buttons(0)

    def clearProgress(self) -> None:
        self.clear_progress_calls += 1
        self._progress_bar.reset()
        self._progress_bar.setEnabled(True)

    def _record_cancel_click(self) -> None:
        self.cancel_clicks += 1

    def _reorder_action_buttons(self, _tab_index: int) -> None:
        action_buttons = [
            button
            for button in self._button_box.buttons()
            if self._button_box.buttonRole(button)
            == QDialogButtonBox.ButtonRole.ActionRole
        ]
        for button in action_buttons:
            self._button_box.removeButton(button)
            self._button_box.addButton(
                button,
                QDialogButtonBox.ButtonRole.ActionRole,
            )

    def close(self) -> bool:
        self.was_closed = True
        return super().close()


class DelayedMessageBarDialog(FakeAlgorithmDialog):
    def __init__(self, algorithm) -> None:
        super().__init__(algorithm)
        self.message_bar_available = False

    def messageBar(self):
        if not self.message_bar_available:
            return None

        return self._message_bar


class FakeProviderWarningProvider:
    def __init__(self, warning_message: str) -> None:
        self._warning_message = warning_message

    def warningMessage(self) -> str:
        return self._warning_message


class FakeProviderWarningAlgorithm:
    def __init__(self, warning_message: str) -> None:
        self._provider = FakeProviderWarningProvider(warning_message)
        self.tool = Mock(can_run=True)

    def provider(self):
        return self._provider


def _message_bar_text(item) -> str:
    for child in item.findChildren(QTextBrowser):
        return child.toPlainText()

    return ""


def test_message_bar_text_patch_only_updates_text_widgets(qgis_app) -> None:
    del qgis_app

    dialog_patcher_module = _import_dialog_patcher_module()
    algorithm = _create_algorithm(can_run=True, with_preset=False)
    dialog = FakeAlgorithmDialog(algorithm)
    patch = dialog_patcher_module.MessageBarTextColorPatch()

    dialog.messageBar().pushMessage(
        "",
        "Tool is unavailable",
        level=Qgis.MessageLevel.Warning,
    )
    warning_item = dialog.messageBar().items()[0]
    action_button = QPushButton("Open settings", warning_item)
    progress_bar = QProgressBar(warning_item)
    warning_item.layout().addWidget(action_button)
    warning_item.layout().addWidget(progress_bar)

    patch.apply(dialog, algorithm)

    text_browser = warning_item.findChild(QTextBrowser)

    assert text_browser is not None
    assert "color: black" in text_browser.styleSheet()
    assert "QTextEdit, QTextBrowser" in text_browser.styleSheet()
    assert progress_bar.styleSheet() == ""
    assert warning_item.styleSheet() == ""
    assert action_button.styleSheet() == ""


def test_algorithm_dialog_patcher_hides_demo_button_without_presets(
    qgis_app,
) -> None:
    del qgis_app

    demo_button_module = _import_demo_button_module()
    algorithm = _create_algorithm(can_run=True, with_preset=False)
    dialog = FakeAlgorithmDialog(algorithm)
    patcher = AlgorithmDialogPatcher()

    patcher.patch(dialog)

    demo_buttons = dialog.findChildren(
        QPushButton,
        demo_button_module.DemoButton.OBJECT_NAME,
    )

    assert demo_buttons == []


def test_algorithm_dialog_patcher_adds_demo_button_and_help_icon(
    qgis_app,
) -> None:
    del qgis_app

    demo_button_module = _import_demo_button_module()
    notifier_module = importlib.import_module(
        "nextgis_toolbox.notifier.message_bar_notifier"
    )
    algorithm = _create_algorithm(can_run=True, with_preset=True)
    dialog = FakeAlgorithmDialog(algorithm)
    patcher = AlgorithmDialogPatcher()

    patcher.patch(dialog)
    patcher.patch(dialog)

    help_button = dialog.buttonBox().button(
        QDialogButtonBox.StandardButton.Help
    )
    demo_buttons = dialog.findChildren(
        QPushButton,
        demo_button_module.DemoButton.OBJECT_NAME,
    )

    assert help_button is not None
    assert not help_button.icon().isNull()
    assert len(demo_buttons) == 1
    assert isinstance(dialog.notifier, notifier_module.MessageBarNotifier)
    assert algorithm.notifier is dialog.notifier

    layout = dialog.buttonBox().layout()
    assert layout is not None
    assert layout.indexOf(help_button) < layout.indexOf(demo_buttons[0])
    assert (
        dialog.buttonBox().buttonRole(demo_buttons[0])
        == QDialogButtonBox.ButtonRole.ActionRole
    )


def test_dialog_runtime_resolves_notifier_lazily(qgis_app) -> None:
    del qgis_app

    algorithm = _create_algorithm(can_run=True, with_preset=False)
    dialog = DelayedMessageBarDialog(algorithm)
    patcher = AlgorithmDialogPatcher()

    patcher.patch(dialog)

    assert algorithm.notifier is None
    assert getattr(dialog, "notifier", None) is None

    dialog.message_bar_available = True

    notifier = algorithm.notifier

    assert notifier is not None
    assert dialog.notifier is notifier


def test_algorithm_clone_keeps_runtime_notifier_resolver(qgis_app) -> None:
    del qgis_app

    algorithm = _create_algorithm(can_run=True, with_preset=False)
    dialog = FakeAlgorithmDialog(algorithm)
    patcher = AlgorithmDialogPatcher()

    patcher.patch(dialog)

    clone = algorithm.createInstance()

    assert clone.notifier is dialog.notifier


def test_algorithm_dialog_patcher_applies_demo_preset(qgis_app) -> None:
    del qgis_app

    demo_button_module = _import_demo_button_module()
    notifier_module = importlib.import_module(
        "nextgis_toolbox.notifier.message_bar_notifier"
    )
    algorithm = _create_algorithm(
        can_run=True,
        with_preset=True,
        inputs=[_parameter("source", "string")],
        preset_inputs={"source": "/tmp/demo-input.tif"},
    )
    dialog = FakeAlgorithmDialog(algorithm)
    patcher = AlgorithmDialogPatcher()

    patcher.patch(dialog)
    QApplication.processEvents()

    demo_button = dialog.findChildren(
        demo_button_module.DemoButton,
        demo_button_module.DemoButton.OBJECT_NAME,
    )[0]
    demo_button.click()
    demo_button.click()
    QApplication.processEvents()
    QApplication.processEvents()

    notifier_items = [
        item
        for item in dialog.messageBar().items()
        if item.objectName() == notifier_module.MESSAGE_BAR_ITEM_OBJECT_NAME
    ]

    assert (
        dialog.mainWidget().wrappers["source"].value == "/tmp/demo-input.tif"
    )
    assert len(notifier_items) == 1
    assert notifier_items[0].level() == Qgis.MessageLevel.Success
    assert (
        _message_bar_text(notifier_items[0])
        == "Demo values set and tool is ready for process. Click Run."
    )


def test_demo_button_switches_to_parameters_tab(qgis_app) -> None:
    del qgis_app

    demo_button_module = _import_demo_button_module()
    algorithm = _create_algorithm(
        can_run=True,
        with_preset=True,
        inputs=[_parameter("source", "string")],
        outputs=[_output_parameter("result", "file")],
        preset_inputs={"source": "demo"},
        preset_outputs={"result": {"name": "demo.zip"}},
    )
    dialog = FakeAlgorithmDialog(algorithm)
    dialog._tab_widget.setCurrentIndex(1)
    patcher = AlgorithmDialogPatcher()

    patcher.patch(dialog)
    QApplication.processEvents()

    demo_button = dialog.findChildren(
        demo_button_module.DemoButton,
        demo_button_module.DemoButton.OBJECT_NAME,
    )[0]
    demo_button.click()

    assert dialog._tab_widget.currentIndex() == 0


def test_demo_button_clicks_are_not_swallowed_while_loading(
    qgis_app,
) -> None:
    del qgis_app

    demo_button_module = _import_demo_button_module()
    demo_button = demo_button_module.DemoButton()
    demo_button.resize(120, 32)
    demo_button.show()

    applied_markers = []
    demo_button.apply_preset.connect(lambda: applied_markers.append("x"))

    demo_button.start()
    QTest.mouseClick(demo_button, Qt.MouseButton.LeftButton)
    QApplication.processEvents()

    assert applied_markers == []


def test_demo_button_starts_loading_without_valid_animation(
    qgis_app,
) -> None:
    del qgis_app

    demo_button_module = _import_demo_button_module()
    demo_button = demo_button_module.DemoButton()

    class InvalidMovie:
        def fileName(self) -> str:
            return "missing.gif"

        def isValid(self) -> bool:
            return False

        def state(self) -> QMovie.MovieState:
            return QMovie.MovieState.NotRunning

        def stop(self) -> None:
            return

    demo_button._movie = InvalidMovie()

    demo_button.start()

    assert demo_button.is_loading() is True
    assert demo_button.isEnabled() is False

    demo_button.stop()

    assert demo_button.is_loading() is False
    assert demo_button.isEnabled() is True


def test_message_bar_patches_ignore_generic_widgets(qgis_app) -> None:
    del qgis_app

    dialog_patcher_module = _import_dialog_patcher_module()
    algorithm = _create_algorithm(can_run=True, with_preset=False)
    dialog = FakeAlgorithmDialog(algorithm)

    generic_widget = QWidget()
    generic_text = QTextBrowser(generic_widget)

    text_patch = dialog_patcher_module.MessageBarTextColorPatch()
    provider_patch = dialog_patcher_module.ToolAvailabilityPatch()

    text_patch._patch_item(generic_widget)
    provider_patch._patch_provider_warning_item(
        dialog,
        algorithm,
        generic_widget,
    )

    assert generic_text.styleSheet() == ""


def test_dialog_runtime_expands_existing_message_bar_items(qgis_app) -> None:
    del qgis_app

    dialog_runtime_module = importlib.import_module(
        "nextgis_toolbox.processing.ui.dialog_patches.dialog_runtime"
    )
    notifier_module = importlib.import_module(
        "nextgis_toolbox.notifier.message_bar_notifier"
    )
    algorithm = _create_algorithm(can_run=True, with_preset=False)
    dialog = FakeAlgorithmDialog(algorithm)
    dialog.messageBar().pushMessage(
        "",
        "Existing warning message",
        level=Qgis.MessageLevel.Warning,
    )
    patcher = AlgorithmDialogPatcher(
        patches=(
            dialog_runtime_module.DialogRuntimePatch(
                runtime_controller=dialog_runtime_module.DialogRuntimeController(
                    notifier_factory=lambda message_bar: (
                        notifier_module.MessageBarNotifier(
                            message_bar,
                            expanding=True,
                        )
                    )
                )
            ),
        )
    )

    patcher.patch(dialog)
    QApplication.processEvents()

    warning_item = dialog.messageBar().items()[0]
    text_browser = warning_item.findChild(QTextBrowser)

    assert text_browser is not None
    assert (
        dialog.messageBar().sizePolicy().verticalPolicy()
        == QSizePolicy.Policy.Preferred
    )
    assert text_browser.minimumHeight() > 0
    assert text_browser.minimumHeight() == text_browser.maximumHeight()


def test_dialog_runtime_expands_notifier_created_message_items(
    qgis_app,
) -> None:
    del qgis_app

    dialog_patcher_module = _import_dialog_patcher_module()
    dialog_runtime_module = importlib.import_module(
        "nextgis_toolbox.processing.ui.dialog_patches.dialog_runtime"
    )
    notifier_module = importlib.import_module(
        "nextgis_toolbox.notifier.message_bar_notifier"
    )
    algorithm = _create_algorithm(can_run=True, with_preset=False)
    dialog = FakeAlgorithmDialog(algorithm)
    patcher = AlgorithmDialogPatcher(
        patches=(
            dialog_runtime_module.DialogRuntimePatch(
                runtime_controller=dialog_runtime_module.DialogRuntimeController(
                    notifier_factory=lambda message_bar: (
                        notifier_module.MessageBarNotifier(
                            message_bar,
                            expanding=True,
                        )
                    )
                )
            ),
            dialog_patcher_module.MessageBarTextColorPatch(),
        ),
    )

    patcher.patch(dialog)

    action_button = QPushButton("Action")
    dialog.notifier.display_message(
        "A message with a custom action button.",
        widgets=[action_button],
    )
    QApplication.processEvents()

    message_item = dialog.messageBar().items()[-1]
    text_browser = message_item.findChild(QTextBrowser)

    assert text_browser is not None
    assert action_button in message_item.findChildren(QPushButton)
    assert (
        dialog.messageBar().sizePolicy().verticalPolicy()
        == QSizePolicy.Policy.Preferred
    )
    assert "color: black" in text_browser.styleSheet()
    assert text_browser.minimumHeight() > 0
    assert text_browser.minimumHeight() == text_browser.maximumHeight()


def test_dialog_runtime_notifier_expands_messages_by_default(
    qgis_app,
) -> None:
    del qgis_app

    notifier_module = importlib.import_module(
        "nextgis_toolbox.notifier.message_bar_notifier"
    )
    algorithm = _create_algorithm(can_run=True, with_preset=False)
    dialog = FakeAlgorithmDialog(algorithm)
    patcher = AlgorithmDialogPatcher()

    patcher.patch(dialog)

    assert dialog.messageBar().property(
        notifier_module.MESSAGE_BAR_AUTO_EXPAND_PATCHED_PROPERTY
    )


def test_demo_button_clears_existing_progress_indicators(qgis_app) -> None:
    del qgis_app

    demo_button_module = _import_demo_button_module()
    algorithm = _create_algorithm(
        can_run=True,
        with_preset=True,
        inputs=[_parameter("source", "string")],
        outputs=[_output_parameter("result", "file")],
        preset_inputs={"source": "demo"},
        preset_outputs={"result": {"name": "demo.zip"}},
    )
    dialog = FakeAlgorithmDialog(algorithm)
    patcher = AlgorithmDialogPatcher()
    dialog._progress_bar.setValue(67)
    dialog._progress_bar.setEnabled(False)

    progress_widget = dialog.messageBar().createMessage("", "Running")
    message_progress_bar = QProgressBar(progress_widget)
    progress_widget.layout().addWidget(message_progress_bar)
    dialog.messageBar().pushWidget(progress_widget, Qgis.MessageLevel.Info, 0)

    patcher.patch(dialog)
    QApplication.processEvents()

    demo_button = dialog.findChildren(
        QPushButton,
        demo_button_module.DemoButton.OBJECT_NAME,
    )[0]
    demo_button.click()
    QApplication.processEvents()
    QApplication.processEvents()

    assert dialog.clear_progress_calls == 1
    assert dialog._progress_bar.isEnabled() is True
    assert dialog._progress_bar.value() == -1
    assert all(
        item.findChild(QProgressBar) is None
        for item in dialog.messageBar().items()
    )


def test_cancel_confirmation_patch_blocks_cancel_when_rejected(
    monkeypatch,
    qgis_app,
) -> None:
    del qgis_app

    dialog_patcher_module = _import_dialog_patcher_module()
    interaction_module = importlib.import_module(
        "nextgis_toolbox.processing.ui.dialog_patches.cancel_button"
    )
    algorithm = _create_algorithm(can_run=True, with_preset=False)
    dialog = FakeAlgorithmDialog(algorithm)
    dialog.feedback = object()
    dialog.show()
    patcher = AlgorithmDialogPatcher(
        patches=(dialog_patcher_module.CancelConfirmationPatch(),)
    )

    monkeypatch.setattr(
        interaction_module.QMessageBox,
        "warning",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Cancel,
    )

    patcher.patch(dialog)
    QTest.mouseClick(dialog.cancelButton(), Qt.MouseButton.LeftButton)
    QApplication.processEvents()

    assert dialog.cancel_clicks == 0


def test_cancel_confirmation_patch_allows_cancel_when_confirmed(
    monkeypatch,
    qgis_app,
) -> None:
    del qgis_app

    dialog_patcher_module = _import_dialog_patcher_module()
    interaction_module = importlib.import_module(
        "nextgis_toolbox.processing.ui.dialog_patches.cancel_button"
    )
    algorithm = _create_algorithm(can_run=True, with_preset=False)
    dialog = FakeAlgorithmDialog(algorithm)
    dialog.feedback = object()
    dialog.show()
    patcher = AlgorithmDialogPatcher(
        patches=(dialog_patcher_module.CancelConfirmationPatch(),)
    )

    monkeypatch.setattr(
        interaction_module.QMessageBox,
        "warning",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )

    patcher.patch(dialog)
    QTest.mouseClick(dialog.cancelButton(), Qt.MouseButton.LeftButton)
    QApplication.processEvents()

    assert dialog.cancel_clicks == 1


def test_advanced_button_patch_hides_toolbox_sdk_action(qgis_app) -> None:
    del qgis_app

    dialog_patcher_module = _import_dialog_patcher_module()
    algorithm = _create_algorithm(can_run=True, with_preset=False)
    dialog = FakeAlgorithmDialog(algorithm)
    menu = QMenu(dialog._advanced_button)
    menu.addAction("Copy as Python command")
    dialog._advanced_button.setMenu(menu)
    patch = dialog_patcher_module.AdvancedButtonPatch()

    patch.apply(dialog, algorithm)

    action_texts = [
        action.text() for action in menu.actions() if action.text()
    ]

    assert "Open Tool in Browser" in action_texts
    assert "Copy as Toolbox SDK code" not in action_texts


def test_tool_preset_applier_downloads_and_converts_values(
    api_server,
    qgis_app,
    tmp_path: Path,
) -> None:
    del qgis_app

    dialog_patcher_module = _import_dialog_patcher_module()
    applier_module = importlib.import_module(
        "nextgis_toolbox.processing.ui.tool_preset_applier"
    )
    demo_button_module = _import_demo_button_module()

    file_payload = b"preset-file-content"
    api_server.add_response(
        "HEAD",
        "/files/demo.txt",
        b"",
        headers={
            "Content-Disposition": 'attachment; filename="demo.txt"',
            "Content-Type": "text/plain",
        },
    )
    api_server.add_response(
        "GET",
        "/files/demo.txt",
        file_payload,
        headers={
            "Content-Disposition": 'attachment; filename="demo.txt"',
            "Content-Type": "text/plain",
        },
    )

    client = ToolboxApiClient(endpoint=api_server.base_url)
    algorithm = _create_algorithm(
        can_run=True,
        with_preset=True,
        client=client,
        inputs=[
            _parameter("source", "file"),
            _parameter(
                "mode",
                "single_choice",
                choices=[
                    {"alias": "First", "value": "a"},
                    {"alias": "Second", "value": "b"},
                ],
            ),
            _parameter(
                "modes",
                "multiple_choice",
                choices=[
                    {"alias": "First", "value": "a"},
                    {"alias": "Second", "value": "b"},
                ],
            ),
            _parameter("connection", "ngw_connection"),
        ],
        preset_inputs={
            "source": api_server.url("/files/demo.txt"),
            "mode": "b",
            "modes": ["a", "b"],
            "connection": {
                "url": "https://demo.nextgis.com",
                "login": "demo-user",
                "password": "demo-pass",  # pragma: allowlist secret
            },
        },
    )
    dialog = FakeAlgorithmDialog(algorithm)
    patcher = AlgorithmDialogPatcher(
        patches=(
            dialog_patcher_module.DemoButtonPatch(
                applier_module.ToolPresetApplier(
                    download_root=tmp_path / "preset-downloads"
                )
            ),
        )
    )

    patcher.patch(dialog)
    QApplication.processEvents()

    demo_button = dialog.findChildren(
        QPushButton,
        demo_button_module.DemoButton.OBJECT_NAME,
    )[0]
    demo_button.click()

    saved_path = Path(dialog.mainWidget().wrappers["source"].value)

    assert saved_path.exists()
    assert saved_path.read_bytes() == file_payload
    assert dialog.mainWidget().wrappers["mode"].value == 1
    assert dialog.mainWidget().wrappers["modes"].value == [0, 1]
    assert (
        dialog.mainWidget().wrappers["connection_url"].value
        == "https://demo.nextgis.com"
    )
    assert (
        dialog.mainWidget().wrappers["connection_login"].value == "demo-user"
    )
    assert (
        dialog.mainWidget().wrappers["connection_password"].value
        == "demo-pass"
    )


def test_tool_preset_applier_ignores_preset_outputs(qgis_app) -> None:
    del qgis_app

    applier_module = importlib.import_module(
        "nextgis_toolbox.processing.ui.tool_preset_applier"
    )
    algorithm = _create_algorithm(
        can_run=True,
        with_preset=True,
        inputs=[_parameter("source", "string")],
        preset_inputs={"source": "demo"},
        preset_outputs={
            "result": {
                "name": "demo.zip",
                "local": {"uuid": "uuid-1"},
            }
        },
    )
    dialog = FakeAlgorithmDialog(algorithm)

    applied = applier_module.ToolPresetApplier().apply(
        dialog,
        algorithm,
        algorithm.tool.presets[0],
    )

    assert applied is True
    assert dialog.mainWidget().wrappers["source"].value == "demo"
    assert "result" not in dialog.mainWidget().extra_parameters


def test_tool_preset_applier_enables_add_to_project_control(qgis_app) -> None:
    del qgis_app

    applier_module = importlib.import_module(
        "nextgis_toolbox.processing.ui.tool_preset_applier"
    )
    algorithm = _create_algorithm(
        can_run=True,
        with_preset=True,
        inputs=[_parameter("source", "string")],
        outputs=[_output_parameter("result", "file")],
        preset_inputs={"source": "demo"},
        preset_outputs={"result": {"name": "demo.zip"}},
    )
    dialog = FakeAlgorithmDialog(algorithm)

    applied = applier_module.ToolPresetApplier().apply(
        dialog,
        algorithm,
        algorithm.tool.presets[0],
    )

    assert applied is True
    assert (
        dialog.mainWidget()
        .wrappers[ADD_RESULTS_TO_PROJECT_PARAMETER_NAME]
        .value
        is True
    )


def test_demo_button_blocks_inputs_while_preset_is_loading(qgis_app) -> None:
    del qgis_app

    dialog_patcher_module = _import_dialog_patcher_module()
    demo_button_module = _import_demo_button_module()
    algorithm = _create_algorithm(
        can_run=True,
        with_preset=True,
        inputs=[_parameter("source", "string")],
        preset_inputs={"source": "demo"},
    )
    dialog = FakeAlgorithmDialog(algorithm)
    observed = {}

    class InspectingPresetApplier:
        button = None

        def apply(self, dialog, algorithm, preset) -> bool:
            del algorithm, preset
            observed["tab_widget_enabled"] = dialog._tab_widget.isEnabled()
            observed["progress_bar_enabled"] = dialog._progress_bar.isEnabled()
            observed["run_button_enabled"] = dialog.runButton().isEnabled()
            observed["help_button_enabled"] = (
                dialog.buttonBox()
                .button(QDialogButtonBox.StandardButton.Help)
                .isEnabled()
            )
            observed["close_button_enabled"] = (
                dialog.buttonBox()
                .button(QDialogButtonBox.StandardButton.Close)
                .isEnabled()
            )
            observed["advanced_button_enabled"] = (
                dialog._advanced_button.isEnabled()
            )
            observed["cancel_button_enabled"] = (
                dialog.cancelButton().isEnabled()
            )
            observed["button_loading"] = self.button.is_loading()
            return True

    preset_applier = InspectingPresetApplier()
    patcher = AlgorithmDialogPatcher(
        patches=(dialog_patcher_module.DemoButtonPatch(preset_applier),)
    )

    patcher.patch(dialog)
    QApplication.processEvents()

    demo_button = dialog.findChildren(
        QPushButton,
        demo_button_module.DemoButton.OBJECT_NAME,
    )[0]
    preset_applier.button = demo_button
    demo_button.click()

    assert observed == {
        "tab_widget_enabled": False,
        "progress_bar_enabled": False,
        "run_button_enabled": False,
        "help_button_enabled": True,
        "close_button_enabled": True,
        "advanced_button_enabled": False,
        "cancel_button_enabled": False,
        "button_loading": True,
    }
    assert dialog._tab_widget.isEnabled() is True
    assert dialog._progress_bar.isEnabled() is True
    assert dialog.runButton().isEnabled() is True
    assert (
        dialog.buttonBox()
        .button(QDialogButtonBox.StandardButton.Help)
        .isEnabled()
        is True
    )
    assert (
        dialog.buttonBox()
        .button(QDialogButtonBox.StandardButton.Close)
        .isEnabled()
        is True
    )
    assert dialog._advanced_button.isEnabled() is True
    assert dialog.cancelButton().isEnabled() is True
    assert demo_button.is_loading() is False


def test_tool_preset_applier_logs_error_on_failure(
    monkeypatch,
    qgis_app,
) -> None:
    del qgis_app

    applier_module = importlib.import_module(
        "nextgis_toolbox.processing.ui.tool_preset_applier"
    )
    algorithm = _create_algorithm(can_run=True, with_preset=True)
    dialog = FakeAlgorithmDialog(algorithm)
    logger = Mock()

    def raise_runtime_error(parameters) -> None:
        del parameters
        raise RuntimeError("broken")

    dialog.mainWidget().setParameters = raise_runtime_error
    monkeypatch.setattr(applier_module, "logger", logger)

    applied = applier_module.ToolPresetApplier().apply(
        dialog,
        algorithm,
        algorithm.tool.presets[0],
    )

    assert applied is False
    logger.exception.assert_called_once()


def test_algorithm_dialog_patcher_blocks_unrunnable_tool_inputs(
    qgis_app,
) -> None:
    del qgis_app

    algorithm = _create_algorithm(can_run=False, with_preset=False)
    dialog = FakeAlgorithmDialog(algorithm)
    patcher = AlgorithmDialogPatcher()

    patcher.patch(dialog)

    assert callable(getattr(dialog, "set_toolbox_ui_blocked", None))
    assert dialog._tab_widget.isEnabled() is False
    assert dialog._progress_bar.isEnabled() is False
    assert dialog.runButton().isEnabled() is False
    assert dialog._advanced_button.isEnabled() is False
    assert dialog.cancelButton().isEnabled() is False
    assert (
        dialog.buttonBox()
        .button(QDialogButtonBox.StandardButton.Help)
        .isEnabled()
        is True
    )
    assert (
        dialog.buttonBox()
        .button(QDialogButtonBox.StandardButton.Close)
        .isEnabled()
        is True
    )


def test_algorithm_dialog_patcher_unblocks_tool_after_repatch(
    qgis_app,
) -> None:
    del qgis_app

    algorithm = _create_algorithm(can_run=False, with_preset=False)
    dialog = FakeAlgorithmDialog(algorithm)
    patcher = AlgorithmDialogPatcher()

    patcher.patch(dialog)

    algorithm.tool.can_run = True
    patcher.patch(dialog)

    assert dialog._tab_widget.isEnabled() is True
    assert dialog._progress_bar.isEnabled() is True
    assert dialog.runButton().isEnabled() is True
    assert dialog._advanced_button.isEnabled() is True
    assert dialog.cancelButton().isEnabled() is True


def test_algorithm_dialog_block_method_restores_widget_state(qgis_app) -> None:
    del qgis_app

    algorithm = _create_algorithm(can_run=True, with_preset=False)
    dialog = FakeAlgorithmDialog(algorithm)
    patcher = AlgorithmDialogPatcher()

    patcher.patch(dialog)

    dialog.set_toolbox_ui_blocked(True)

    assert dialog._tab_widget.isEnabled() is False
    assert dialog._progress_bar.isEnabled() is False
    assert dialog.runButton().isEnabled() is False
    assert dialog._advanced_button.isEnabled() is False
    assert dialog.cancelButton().isEnabled() is False
    assert (
        dialog.buttonBox()
        .button(QDialogButtonBox.StandardButton.Help)
        .isEnabled()
        is True
    )
    assert (
        dialog.buttonBox()
        .button(QDialogButtonBox.StandardButton.Close)
        .isEnabled()
        is True
    )

    dialog.set_toolbox_ui_blocked(False)

    assert dialog._tab_widget.isEnabled() is True
    assert dialog._progress_bar.isEnabled() is True
    assert dialog.runButton().isEnabled() is True
    assert dialog._advanced_button.isEnabled() is True
    assert dialog.cancelButton().isEnabled() is True


def test_algorithm_dialog_runtime_hooks_block_controls_while_running(
    qgis_app,
) -> None:
    del qgis_app

    demo_button_module = _import_demo_button_module()
    algorithm = _create_algorithm(can_run=True, with_preset=True)
    dialog = FakeAlgorithmDialog(algorithm)
    patcher = AlgorithmDialogPatcher()

    patcher.patch(dialog)
    QApplication.processEvents()

    demo_button = dialog.findChildren(
        demo_button_module.DemoButton,
        demo_button_module.DemoButton.OBJECT_NAME,
    )[0]

    dialog.cancelButton().setEnabled(True)
    dialog.blockControlsWhileRunning()

    assert dialog.block_controls_calls == 1
    assert dialog._tab_widget.isEnabled() is False
    assert dialog._progress_bar.isEnabled() is False
    assert dialog.runButton().isEnabled() is False
    assert dialog._advanced_button.isEnabled() is False
    assert dialog.cancelButton().isEnabled() is True
    assert demo_button.isEnabled() is False

    dialog.resetAdditionalGui()

    assert dialog.reset_additional_gui_calls == 1
    assert dialog._tab_widget.isEnabled() is True
    assert dialog._progress_bar.isEnabled() is True
    assert dialog.runButton().isEnabled() is True
    assert dialog._advanced_button.isEnabled() is True
    assert dialog.cancelButton().isEnabled() is True
    assert demo_button.isEnabled() is True


def test_dialog_runtime_ignores_deleted_widgets_on_restore(
    qgis_app,
) -> None:
    del qgis_app

    demo_button_module = _import_demo_button_module()
    algorithm = _create_algorithm(can_run=True, with_preset=True)
    dialog = FakeAlgorithmDialog(algorithm)
    patcher = AlgorithmDialogPatcher()

    patcher.patch(dialog)
    QApplication.processEvents()

    demo_button = dialog.findChildren(
        demo_button_module.DemoButton,
        demo_button_module.DemoButton.OBJECT_NAME,
    )[0]

    dialog.set_toolbox_ui_blocked(True)
    dialog.buttonBox().removeButton(demo_button)
    sip.delete(demo_button)

    dialog.set_toolbox_ui_blocked(False)

    assert dialog._tab_widget.isEnabled() is True
    assert dialog._progress_bar.isEnabled() is True
    assert dialog.runButton().isEnabled() is True
    assert dialog._advanced_button.isEnabled() is True
    assert dialog.cancelButton().isEnabled() is True


def test_demo_button_repatch_restores_enabled_state(qgis_app) -> None:
    del qgis_app

    demo_button_module = _import_demo_button_module()
    algorithm = _create_algorithm(can_run=True, with_preset=True)
    dialog = FakeAlgorithmDialog(algorithm)
    patcher = AlgorithmDialogPatcher()

    patcher.patch(dialog)
    QApplication.processEvents()

    demo_button = dialog.findChildren(
        QPushButton,
        demo_button_module.DemoButton.OBJECT_NAME,
    )[0]
    demo_button.setEnabled(False)

    patcher.patch(dialog)

    assert demo_button.isEnabled() is True


def test_demo_button_repatch_preserves_external_handlers(qgis_app) -> None:
    del qgis_app

    demo_button_module = _import_demo_button_module()
    algorithm = _create_algorithm(can_run=True, with_preset=True)
    dialog = FakeAlgorithmDialog(algorithm)
    patcher = AlgorithmDialogPatcher()
    external_calls = []

    patcher.patch(dialog)
    QApplication.processEvents()

    demo_button = dialog.findChildren(
        demo_button_module.DemoButton,
        demo_button_module.DemoButton.OBJECT_NAME,
    )[0]
    getattr(demo_button, "apply_preset").connect(
        lambda: external_calls.append("called")
    )

    patcher.patch(dialog)
    demo_button.click()
    QApplication.processEvents()
    QApplication.processEvents()

    assert external_calls == ["called"]


def test_demo_button_keeps_position_after_tab_switch(qgis_app) -> None:
    del qgis_app

    demo_button_module = _import_demo_button_module()
    algorithm = _create_algorithm(can_run=True, with_preset=True)
    dialog = FakeAlgorithmDialog(
        algorithm,
        reorder_action_buttons_on_tab_change=True,
    )
    patcher = AlgorithmDialogPatcher()

    patcher.patch(dialog)
    QApplication.processEvents()

    demo_button = dialog.findChildren(
        demo_button_module.DemoButton,
        demo_button_module.DemoButton.OBJECT_NAME,
    )[0]
    help_button = dialog.buttonBox().button(
        QDialogButtonBox.StandardButton.Help
    )
    layout = dialog.buttonBox().layout()

    dialog._tab_widget.setCurrentIndex(1)
    QApplication.processEvents()

    assert help_button is not None
    assert layout.indexOf(help_button) < layout.indexOf(demo_button)


def test_demo_button_keeps_position_after_execution_reset(qgis_app) -> None:
    del qgis_app

    demo_button_module = _import_demo_button_module()
    algorithm = _create_algorithm(can_run=True, with_preset=True)
    dialog = FakeAlgorithmDialog(
        algorithm,
        reorder_action_buttons_on_reset=True,
    )
    patcher = AlgorithmDialogPatcher()

    patcher.patch(dialog)
    QApplication.processEvents()

    demo_button = dialog.findChildren(
        demo_button_module.DemoButton,
        demo_button_module.DemoButton.OBJECT_NAME,
    )[0]
    help_button = dialog.buttonBox().button(
        QDialogButtonBox.StandardButton.Help
    )
    layout = dialog.buttonBox().layout()

    dialog.blockControlsWhileRunning()
    dialog.resetAdditionalGui()
    QApplication.processEvents()

    assert help_button is not None
    assert layout.indexOf(help_button) < layout.indexOf(demo_button)


def test_demo_button_handler_is_owned_by_dialog(qgis_app) -> None:
    del qgis_app

    demo_patch_module = importlib.import_module(
        "nextgis_toolbox.processing.ui.dialog_patches.demo_button"
    )
    demo_button_module = _import_demo_button_module()
    algorithm = _create_algorithm(can_run=True, with_preset=True)
    dialog = FakeAlgorithmDialog(algorithm)
    patcher = AlgorithmDialogPatcher()

    patcher.patch(dialog)
    QApplication.processEvents()

    demo_button = dialog.findChildren(
        demo_button_module.DemoButton,
        demo_button_module.DemoButton.OBJECT_NAME,
    )[0]
    handler = getattr(
        dialog,
        demo_patch_module.DEMO_BUTTON_HANDLER_ATTRIBUTE,
    )

    assert isinstance(handler, QObject)
    assert isinstance(handler, demo_patch_module.DemoButtonHandler)
    assert handler.parent() is dialog

    demo_button.click()
    QApplication.processEvents()


def test_provider_warning_patch_hides_close_control_for_provider_warning(
    qgis_app,
) -> None:
    del qgis_app

    dialog_patcher_module = _import_dialog_patcher_module()
    algorithm = _create_algorithm(can_run=True, with_preset=False)
    dialog = FakeAlgorithmDialog(algorithm)
    close_control = QWidget(dialog.messageBar())
    close_control.show()
    close_menu = QMenu(close_control)
    close_menu.setObjectName("mCloseMenu")
    close_button = QToolButton(close_control)
    close_button.show()
    dialog.messageBar().pushMessage(
        "",
        "Tool is unavailable",
        level=Qgis.MessageLevel.Warning,
    )
    patch = dialog_patcher_module.ToolAvailabilityPatch()
    algorithm = FakeProviderWarningAlgorithm("Tool is unavailable")

    patch.apply(dialog, algorithm)

    assert close_control.isHidden() is True


def test_provider_warning_patch_adds_open_settings_button(
    monkeypatch,
    qgis_app,
) -> None:
    del qgis_app

    dialog_patcher_module = _import_dialog_patcher_module()
    tool_availability_module = _import_tool_availability_patches_module()
    algorithm = _create_algorithm(can_run=True, with_preset=False)
    dialog = FakeAlgorithmDialog(algorithm)
    warning_message = "Tool execution requires authentication"
    dialog.messageBar().pushMessage(
        "",
        warning_message,
        level=Qgis.MessageLevel.Warning,
    )
    patch = dialog_patcher_module.ToolAvailabilityPatch()
    plugin_mock = Mock()

    monkeypatch.setattr(
        tool_availability_module.NextgisToolboxInterface,
        "instance",
        classmethod(lambda cls: plugin_mock),
    )
    monkeypatch.setattr(
        tool_availability_module.QTimer,
        "singleShot",
        lambda _timeout, callback: callback(),
    )

    patch.apply(dialog, FakeProviderWarningAlgorithm(warning_message))

    warning_item = dialog.messageBar().items()[0]

    button = warning_item.findChild(
        QPushButton,
        tool_availability_module.TOOLBOX_PROVIDER_WARNING_OPEN_SETTINGS_BUTTON_OBJECT_NAME,
    )

    assert button is not None
    assert not button.icon().isNull()

    button.click()

    assert dialog.was_closed is True
    plugin_mock.open_settings.assert_called_once_with()


def test_help_anchor_click_patch_replaces_existing_handler_and_previews_images(
    monkeypatch,
    qgis_app,
    tmp_path: Path,
) -> None:
    del qgis_app

    dialog_patcher_module = _import_dialog_patcher_module()
    help_patches_module = _import_help_patches_module()
    algorithm = _create_algorithm(can_run=True, with_preset=False)
    dialog = FakeAlgorithmDialog(algorithm)
    previous_handler = Mock()
    preview_dialog = Mock()
    open_url = Mock()

    dialog._help_browser.anchorClicked.connect(previous_handler)
    monkeypatch.setattr(
        dialog_patcher_module.HelpAnchorClickPatch,
        "_show_help_image_preview_dialog",
        preview_dialog,
    )
    monkeypatch.setattr(
        help_patches_module.QDesktopServices,
        "openUrl",
        open_url,
    )

    patch = dialog_patcher_module.HelpAnchorClickPatch()
    patch.apply(dialog, algorithm)

    image_path = tmp_path / "help.png"
    image_path.write_bytes(b"png")
    help_patches_module.HelpBrowserState().set_cached_image_paths(
        dialog._help_browser,
        {"https://example.com/help.png": str(image_path)},
    )

    dialog._help_browser.anchorClicked.emit(QUrl("https://nextgis.com"))
    dialog._help_browser.anchorClicked.emit(
        QUrl("https://example.com/help.png")
    )

    assert previous_handler.call_count == 0
    assert open_url.call_count == 1
    assert open_url.call_args[0][0].toString() == "https://nextgis.com"
    preview_dialog.assert_called_once_with(str(image_path))


def test_help_browser_state_ignores_deleted_browser(
    qgis_app,
    tmp_path: Path,
) -> None:
    del qgis_app

    help_patches_module = _import_help_patches_module()
    help_browser = QTextBrowser()
    image_path = tmp_path / "help.png"
    browser_state = help_patches_module.HelpBrowserState()

    image_path.write_bytes(b"png")
    browser_state.set_cached_image_paths(
        help_browser,
        {"https://example.com/help.png": str(image_path)},
    )
    sip.delete(help_browser)

    assert (
        browser_state.cached_image_path(
            help_browser,
            QUrl("https://example.com/help.png"),
        )
        is None
    )


def test_wrap_help_image_links_uses_original_image_url(qgis_app) -> None:
    del qgis_app

    help_patches_module = _import_help_patches_module()
    help_image = help_patches_module.ToolHelpImage(
        placeholder="__image__",
        source_url="https://example.com/help.png",
    )
    rendered_source = "data:image/png;base64,Zm9v"

    wrapped_html = (
        help_patches_module.HelpImageTaskSupport().wrap_help_image_links(
            f'<p><img src="{rendered_source}" style="display:block;"></p>',
            (help_image,),
            {help_image.placeholder: rendered_source},
        )
    )

    assert '<a href="https://example.com/help.png"><img' in wrapped_html


def test_run_message_dismiss_patch_clears_demo_notification_on_accept(
    qgis_app,
) -> None:
    del qgis_app

    dialog_patcher_module = _import_dialog_patcher_module()
    notifier_module = importlib.import_module(
        "nextgis_toolbox.notifier.message_bar_notifier"
    )
    algorithm = _create_algorithm(can_run=True, with_preset=False)
    dialog = FakeAlgorithmDialog(algorithm)
    patcher = AlgorithmDialogPatcher(
        patches=(dialog_patcher_module.DialogRuntimePatch(),)
    )

    patcher.patch(dialog)
    dialog.notifier.display_message(
        "Demo values set and tool is ready for process. Click Run.",
        level=Qgis.MessageLevel.Success,
    )

    dialog.buttonBox().accepted.emit()

    notifier_items = [
        item
        for item in dialog.messageBar().items()
        if item.objectName() == notifier_module.MESSAGE_BAR_ITEM_OBJECT_NAME
    ]

    assert notifier_items == []


def test_help_images_task_uses_cached_file_paths(
    qgis_app,
    tmp_path: Path,
) -> None:
    del qgis_app

    help_patches_module = _import_help_patches_module()
    api_client = Mock()
    api_client.get_bytes.return_value = b"png"
    task = help_patches_module._LoadHelpImagesTask(
        api_client,
        [
            help_patches_module.ToolHelpImage(
                placeholder="__image_0__",
                source_url="https://example.com/help.png",
            ),
            help_patches_module.ToolHelpImage(
                placeholder="__image_1__",
                source_url="https://example.com/help.png",
            ),
        ],
        tmp_path,
        Mock(),
    )

    assert task.run() is True
    first_image_path = Path(task.image_paths["__image_0__"])
    second_image_path = Path(task.image_paths["__image_1__"])

    assert first_image_path == second_image_path
    assert first_image_path.parent == tmp_path
    assert first_image_path.read_bytes() == b"png"
    api_client.get_bytes.assert_called_once_with(
        "https://example.com/help.png",
        cache_key="help-images/https://example.com/help.png",
    )
