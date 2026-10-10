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

from types import MethodType
from typing import Callable, List, Optional, Tuple, cast
from weakref import ref

from qgis.gui import QgsMessageBar
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QAbstractButton,
    QDialogButtonBox,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QWidget,
)

from nextgis_toolbox.notifier.message_bar_notifier import MessageBarNotifier
from nextgis_toolbox.processing.toolbox_algorithm import (
    ToolboxAlgorithm,
)
from nextgis_toolbox.processing.ui.compat import AlgorithmDialog
from nextgis_toolbox.processing.ui.demo_button import DemoButton

from .common import AlgorithmDialogPatch

TOOLBOX_DIALOG_RUNTIME_ATTRIBUTE = "_nextgis_toolbox_dialog_runtime"
TOOLBOX_UI_BLOCK_METHOD = "set_toolbox_ui_blocked"
TOOLBOX_EXECUTION_UI_BLOCK_METHOD = "set_toolbox_execution_ui_blocked"
TOOLBOX_ORIGINAL_BLOCK_CONTROLS_ATTRIBUTE = (
    "_nextgis_toolbox_original_block_controls_while_running"
)
TOOLBOX_ORIGINAL_RESET_ADDITIONAL_GUI_ATTRIBUTE = (
    "_nextgis_toolbox_original_reset_additional_gui"
)
TOOLBOX_RUN_MESSAGE_DISMISS_PATCHED_PROPERTY = (
    "_nextgis_toolbox_run_message_dismiss_patched"
)
NotifierFactory = Callable[[QgsMessageBar], MessageBarNotifier]


def create_dialog_notifier(message_bar: QgsMessageBar) -> MessageBarNotifier:
    return MessageBarNotifier(message_bar, expanding=True)


class DialogWidgetAccessor:
    def progress_bar(
        self,
        dialog: AlgorithmDialog,
    ) -> Optional[QProgressBar]:
        return self._progress_bar(dialog)

    def tab_widget(
        self,
        dialog: AlgorithmDialog,
    ) -> QTabWidget:
        return self._tab_widget(dialog)

    def cancel_button(
        self,
        dialog: AlgorithmDialog,
    ) -> Optional[QWidget]:
        return self._cancel_button(dialog)

    def help_button(
        self,
        dialog: AlgorithmDialog,
    ) -> Optional[QAbstractButton]:
        """Return the help button for the algorithm dialog."""
        button_box = dialog.buttonBox()
        if button_box is None:
            return None

        return button_box.button(QDialogButtonBox.StandardButton.Help)

    def help_browser(
        self,
        dialog: AlgorithmDialog,
    ) -> Optional[QTextBrowser]:
        """Return the short help browser widget for the dialog."""
        help_browser = dialog.findChild(QTextBrowser, "textShortHelp")
        if help_browser is not None:
            return help_browser

        return dialog.findChild(QTextBrowser)

    def demo_button(
        self,
        dialog: AlgorithmDialog,
    ) -> Optional[DemoButton]:
        """Return the demo button if it is already attached."""
        return self._demo_button(dialog)

    def advanced_button(
        self,
        dialog: AlgorithmDialog,
    ) -> Optional[QPushButton]:
        """Return the advanced button from the dialog button box."""
        button_box = dialog.buttonBox()
        if button_box is None:
            return None

        for button in button_box.buttons():
            if not self._is_advanced_button(button_box, button):
                continue

            if isinstance(button, QPushButton):
                return button

        return None

    def widgets_to_block(
        self,
        dialog: AlgorithmDialog,
    ) -> List[QWidget]:
        return self._widgets_to_block(dialog, keep_cancel_enabled=False)

    def widgets_to_block_while_running(
        self,
        dialog: AlgorithmDialog,
    ) -> List[QWidget]:
        widgets_to_block: List[QWidget] = []
        self._append_unique_widget(
            widgets_to_block,
            self._demo_button(dialog),
        )
        return widgets_to_block

    def _widgets_to_block(
        self,
        dialog: AlgorithmDialog,
        *,
        keep_cancel_enabled: bool,
    ) -> List[QWidget]:
        widgets_to_block: List[QWidget] = []

        self._append_unique_widget(widgets_to_block, self._tab_widget(dialog))

        self._append_unique_widget(
            widgets_to_block,
            self._progress_bar(dialog),
        )

        button_box = dialog.buttonBox()
        if button_box is not None:
            for button in button_box.buttons():
                if self._button_stays_enabled(
                    button_box,
                    button,
                    keep_cancel_enabled=keep_cancel_enabled,
                ):
                    continue

                self._append_unique_widget(widgets_to_block, button)

        if not keep_cancel_enabled:
            self._append_unique_widget(
                widgets_to_block,
                self._cancel_button(dialog),
            )

        return widgets_to_block

    def _tab_widget(
        self,
        dialog: AlgorithmDialog,
    ) -> QTabWidget:
        tab_widget = dialog.findChild(QTabWidget, "mTabWidget")
        if tab_widget is not None:
            return tab_widget

        return cast(QTabWidget, dialog.findChild(QTabWidget))

    def _progress_bar(
        self,
        dialog: AlgorithmDialog,
    ) -> Optional[QProgressBar]:
        progress_bar = dialog.findChild(QProgressBar, "progressBar")
        if progress_bar is not None:
            return progress_bar

        return dialog.findChild(QProgressBar)

    def _cancel_button(
        self,
        dialog: AlgorithmDialog,
    ) -> Optional[QWidget]:
        cancel_button_method = getattr(dialog, "cancelButton", None)
        if callable(cancel_button_method):
            cancel_button = cancel_button_method()
            if isinstance(cancel_button, QWidget):
                return cancel_button

        return dialog.findChild(QPushButton, "buttonCancel")

    def _demo_button(
        self,
        dialog: AlgorithmDialog,
    ) -> Optional[DemoButton]:
        button_box = dialog.buttonBox()
        if button_box is None:
            return None

        return button_box.findChild(
            DemoButton,
            DemoButton.OBJECT_NAME,
        )

    def _button_stays_enabled(
        self,
        button_box: QDialogButtonBox,
        button: QAbstractButton,
        *,
        keep_cancel_enabled: bool,
    ) -> bool:
        kept_buttons = {
            QDialogButtonBox.StandardButton.Close,
            QDialogButtonBox.StandardButton.Help,
        }
        if keep_cancel_enabled:
            kept_buttons.add(QDialogButtonBox.StandardButton.Cancel)

        return button_box.standardButton(button) in kept_buttons

    def _is_advanced_button(
        self,
        button_box: QDialogButtonBox,
        button: QAbstractButton,
    ) -> bool:
        if not isinstance(button, QPushButton):
            return False

        if (
            button_box.buttonRole(button)
            != QDialogButtonBox.ButtonRole.ResetRole
        ):
            return False

        menu = button.menu()
        if menu is None:
            return False

        return any(
            "python" in action.text().lower() for action in menu.actions()
        )

    def _append_unique_widget(
        self,
        widgets: List[QWidget],
        widget: Optional[QWidget],
    ) -> None:
        if widget is None:
            return

        if any(existing_widget is widget for existing_widget in widgets):
            return

        widgets.append(widget)


