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

from typing import Optional, cast

from qgis.core import Qgis, QgsApplication
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QObject, QTimer, pyqtSlot
from qgis.PyQt.QtWidgets import (
    QApplication,
    QDialogButtonBox,
    QHBoxLayout,
)

from nextgis_toolbox.core.logging import logger
from nextgis_toolbox.processing.toolbox_algorithm import (
    ToolboxAlgorithm,
)
from nextgis_toolbox.processing.ui.compat import AlgorithmDialog
from nextgis_toolbox.processing.ui.demo_button import DemoButton
from nextgis_toolbox.processing.ui.tool_preset_applier import ToolPresetApplier
from nextgis_toolbox.tools.models import ToolPreset

from .common import AlgorithmDialogPatch
from .dialog_runtime import DialogRuntimeController

DEMO_APPLIED_MESSAGE = QgsApplication.translate(
    "NGToolboxProcessing",
    "Demo values set and tool is ready for process. Click Run.",
)
DEMO_BUTTON_HANDLER_ATTRIBUTE = "_nextgis_toolbox_demo_button_handler"


class DemoButtonHandler(QObject):
    """Handle demo button clicks with an explicit QObject lifetime."""

    def __init__(
        self,
        patch: "DemoButtonPatch",
        button: DemoButton,
        dialog: AlgorithmDialog,
        algorithm: ToolboxAlgorithm,
        preset: ToolPreset,
    ) -> None:
        super().__init__(dialog)
        self._patch = patch
        self._button = button
        self._dialog = dialog
        self._algorithm = algorithm
        self._preset = preset

    @pyqtSlot()
    def apply_preset(self) -> None:
        """Apply the stored demo preset."""
        self._patch._apply_preset(
            self._button,
            self._dialog,
            self._algorithm,
            self._preset,
        )

    def _sync_button_placement(self) -> None:
        self._patch._place_demo_button(self._dialog, self._button)

    @pyqtSlot(int)
    def sync_button_placement_for_tab_change(self, _tab_index: int) -> None:
        """Keep the demo button next to help after tab relayouts."""
        self._sync_button_placement()

    @pyqtSlot()
    def sync_button_placement_after_execution(self) -> None:
        """Keep the demo button next to help after execution reset."""
        self._sync_button_placement()