class DialogRuntimeState(QObject):
    execution_ui_restored = pyqtSignal()

    def __init__(
        self,
        dialog: AlgorithmDialog,
        widget_accessor: DialogWidgetAccessor,
        notifier_factory: NotifierFactory,
    ) -> None:
        super().__init__(dialog)
        self._dialog_ref = ref(dialog)
        self._widget_accessor = widget_accessor
        self._notifier_factory = notifier_factory
        self._notifier: Optional[MessageBarNotifier] = None
        self._block_state: List[Tuple[QWidget, bool]] = []
        self._execution_block_state: List[Tuple[QWidget, bool]] = []

    @property
    def notifier(self) -> Optional[MessageBarNotifier]:
        if self._notifier is not None:
            return self._notifier

        dialog = self._dialog_ref()
        if dialog is None:
            return None

        message_bar = dialog.messageBar()
        if message_bar is None:
            return None

        self._notifier = self._notifier_factory(message_bar)
        setattr(dialog, "notifier", self._notifier)
        return self._notifier

    def apply(self, dialog: AlgorithmDialog) -> None:
        notifier = self.notifier
        if notifier is not None:
            setattr(dialog, "notifier", notifier)

        if not callable(getattr(dialog, TOOLBOX_UI_BLOCK_METHOD, None)):
            setattr(
                dialog,
                TOOLBOX_UI_BLOCK_METHOD,
                MethodType(self._set_toolbox_ui_blocked, dialog),
            )
            setattr(
                dialog,
                TOOLBOX_EXECUTION_UI_BLOCK_METHOD,
                MethodType(self._set_toolbox_execution_ui_blocked, dialog),
            )

        self._install_execution_hooks(dialog)
        self._install_run_message_dismiss_hook(dialog)

    def _set_toolbox_ui_blocked(
        self,
        dialog: AlgorithmDialog,
        is_blocked: bool,
    ) -> None:
        self._set_widgets_blocked(
            dialog,
            is_blocked,
            self._widget_accessor.widgets_to_block,
            self._block_state,
        )

    def _set_toolbox_execution_ui_blocked(
        self,
        dialog: AlgorithmDialog,
        is_blocked: bool,
    ) -> None:
        self._set_widgets_blocked(
            dialog,
            is_blocked,
            self._widget_accessor.widgets_to_block_while_running,
            self._execution_block_state,
        )

    def _set_widgets_blocked(
        self,
        dialog: AlgorithmDialog,
        is_blocked: bool,
        widget_resolver: Callable[[AlgorithmDialog], List[QWidget]],
        block_state: List[Tuple[QWidget, bool]],
    ) -> None:
        if is_blocked:
            self._store_block_state(dialog, widget_resolver, block_state)
            return

        self._restore_block_state(block_state)

    def _store_block_state(
        self,
        dialog: AlgorithmDialog,
        widget_resolver: Callable[[AlgorithmDialog], List[QWidget]],
        block_state: List[Tuple[QWidget, bool]],
    ) -> None:
        stored_widgets = self._live_block_state(block_state)
        for widget in widget_resolver(dialog):
            if sip.isdeleted(widget):
                continue

            widget_id = id(widget)
            try:
                if widget_id not in stored_widgets:
                    stored_widgets[widget_id] = (
                        widget,
                        widget.isEnabled(),
                    )
                widget.setEnabled(False)
            except RuntimeError:
                continue

        block_state[:] = list(stored_widgets.values())

    def _restore_block_state(
        self,
        block_state: List[Tuple[QWidget, bool]],
    ) -> None:
        for widget, was_enabled in block_state:
            if sip.isdeleted(widget):
                continue

            try:
                widget.setEnabled(was_enabled)
            except RuntimeError:
                continue

        block_state[:] = []

    def _live_block_state(
        self,
        block_state: List[Tuple[QWidget, bool]],
    ) -> dict:
        return {
            id(widget): (widget, was_enabled)
            for widget, was_enabled in block_state
            if not sip.isdeleted(widget)
        }

    def _install_execution_hooks(
        self,
        dialog: AlgorithmDialog,
    ) -> None:
        if not callable(
            getattr(dialog, TOOLBOX_EXECUTION_UI_BLOCK_METHOD, None)
        ):
            return

        self._install_dialog_hook(
            dialog,
            TOOLBOX_ORIGINAL_BLOCK_CONTROLS_ATTRIBUTE,
            "blockControlsWhileRunning",
            self._block_controls_while_running,
        )
        self._install_dialog_hook(
            dialog,
            TOOLBOX_ORIGINAL_RESET_ADDITIONAL_GUI_ATTRIBUTE,
            "resetAdditionalGui",
            self._reset_additional_gui,
        )

    def _install_run_message_dismiss_hook(
        self,
        dialog: AlgorithmDialog,
    ) -> None:
        button_box = dialog.buttonBox()
        if button_box is None:
            return

        if button_box.property(TOOLBOX_RUN_MESSAGE_DISMISS_PATCHED_PROPERTY):
            return

        button_box.accepted.connect(self._dismiss_runtime_messages)
        button_box.setProperty(
            TOOLBOX_RUN_MESSAGE_DISMISS_PATCHED_PROPERTY,
            True,
        )

    def _install_dialog_hook(
        self,
        dialog: AlgorithmDialog,
        original_attribute: str,
        method_name: str,
        replacement: Callable[[AlgorithmDialog], None],
    ) -> None:
        original_method = getattr(dialog, original_attribute, None)
        if original_method is not None:
            return

        current_method = getattr(dialog, method_name, None)
        if not callable(current_method):
            return

        setattr(dialog, original_attribute, current_method)
        setattr(dialog, method_name, MethodType(replacement, dialog))

    def _block_controls_while_running(
        self,
        dialog: AlgorithmDialog,
    ) -> None:
        set_execution_ui_blocked = getattr(
            dialog,
            TOOLBOX_EXECUTION_UI_BLOCK_METHOD,
            None,
        )
        if callable(set_execution_ui_blocked):
            set_execution_ui_blocked(True)

        original_block_controls = getattr(
            dialog,
            TOOLBOX_ORIGINAL_BLOCK_CONTROLS_ATTRIBUTE,
            None,
        )
        if callable(original_block_controls):
            original_block_controls()

    def _reset_additional_gui(
        self,
        dialog: AlgorithmDialog,
    ) -> None:
        original_reset_additional_gui = getattr(
            dialog,
            TOOLBOX_ORIGINAL_RESET_ADDITIONAL_GUI_ATTRIBUTE,
            None,
        )
        if callable(original_reset_additional_gui):
            original_reset_additional_gui()

        set_execution_ui_blocked = getattr(
            dialog,
            TOOLBOX_EXECUTION_UI_BLOCK_METHOD,
            None,
        )
        if callable(set_execution_ui_blocked):
            set_execution_ui_blocked(False)

        QTimer.singleShot(0, self._emit_execution_ui_restored)

    def _emit_execution_ui_restored(self) -> None:
        self.execution_ui_restored.emit()

    def _dismiss_runtime_messages(self) -> None:
        notifier = self.notifier
        if notifier is None:
            return

        try:
            notifier.dismiss_all()
        except RuntimeError:
            return


class DialogRuntimeController:
    def __init__(
        self,
        widget_accessor: Optional[DialogWidgetAccessor] = None,
        notifier_factory: NotifierFactory = create_dialog_notifier,
    ) -> None:
        self._widget_accessor = widget_accessor or DialogWidgetAccessor()
        self._notifier_factory = notifier_factory

    def ensure(
        self,
        dialog: AlgorithmDialog,
    ) -> DialogRuntimeState:
        runtime = getattr(dialog, TOOLBOX_DIALOG_RUNTIME_ATTRIBUTE, None)
        if isinstance(runtime, DialogRuntimeState):
            return runtime

        runtime = DialogRuntimeState(
            dialog,
            widget_accessor=self._widget_accessor,
            notifier_factory=self._notifier_factory,
        )
        setattr(dialog, TOOLBOX_DIALOG_RUNTIME_ATTRIBUTE, runtime)
        runtime.apply(dialog)
        return runtime

    def runtime_state(
        self,
        dialog: AlgorithmDialog,
    ) -> DialogRuntimeState:
        """Return the runtime state for the dialog."""
        return self.ensure(dialog)

    def help_button(
        self,
        dialog: AlgorithmDialog,
    ) -> Optional[QAbstractButton]:
        """Return the help button for the dialog."""
        return self._widget_accessor.help_button(dialog)

    def help_browser(
        self,
        dialog: AlgorithmDialog,
    ) -> Optional[QTextBrowser]:
        """Return the short help browser for the dialog."""
        return self._widget_accessor.help_browser(dialog)

    def tab_widget(
        self,
        dialog: AlgorithmDialog,
    ) -> QTabWidget:
        """Return the tab widget for the dialog."""
        return self._widget_accessor.tab_widget(dialog)

    def demo_button(
        self,
        dialog: AlgorithmDialog,
    ) -> Optional[DemoButton]:
        """Return the demo button for the dialog."""
        return self._widget_accessor.demo_button(dialog)

    def advanced_button(
        self,
        dialog: AlgorithmDialog,
    ) -> Optional[QPushButton]:
        """Return the advanced button for the dialog."""
        return self._widget_accessor.advanced_button(dialog)

    def cancel_button(
        self,
        dialog: AlgorithmDialog,
    ) -> Optional[QWidget]:
        return self._widget_accessor.cancel_button(dialog)

    def show_parameters_tab(
        self,
        dialog: AlgorithmDialog,
    ) -> None:
        self._widget_accessor.tab_widget(dialog).setCurrentIndex(0)

    def notifier(
        self,
        dialog: Optional[AlgorithmDialog],
    ) -> Optional[MessageBarNotifier]:
        if dialog is None:
            return None

        return self.ensure(dialog).notifier

    def dismiss_notifier_messages(
        self,
        dialog: AlgorithmDialog,
    ) -> None:
        notifier = self.notifier(dialog)
        if notifier is None:
            return

        try:
            notifier.dismiss_all()
        except RuntimeError:
            return

    def set_ui_blocked(
        self,
        dialog: AlgorithmDialog,
        is_blocked: bool,
    ) -> None:
        self.ensure(dialog)
        set_ui_blocked = getattr(dialog, TOOLBOX_UI_BLOCK_METHOD, None)
        if callable(set_ui_blocked):
            set_ui_blocked(is_blocked)

    def clear_progress(self, dialog: AlgorithmDialog) -> None:
        """Clear stale execution progress before applying a new demo preset."""
        clear_progress = getattr(dialog, "clearProgress", None)
        if callable(clear_progress):
            clear_progress()
        message_bar = dialog.messageBar()
        if message_bar is None:
            return
        for item in message_bar.items():
            if item.findChild(QProgressBar) is not None:
                message_bar.popWidget(item)


class DialogRuntimePatch(AlgorithmDialogPatch):
    def __init__(
        self,
        runtime_controller: Optional[DialogRuntimeController] = None,
    ) -> None:
        self._runtime_controller = (
            runtime_controller or DialogRuntimeController()
        )

    def apply(
        self,
        dialog: AlgorithmDialog,
        algorithm: ToolboxAlgorithm,
    ) -> None:
        self._runtime_controller.ensure(dialog)
        dialog_ref = ref(dialog)
        algorithm.set_notifier_resolver(
            lambda current_dialog_ref=dialog_ref: (
                self._runtime_controller.notifier(current_dialog_ref())
            )
        )