class DemoButtonPatch(AlgorithmDialogPatch):
    """Manage the lifecycle and behavior of the demo preset button."""

    def __init__(
        self,
        preset_applier: Optional[ToolPresetApplier] = None,
        runtime_controller: Optional[DialogRuntimeController] = None,
    ) -> None:
        self._preset_applier = preset_applier or ToolPresetApplier()
        self._runtime_controller = (
            runtime_controller or DialogRuntimeController()
        )

    def apply(
        self,
        dialog: AlgorithmDialog,
        algorithm: ToolboxAlgorithm,
    ) -> None:
        """Synchronize the demo button with the current tool preset."""
        self._runtime_controller.dismiss_notifier_messages(dialog)

        preset = algorithm.tool.demo_preset()
        button_box = dialog.buttonBox()
        if button_box is None:
            return

        existing_button = self._runtime_controller.demo_button(dialog)
        if preset is None:
            self._remove_demo_button(button_box, dialog, existing_button)
            return

        demo_button = existing_button or DemoButton(button_box)
        self._configure_demo_button(
            demo_button,
            dialog,
            algorithm,
            preset,
        )

        if existing_button is not None:
            logger.debug(
                "Demo button already exists, syncing its state with the algorithm"
            )
            self._sync_button_state(demo_button, algorithm)
            return

        self._initialize_button_state(demo_button, algorithm)

    def _remove_demo_button(
        self,
        button_box: QDialogButtonBox,
        dialog: AlgorithmDialog,
        demo_button: Optional[DemoButton],
    ) -> None:
        if demo_button is None:
            return

        button_box.removeButton(demo_button)
        demo_button.deleteLater()
        if hasattr(dialog, DEMO_BUTTON_HANDLER_ATTRIBUTE):
            delattr(dialog, DEMO_BUTTON_HANDLER_ATTRIBUTE)

    def _configure_demo_button(
        self,
        button: DemoButton,
        dialog: AlgorithmDialog,
        algorithm: ToolboxAlgorithm,
        preset: ToolPreset,
    ) -> None:
        button.setToolTip(preset.alias)
        button.setStatusTip(preset.alias)
        self._connect_demo_button(button, dialog, algorithm, preset)
        self._place_demo_button(dialog, button)

    def _place_demo_button(
        self,
        dialog: AlgorithmDialog,
        demo_button: DemoButton,
    ) -> None:
        button_box = dialog.buttonBox()
        if button_box is None:
            return

        if demo_button not in button_box.buttons():
            button_box.addButton(
                demo_button,
                QDialogButtonBox.ButtonRole.ActionRole,
            )

        layout = cast(QHBoxLayout, button_box.layout())
        layout.removeWidget(demo_button)

        help_button = self._runtime_controller.help_button(dialog)
        if help_button is None:
            return

        help_button_index = layout.indexOf(help_button)
        layout.insertWidget(help_button_index + 1, demo_button)

    def _connect_demo_button(
        self,
        button: DemoButton,
        dialog: AlgorithmDialog,
        algorithm: ToolboxAlgorithm,
        preset: ToolPreset,
    ) -> None:
        tab_widget = self._runtime_controller.tab_widget(dialog)
        runtime_state = self._runtime_controller.runtime_state(dialog)
        existing_handler = getattr(dialog, DEMO_BUTTON_HANDLER_ATTRIBUTE, None)
        if isinstance(existing_handler, DemoButtonHandler):
            try:
                button.apply_preset.disconnect(existing_handler.apply_preset)
            except (RuntimeError, TypeError):
                pass

            try:
                tab_widget.currentChanged.disconnect(
                    existing_handler.sync_button_placement_for_tab_change
                )
            except (RuntimeError, TypeError):
                pass

            try:
                runtime_state.execution_ui_restored.disconnect(
                    existing_handler.sync_button_placement_after_execution
                )
            except (RuntimeError, TypeError):
                pass

        handler = self._create_demo_button_handler(
            button,
            dialog,
            algorithm,
            preset,
        )
        try:
            button.apply_preset.connect(handler.apply_preset)
        except RuntimeError:
            return

        try:
            tab_widget.currentChanged.connect(
                handler.sync_button_placement_for_tab_change
            )
        except RuntimeError:
            return

        try:
            runtime_state.execution_ui_restored.connect(
                handler.sync_button_placement_after_execution
            )
        except RuntimeError:
            return

        setattr(dialog, DEMO_BUTTON_HANDLER_ATTRIBUTE, handler)

    def _create_demo_button_handler(
        self,
        button: DemoButton,
        dialog: AlgorithmDialog,
        algorithm: ToolboxAlgorithm,
        preset: ToolPreset,
    ) -> DemoButtonHandler:
        return DemoButtonHandler(
            self,
            button,
            dialog,
            algorithm,
            preset,
        )

    def _apply_preset(
        self,
        button: DemoButton,
        dialog: AlgorithmDialog,
        algorithm: ToolboxAlgorithm,
        preset: ToolPreset,
    ) -> None:
        if button.is_loading():
            return

        notifier = self._runtime_controller.notifier(dialog)
        self._runtime_controller.dismiss_notifier_messages(dialog)
        self._runtime_controller.show_parameters_tab(dialog)
        self._runtime_controller.clear_progress(dialog)

        button.start()
        QApplication.processEvents()
        self._runtime_controller.set_ui_blocked(dialog, True)
        preset_was_applied = False
        try:
            preset_was_applied = self._preset_applier.apply(
                dialog,
                algorithm,
                preset,
            )
        finally:
            self._runtime_controller.set_ui_blocked(dialog, False)
            button.stop()

        if not preset_was_applied or notifier is None:
            return

        notifier.display_message(
            DEMO_APPLIED_MESSAGE,
            level=Qgis.MessageLevel.Success,
            clear_previous=True,
        )

    def _initialize_button_state(
        self,
        button: DemoButton,
        algorithm: ToolboxAlgorithm,
    ) -> None:
        button.setEnabled(False)
        QTimer.singleShot(
            0,
            lambda current_button=button, current_algorithm=algorithm: (
                self._restore_button_state(
                    current_button,
                    current_algorithm,
                )
            ),
        )

    def _restore_button_state(
        self,
        button: DemoButton,
        algorithm: ToolboxAlgorithm,
    ) -> None:
        if sip.isdeleted(button):
            return

        button.setEnabled(algorithm.tool.can_run)

    def _sync_button_state(
        self,
        button: DemoButton,
        algorithm: ToolboxAlgorithm,
    ) -> None:
        if sip.isdeleted(button):
            return

        if button.is_loading():
            return

        button.setEnabled(algorithm.tool.can_run)
