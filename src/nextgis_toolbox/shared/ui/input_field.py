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

import html
from dataclasses import dataclass
from enum import Enum
from typing import (
    Any,
    Generic,
    List,
    Optional,
    Sequence,
    Tuple,
    TypeVar,
)
from urllib.parse import urlparse

from qgis.gui import (
    QgsCheckableComboBox,
    QgsDoubleSpinBox,
    QgsHighlightableLineEdit,
    QgsSpinBox,
)
from qgis.PyQt.QtCore import QEvent, QObject, Qt, pyqtSignal, pyqtSlot
from qgis.PyQt.QtGui import (
    QColor,
    QPainter,
    QPaintEvent,
    QPalette,
    QPen,
    QResizeEvent,
    QValidator,
)
from qgis.PyQt.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from nextgis_toolbox.ui.icon import qgis_icon

try:
    from qgis.gui import QgsHighlightableComboBox
except ImportError:

    class QgsHighlightableComboBox(QComboBox):
        """Provide a Python fallback for the non-SIP-bound QGIS widget."""

        def __init__(self, parent: Optional[QWidget] = None) -> None:
            """Create a highlightable combo box.

            :param parent: Parent widget.
            """
            super().__init__(parent)
            self._highlighted = False

        def isHighlighted(self) -> bool:
            """Return whether the combo box is highlighted.

            :returns: ``True`` when the highlight border is enabled.
            """
            return self._highlighted

        def setHighlighted(self, highlighted: bool) -> None:
            """Set whether the combo box is highlighted.

            :param highlighted: Whether to draw the highlight border.
            """
            self._highlighted = highlighted
            self.update()

        def paintEvent(  # pyright: ignore[reportIncompatibleMethodOverride]
            self,
            event: QPaintEvent,
        ) -> None:
            """Paint the combo box and optional highlight border.

            :param event: Paint event.
            """
            super().paintEvent(event)
            if not self._highlighted:
                return

            painter = QPainter(self)
            border_width = 2
            painter.setPen(QPen(self.palette().highlight(), border_width))
            painter.drawRect(
                self.rect().adjusted(
                    border_width,
                    border_width,
                    -border_width,
                    -border_width,
                )
            )


ERROR_COLOR = "#e93d58"

T = TypeVar("T")


class EditorType(str, Enum):
    """Built-in editor adapters supported by :class:`FieldsForm`."""

    TEXT_EDIT = "text_edit"
    INTEGER_SPIN_BOX = "integer_spin_box"
    DOUBLE_SPIN_BOX = "double_spin_box"
    COMBO_BOX = "combo_box"
    CHECKABLE_COMBO_BOX = "checkable_combo_box"
    CUSTOM = "custom"


class UrlValidator(QValidator):
    """Validate HTTP and HTTPS URL values."""

    def validate(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        input_text: str,
        position: int,
    ) -> Tuple[QValidator.State, str, int]:
        """Validate URL text.

        :param input_text: Current editor text.
        :param position: Current cursor position.

        :returns: Validator state, unchanged text and cursor position.
        """
        if input_text == "":
            return QValidator.State.Intermediate, input_text, position

        parsed_url = urlparse(input_text)
        if parsed_url.scheme in ("http", "https") and parsed_url.netloc:
            return QValidator.State.Acceptable, input_text, position

        return QValidator.State.Intermediate, input_text, position


class HighlightableSpinBox(QgsSpinBox):
    """Provide a QGIS spin box with a highlighted border."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Create a highlightable spin box.

        :param parent: Parent widget.
        """
        super().__init__(parent)
        self._highlighted = False

    def isHighlighted(self) -> bool:
        """Return whether the spin box is highlighted.

        :returns: ``True`` when the highlight border is enabled.
        """
        return self._highlighted

    def setHighlighted(self, highlighted: bool) -> None:
        """Set whether the spin box is highlighted.

        :param highlighted: Whether to draw the highlight border.
        """
        self._highlighted = highlighted
        self.update()

    def paintEvent(self, event: Optional[QPaintEvent]) -> None:
        """Paint the spin box and optional highlight border.

        :param event: Paint event.
        """
        super().paintEvent(event)
        if not self._highlighted:
            return

        painter = QPainter(self)
        border_width = 2
        painter.setPen(QPen(self.palette().highlight(), border_width))
        painter.drawRect(
            self.rect().adjusted(
                border_width,
                border_width,
                -border_width,
                -border_width,
            )
        )


class HighlightableDoubleSpinBox(QgsDoubleSpinBox):
    """Provide a QGIS double spin box with a highlighted border."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Create a highlightable double spin box.

        :param parent: Parent widget.
        """
        super().__init__(parent)
        self._highlighted = False

    def isHighlighted(self) -> bool:
        """Return whether the spin box is highlighted.

        :returns: ``True`` when the highlight border is enabled.
        """
        return self._highlighted

    def setHighlighted(self, highlighted: bool) -> None:
        """Set whether the spin box is highlighted.

        :param highlighted: Whether to draw the highlight border.
        """
        self._highlighted = highlighted
        self.update()

    def paintEvent(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        event: QPaintEvent,
    ) -> None:
        """Paint the spin box and optional highlight border.

        :param event: Paint event.
        """
        super().paintEvent(event)
        if not self._highlighted:
            return

        painter = QPainter(self)
        border_width = 2
        painter.setPen(QPen(self.palette().highlight(), border_width))
        painter.drawRect(
            self.rect().adjusted(
                border_width,
                border_width,
                -border_width,
                -border_width,
            )
        )


class HighlightableCheckableComboBox(QgsCheckableComboBox):
    """Provide a checkable combo box with highlighting support."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Create a highlightable checkable combo box.

        :param parent: Parent widget.
        """
        super().__init__(parent)
        self._highlighted = False
        self._highlight_border = QFrame(self)
        self._highlight_border.setFrameShape(QFrame.Shape.Box)
        self._highlight_border.setStyleSheet(
            f"border: 2px solid {ERROR_COLOR};background: transparent;"
        )
        self._highlight_border.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True,
        )
        self._highlight_border.setGeometry(self.rect())
        self._highlight_border.hide()
        self.lineEdit().textChanged.connect(self._update_display_text_palette)
        self.model().dataChanged.connect(self._update_display_text_palette)
        self.model().rowsInserted.connect(self._update_display_text_palette)
        self.model().rowsRemoved.connect(self._update_display_text_palette)
        self._update_display_text_palette()

    def isHighlighted(self) -> bool:
        """Return whether the combo box is highlighted.

        :returns: ``True`` when the highlight border is enabled.
        """
        return self._highlighted

    def setHighlighted(self, highlighted: bool) -> None:
        """Set whether the combo box is highlighted.

        :param highlighted: Whether to draw the highlight border.
        """
        self._highlighted = highlighted
        self._highlight_border.setVisible(highlighted)
        self._highlight_border.raise_()
        self.update()

    def resizeEvent(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        event: QResizeEvent,
    ) -> None:
        """Keep the highlight border aligned with the combo box.

        :param event: Resize event.
        """
        super().resizeEvent(event)
        self._highlight_border.setGeometry(self.rect())
        self._highlight_border.raise_()

    def changeEvent(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        event: QEvent,
    ) -> None:
        """Update the displayed text after palette changes.

        :param event: Widget change event.
        """
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            self._update_display_text_palette()

    @pyqtSlot()
    def _update_display_text_palette(self) -> None:
        """Use placeholder colors while no items are checked."""
        line_edit = self.lineEdit()
        if line_edit is None:
            return

        palette = QPalette(line_edit.palette())
        source_palette = self.palette()
        source_role = QPalette.ColorRole.Text
        if not self.checkedItems():
            source_role = QPalette.ColorRole.PlaceholderText

        color_groups = (
            QPalette.ColorGroup.Active,
            QPalette.ColorGroup.Disabled,
            QPalette.ColorGroup.Inactive,
        )
        for color_group in color_groups:
            palette.setBrush(
                color_group,
                QPalette.ColorRole.Text,
                source_palette.brush(color_group, source_role),
            )

        line_edit.setPalette(palette)


class EditorAdapter(QObject, Generic[T]):
    """Normalize the API of one editor created with the adapter."""

    value_changed = pyqtSignal()
    _editor: QWidget

    def __init__(self) -> None:
        """Initialize the adapter."""
        super().__init__()
        self._is_changed = False
        self.value_changed.connect(self._mark_changed)

    @property
    def editor(self) -> QWidget:
        """Return the editor widget.

        :returns: Editor widget.
        """
        return self._editor

    @property
    def is_changed(self) -> bool:
        """Return whether the user has changed the editor value.

        :returns: ``True`` after the editor has emitted a value-change signal.
        """
        return self._is_changed

    def get_value(self) -> T:
        """Return the current editor value.

        :returns: Current working value.
        """
        raise NotImplementedError

    def set_value(self, value: Optional[T]) -> None:
        """Set the editor value.

        :param value: New working value.
        """
        raise NotImplementedError

    def reset(self, default_value: Optional[T]) -> None:
        """Reset the editor to the value supplied by the field.

        :param default_value: Field default value.
        """
        self.set_value(default_value)
        self._is_changed = False

    def is_empty(self, value: Optional[T]) -> bool:
        """Return whether a value is empty.

        :param value: Value to inspect.

        :returns: ``True`` for a falsy value.
        """
        return not bool(value)

    @pyqtSlot()
    def _mark_changed(self) -> None:
        """Record that the editor emitted a value-change signal."""
        self._is_changed = True


class TextEditAdapter(EditorAdapter[str]):
    """Adapt a QGIS text editor to the common editor contract."""

    def __init__(self) -> None:
        """Create the line edit and connect its user-edit signal."""
        super().__init__()
        self._editor = QgsHighlightableLineEdit()
        self._editor.textChanged.connect(
            lambda _text: self.value_changed.emit()
        )

    def get_value(self) -> str:
        """Return the current line edit text.

        :returns: Editor text.
        """
        return self._editor.text()

    def set_value(self, value: Optional[str]) -> None:
        """Set text without emitting a user change.

        :param value: New text. ``None`` clears the editor.
        """
        signals_were_blocked = self._editor.blockSignals(True)
        try:
            self._editor.setText("" if value is None else str(value))
        finally:
            self._editor.blockSignals(signals_were_blocked)


class IntegerSpinBoxAdapter(EditorAdapter[int]):
    """Adapt an integer QGIS spin box."""

    def __init__(
        self,
        minimum: int = -2147483648,
        maximum: int = 2147483647,
    ) -> None:
        """Create and configure an integer spin box.

        :param minimum: Minimum accepted value.
        :param maximum: Maximum accepted value.
        """
        super().__init__()
        self._editor = HighlightableSpinBox()
        self._editor.setButtonSymbols(
            QAbstractSpinBox.ButtonSymbols.UpDownArrows
        )
        self._editor.setRange(minimum, maximum)
        self._editor.valueChanged.connect(
            lambda _value: self.value_changed.emit()
        )

    def get_value(self) -> int:
        """Return the current integer.

        :returns: Current integer value.
        """
        return int(self._editor.value())

    def set_value(self, value: Optional[int]) -> None:
        """Set an integer without emitting a user change.

        :param value: New value. ``None`` is treated as zero.
        """
        signals_were_blocked = self._editor.blockSignals(True)
        try:
            self._editor.setValue(0 if value is None else int(value))
        finally:
            self._editor.blockSignals(signals_were_blocked)

    def is_empty(self, value: Optional[int]) -> bool:
        """Return ``False`` because a spin box always has a value.

        :param value: Value to inspect.

        :returns: Always ``False``.
        """
        return False


class DoubleSpinBoxAdapter(EditorAdapter[float]):
    """Adapt a floating-point QGIS spin box."""

    def __init__(
        self,
        minimum: float = -1.7976931348623157e308,
        maximum: float = 1.7976931348623157e308,
        decimals: int = 6,
    ) -> None:
        """Create and configure a floating-point spin box.

        :param minimum: Minimum accepted value.
        :param maximum: Maximum accepted value.
        :param decimals: Number of decimal places.
        """
        super().__init__()
        self._editor = HighlightableDoubleSpinBox()
        self._editor.setButtonSymbols(
            QAbstractSpinBox.ButtonSymbols.UpDownArrows
        )
        self._editor.setDecimals(decimals)
        self._editor.setRange(minimum, maximum)
        self._editor.valueChanged.connect(
            lambda _value: self.value_changed.emit()
        )

    def get_value(self) -> float:
        """Return the current floating-point value.

        :returns: Current value.
        """
        return float(self._editor.value())

    def set_value(self, value: Optional[float]) -> None:
        """Set a number without emitting a user change.

        :param value: New value. ``None`` is treated as zero.
        """
        signals_were_blocked = self._editor.blockSignals(True)
        try:
            self._editor.setValue(0.0 if value is None else float(value))
        finally:
            self._editor.blockSignals(signals_were_blocked)

    def is_empty(self, value: Optional[float]) -> bool:
        """Return ``False`` because a spin box always has a value.

        :param value: Value to inspect.

        :returns: Always ``False``.
        """
        return False


class ComboBoxAdapter(EditorAdapter[Any]):
    """Adapt a single-choice combo box using item data as values."""

    def __init__(
        self,
        items: Optional[Sequence[Tuple[str, Any]]] = None,
    ) -> None:
        """Create and populate a single-choice combo box.

        :param items: Sequence of ``(text, data)`` options.
        """
        super().__init__()
        self._editor = QgsHighlightableComboBox()
        for item_text, item_value in items or ():
            self._editor.addItem(item_text, item_value)
        self._editor.setCurrentIndex(-1)
        self._editor.activated.connect(
            lambda _index: self.value_changed.emit()
        )

    def get_value(self) -> Any:
        """Return selected item data or ``None``.

        :returns: Selected item data, or ``None`` without a selection.
        """
        if self._editor.currentIndex() < 0:
            return None
        return self._editor.currentData(Qt.ItemDataRole.UserRole)

    def set_value(self, value: Any) -> None:
        """Select item data without emitting a user change.

        :param value: Item data. ``None`` clears the selection.
        """
        signals_were_blocked = self._editor.blockSignals(True)
        try:
            item_index = -1
            if value is not None:
                item_index = self._editor.findData(
                    value,
                    Qt.ItemDataRole.UserRole,
                )
            self._editor.setCurrentIndex(item_index)
        finally:
            self._editor.blockSignals(signals_were_blocked)


class CheckableComboBoxAdapter(EditorAdapter[List[Any]]):
    """Adapt a QGIS multiple-choice combo box."""

    def __init__(
        self,
        items: Optional[Sequence[Tuple[str, Any]]] = None,
    ) -> None:
        """Create and populate a multiple-choice combo box.

        :param items: Sequence of ``(text, data)`` options.
        """
        super().__init__()
        self._editor = HighlightableCheckableComboBox()
        for item_text, item_value in items or ():
            self._editor.addItemWithCheckState(
                item_text,
                Qt.CheckState.Unchecked,
                item_value,
            )
        self._editor.setCurrentIndex(-1)
        self._editor.checkedItemsChanged.connect(
            lambda _items: self.value_changed.emit()
        )

    def get_value(self) -> List[Any]:
        """Return item data for all checked options.

        :returns: Checked values in editor order.
        """
        return [
            self._editor.itemData(item_index, Qt.ItemDataRole.UserRole)
            for item_index in range(self._editor.count())
            if self._editor.itemCheckState(item_index) == Qt.CheckState.Checked
        ]

    def set_value(self, value: Optional[List[Any]]) -> None:
        """Set checked values without emitting a user change.

        :param value: Values to check. ``None`` clears the selection.
        """
        selected_values = [] if value is None else list(value)
        signals_were_blocked = self._editor.blockSignals(True)
        try:
            for item_index in range(self._editor.count()):
                self._editor.setItemCheckState(
                    item_index,
                    Qt.CheckState.Unchecked,
                )
            self._editor.setCurrentIndex(-1)
            for selected_value in selected_values:
                item_index = self._editor.findData(
                    selected_value,
                    Qt.ItemDataRole.UserRole,
                )
                if item_index < 0:
                    continue
                self._editor.setItemCheckState(
                    item_index,
                    Qt.CheckState.Checked,
                )
                self._editor.setCurrentIndex(item_index)
        finally:
            self._editor.blockSignals(signals_were_blocked)
        self._editor._update_display_text_palette()

    def is_empty(self, value: Optional[List[Any]]) -> bool:
        """Return whether no values are selected.

        :param value: Values to inspect.

        :returns: ``True`` for an empty selection.
        """
        return not bool(value)


@dataclass
class InputField(Generic[T]):
    """Describe an input field and its last saved value.

    :param title: Text displayed next to or above the editor.
    :param editor_type: Type of editor used to edit the value.
    :param value: Last saved value.
    :param combo_box_items: Options available in a combo box editor.
    :param default_value: Value used by reset operations.
    :param placeholder: Optional editor placeholder.
    :param tooltip: Editor tooltip.
    :param is_required: Whether an empty active value is invalid.
    :param is_enabled: Whether users can edit the field.
    :param is_optional_allowed: Whether users can disable the field.
    :param is_used: Last saved optional-use state.
    :param required_message: Error for an empty required value.
    :param invalid_message: Error for a rejected validator value.
    """

    title: str
    editor_type: EditorType
    value: Optional[T] = None
    combo_box_items: Optional[Sequence[Tuple[str, Any]]] = None
    default_value: Optional[T] = None
    placeholder: str = ""
    tooltip: str = ""
    is_required: bool = False
    is_enabled: bool = True
    is_optional_allowed: bool = False
    is_used: bool = True
    required_message: str = "This field is required"
    invalid_message: str = "Invalid value"


@dataclass(frozen=True)
class FormState:
    """Describe observable runtime state of a form.

    :param dirty: Whether working values differ from saved values.
    :param valid: Last known validation state.
    """

    dirty: bool
    valid: Optional[bool]


class InputFieldWidget(QWidget):
    """Display one input field and its auxiliary controls.

    The widget prepares and lays out the title, editor, optional checkbox,
    reset button and validation message. Form-level behavior remains in
    :class:`FieldsForm`.

    :param input_field: Field declaration represented by the widget.
    :param adapter: Runtime adapter for the editor.
    :param validator: Optional Qt validator.
    :param orientation: Layout orientation of the field.
    :param parent: Parent form widget.
    """

    def __init__(
        self,
        input_field: InputField[Any],
        adapter: EditorAdapter[Any],
        validator: Optional[QValidator],
        orientation: Qt.Orientation,
        parent: QWidget,
    ) -> None:
        """Create one field presentation.

        :param input_field: Field declaration represented by the widget.
        :param adapter: Runtime adapter for the editor.
        :param validator: Optional Qt validator.
        :param orientation: Layout orientation of the field.
        :param parent: Parent form widget.
        """
        super().__init__(parent)
        self.definition = input_field
        self.adapter = adapter
        self.validator = validator
        self.editor = adapter.editor
        self.editor.setParent(self)
        self.title_label = QLabel(self)
        self.optional_checkbox = QCheckBox(self)
        self.reset_button = QToolButton(self)
        self.error_label = QLabel(self)
        self.validation_result: Optional[bool] = None
        self._palette_before_error: Optional[QPalette] = None
        self._control_height = 0

        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self._configure_editor()
        self._configure_title(orientation)
        self._configure_optional_checkbox()
        self._configure_reset_button()
        self._configure_error_label()
        self._build_layout(orientation)

    def _configure_editor(self) -> None:
        """Apply common and declarative editor properties."""
        self.editor.setToolTip(self.definition.tooltip)
        self.editor.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self._apply_placeholder()
        self._apply_validator()

    def _apply_placeholder(self) -> None:
        """Apply the declared placeholder to a compatible editor."""
        set_default_text = getattr(self.editor, "setDefaultText", None)
        if callable(set_default_text):
            set_default_text(self.definition.placeholder)
            return

        set_placeholder = getattr(
            self.editor,
            "setPlaceholderText",
            None,
        )
        if callable(set_placeholder):
            set_placeholder(self.definition.placeholder)

    def _apply_validator(self) -> None:
        """Apply the declared validator to a compatible editor."""
        set_validator = getattr(self.editor, "setValidator", None)
        if callable(set_validator):
            set_validator(self.validator)

    def _configure_title(self, orientation: Qt.Orientation) -> None:
        """Configure the title label."""
        title_text = html.escape(self.definition.title)
        if self.definition.is_required and title_text:
            title_text = (
                f'{title_text} <span style="color: {ERROR_COLOR};">*</span>'
            )
        self.title_label.setTextFormat(Qt.TextFormat.RichText)
        self.title_label.setText(title_text)

        title_alignment = Qt.Alignment(Qt.AlignmentFlag.AlignLeft)
        title_alignment |= Qt.Alignment(Qt.AlignmentFlag.AlignVCenter)

        self.title_label.setAlignment(title_alignment)
        self.title_label.setVisible(
            bool(self.definition.title)
            or orientation == Qt.Orientation.Horizontal
        )

    def _configure_optional_checkbox(self) -> None:
        """Configure the optional-use checkbox."""
        self.optional_checkbox.setText("")
        self.optional_checkbox.setVisible(self.definition.is_optional_allowed)
        self.optional_checkbox.setEnabled(self.definition.is_enabled)

    def _configure_reset_button(self) -> None:
        """Configure the reset button."""
        self.reset_button.setIcon(qgis_icon("mActionUndo.svg"))
        self.reset_button.setToolTip(self.tr("Reset to default value"))
        self.reset_button.setVisible(self.definition.default_value is not None)
        self._align_control_heights()

    def _align_control_heights(self) -> None:
        """Set equal heights for the editor and reset button."""
        self._control_height = max(
            self.editor.sizeHint().height(),
            self.editor.minimumSizeHint().height(),
            self.reset_button.sizeHint().height(),
            self.reset_button.minimumSizeHint().height(),
        )
        self.editor.setFixedHeight(self._control_height)
        self.reset_button.setFixedSize(
            self._control_height,
            self._control_height,
        )

    def _configure_error_label(self) -> None:
        """Configure the validation message label."""
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(f"color: {ERROR_COLOR};")
        self.error_label.hide()

    def _build_layout(self, orientation: Qt.Orientation) -> None:
        """Build a horizontal or vertical field layout."""
        editor_layout = self._create_editor_layout()
        field_layout = QVBoxLayout(self)
        field_layout.setContentsMargins(0, 0, 0, 0)
        field_layout.setSpacing(2)
        if orientation == Qt.Orientation.Vertical:
            self._build_vertical_layout(field_layout, editor_layout)
            return
        self._build_horizontal_layout(field_layout, editor_layout)

    def _create_editor_layout(self) -> QHBoxLayout:
        """Create the editor and reset-button layout."""
        editor_layout = QHBoxLayout()
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(3)
        editor_layout.addWidget(self.editor)
        editor_layout.addWidget(self.reset_button)
        return editor_layout

    def _build_vertical_layout(
        self,
        field_layout: QVBoxLayout,
        editor_layout: QHBoxLayout,
    ) -> None:
        """Populate a vertically oriented field layout."""
        if self.definition.title or self.definition.is_optional_allowed:
            title_layout = QHBoxLayout()
            title_layout.setContentsMargins(0, 0, 0, 0)
            title_layout.setSpacing(3)
            title_layout.addWidget(self.optional_checkbox)
            title_layout.addWidget(self.title_label, 1)
            field_layout.addLayout(title_layout)
        field_layout.addLayout(editor_layout)
        field_layout.addWidget(self.error_label)

    def _build_horizontal_layout(
        self,
        field_layout: QVBoxLayout,
        editor_layout: QHBoxLayout,
    ) -> None:
        """Populate a horizontally oriented field layout."""
        self.title_label.setFixedHeight(self._control_height)
        editor_layout.insertWidget(0, self.optional_checkbox)
        value_layout = QVBoxLayout()
        value_layout.setContentsMargins(0, 0, 0, 0)
        value_layout.setSpacing(2)
        value_layout.addLayout(editor_layout)
        value_layout.addWidget(self.error_label)

        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(6)
        content_layout.addWidget(
            self.title_label,
            0,
            Qt.AlignmentFlag.AlignTop,
        )
        content_layout.addLayout(value_layout, 1)
        field_layout.addLayout(content_layout)

        self._apply_error_label_margin(editor_layout)

    def _apply_error_label_margin(
        self,
        editor_layout: QHBoxLayout,
    ) -> None:
        """Align a validation message with the editor contents."""
        if not self.definition.is_optional_allowed:
            return
        message_margin = self.optional_checkbox.sizeHint().width()
        message_margin += editor_layout.spacing()
        self.error_label.setContentsMargins(message_margin, 0, 0, 0)

    def set_optional_checked(self, checked: bool) -> None:
        """Set the optional checkbox without emitting its signal."""
        signals_were_blocked = self.optional_checkbox.blockSignals(True)
        try:
            self.optional_checkbox.setChecked(checked)
        finally:
            self.optional_checkbox.blockSignals(signals_were_blocked)
        self.update_enabled()

    def is_used(self) -> bool:
        """Return the effective optional-use state."""
        if not self.definition.is_optional_allowed:
            return True
        return self.optional_checkbox.isChecked()

    def update_enabled(self) -> None:
        """Apply enabled and optional-use state to the controls."""
        controls_enabled = self.definition.is_enabled and self.is_used()
        self.editor.setEnabled(controls_enabled)
        self.reset_button.setEnabled(
            controls_enabled and self.definition.default_value is not None
        )

    def show_error(self, message: str) -> None:
        """Show or clear the validation error."""
        self._set_error_highlight(bool(message))
        if not message:
            self.error_label.clear()
            self.error_label.hide()
            return
        self.error_label.setText(message)
        self.error_label.show()

    def _set_error_highlight(self, highlighted: bool) -> None:
        """Set a red editor highlight without retaining palette changes."""
        if highlighted:
            self._apply_error_palette()
        elif self._palette_before_error is not None:
            self.editor.setPalette(self._palette_before_error)
            self._palette_before_error = None

        set_highlighted = getattr(self.editor, "setHighlighted", None)
        if callable(set_highlighted):
            set_highlighted(highlighted)

    def _apply_error_palette(self) -> None:
        """Set the palette role used by QGIS highlightable widgets."""
        if self._palette_before_error is None:
            self._palette_before_error = QPalette(self.editor.palette())
        error_palette = QPalette(self.editor.palette())
        error_color = QColor(ERROR_COLOR)
        for color_group in (
            QPalette.ColorGroup.Active,
            QPalette.ColorGroup.Disabled,
            QPalette.ColorGroup.Inactive,
        ):
            error_palette.setColor(
                color_group,
                QPalette.ColorRole.Highlight,
                error_color,
            )
        self.editor.setPalette(error_palette)

    def clear_validation(self) -> None:
        """Clear the stored and displayed validation result."""
        self.validation_result = None
        self.show_error("")


class FieldsForm(QWidget):
    """Render and manage a collection of declarative input fields."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        orientation: Qt.Orientation = Qt.Orientation.Horizontal,
    ) -> None:
        """Create an empty fields form.

        :param parent: Optional Qt parent.
        :param orientation: Common field layout orientation.
        """
        super().__init__(parent)
        self._orientation = orientation
        self._input_fields: List[InputFieldWidget] = []
        self._form_layout = QVBoxLayout(self)
        self._form_layout.setContentsMargins(0, 0, 0, 0)
        self._form_layout.setSpacing(9)
        self._state = self._calculate_state()

    def add_field(
        self,
        input_field: InputField[Any],
        *,
        adapter: Optional[EditorAdapter[Any]] = None,
        validator: Optional[QValidator] = None,
    ) -> QWidget:
        """Append an input field and return its editor.

        :param input_field: Declarative field description.
        :param adapter: Optional configured adapter; required for custom editors.
        :param validator: Optional Qt validator.

        :returns: Created editor widget.

        :raises ValueError: If editor configuration is invalid.
        """
        editor_adapter = self._create_adapter(input_field, adapter)

        input_field_widget = InputFieldWidget(
            input_field,
            editor_adapter,
            validator,
            self._orientation,
            self,
        )
        editor_adapter.set_value(input_field.value)
        input_field_widget.set_optional_checked(input_field.is_used)
        self._connect_input_field(input_field_widget)
        self._input_fields.append(input_field_widget)
        self._form_layout.addWidget(input_field_widget)
        self._align_titles()
        self._refresh_state()
        return input_field_widget.editor

    def _create_adapter(
        self,
        input_field: InputField[Any],
        adapter: Optional[EditorAdapter[Any]],
    ) -> EditorAdapter[Any]:
        """Create or validate the adapter for an input field.

        :param input_field: Field declaration that selects the editor type.
        :param adapter: Optional configured adapter; required for custom editors.

        :returns: Adapter that owns the editor widget.

        :raises ValueError: If editor configuration is invalid.
        """
        self._validate_combo_box_items(input_field)

        if adapter is not None:
            if input_field.combo_box_items is not None:
                raise ValueError(
                    "Combo box items cannot be combined with a supplied adapter"
                )
            self._validate_adapter_type(input_field.editor_type, adapter)
            return adapter

        if input_field.editor_type == EditorType.TEXT_EDIT:
            return TextEditAdapter()
        if input_field.editor_type == EditorType.INTEGER_SPIN_BOX:
            return IntegerSpinBoxAdapter()
        if input_field.editor_type == EditorType.DOUBLE_SPIN_BOX:
            return DoubleSpinBoxAdapter()
        if input_field.editor_type == EditorType.COMBO_BOX:
            return ComboBoxAdapter(input_field.combo_box_items)
        if input_field.editor_type == EditorType.CHECKABLE_COMBO_BOX:
            return CheckableComboBoxAdapter(input_field.combo_box_items)
        if input_field.editor_type == EditorType.CUSTOM:
            raise ValueError("Custom editor type requires an adapter")

        raise ValueError(f"Unsupported editor type: {input_field.editor_type}")

    def _validate_combo_box_items(self, input_field: InputField[Any]) -> None:
        """Reject combo box items configured for a different editor."""
        if input_field.combo_box_items is None:
            return

        if input_field.editor_type in (
            EditorType.COMBO_BOX,
            EditorType.CHECKABLE_COMBO_BOX,
        ):
            return

        raise ValueError(
            f"Editor type {input_field.editor_type} does not support combo box items"
        )

    def _validate_adapter_type(
        self,
        editor_type: EditorType,
        adapter: EditorAdapter[Any],
    ) -> None:
        """Ensure a supplied adapter is compatible with its editor type."""
        if editor_type == EditorType.CUSTOM:
            return

        adapter_types = {
            EditorType.TEXT_EDIT: TextEditAdapter,
            EditorType.INTEGER_SPIN_BOX: IntegerSpinBoxAdapter,
            EditorType.DOUBLE_SPIN_BOX: DoubleSpinBoxAdapter,
            EditorType.COMBO_BOX: ComboBoxAdapter,
            EditorType.CHECKABLE_COMBO_BOX: CheckableComboBoxAdapter,
        }
        expected_type = adapter_types.get(editor_type)
        if expected_type is None:
            raise ValueError(f"Unsupported editor type: {editor_type}")
        if isinstance(adapter, expected_type):
            return

        raise ValueError(
            f"Editor type {editor_type} requires {expected_type.__name__}"
        )

    @property
    def fields(self) -> List[InputField[Any]]:
        """Return fields in layout order.

        :returns: Field list copy.
        """
        return [input_field.definition for input_field in self._input_fields]

    @property
    def orientation(self) -> Qt.Orientation:
        """Return the common field orientation.

        :returns: Form orientation.
        """
        return self._orientation

    @property
    def state(self) -> FormState:
        """Return current aggregate form state.

        :returns: Immutable state snapshot.
        """
        return self._state

    @property
    def dirty(self) -> bool:
        """Return whether working values differ from saved values.

        :returns: Dirty-state flag.
        """
        return self._state.dirty

    @property
    def is_valid(self) -> Optional[bool]:
        """Return the currently known validation result.

        :returns: Validation result or ``None`` before validation.
        """
        return self._state.valid

    def validate(self) -> bool:
        """Validate all fields and show all errors.

        :returns: ``True`` when all active fields are valid.
        """
        validation_results = [
            self._validate_input_field(input_field)
            for input_field in self._input_fields
        ]
        self._refresh_state()
        return all(validation_results)

    def clear_validation(self) -> None:
        """Clear all validation without changing editor values."""
        for input_field in self._input_fields:
            input_field.clear_validation()
        self._refresh_state()

    def save(self) -> bool:
        """Validate and save all current editor values.

        :returns: ``True`` when all values were saved.
        """
        if not self.validate():
            return False

        for input_field in self._input_fields:
            field_definition = input_field.definition
            field_definition.value = input_field.adapter.get_value()
            if field_definition.is_optional_allowed:
                field_definition.is_used = (
                    input_field.optional_checkbox.isChecked()
                )
        self._refresh_state()
        return True

    def restore_saved_values(self) -> None:
        """Restore working values from saved field values."""
        for input_field in self._input_fields:
            field_definition = input_field.definition
            input_field.adapter.set_value(field_definition.value)
            input_field.set_optional_checked(field_definition.is_used)
            input_field.clear_validation()
        self._refresh_state()

    def reset_defaults(self) -> None:
        """Reset working values without changing saved field values."""
        for input_field in self._input_fields:
            field_definition = input_field.definition
            if field_definition.default_value is not None:
                input_field.adapter.reset(field_definition.default_value)
            input_field.clear_validation()
        self._refresh_state()

    def _reset_field(self, input_field: InputFieldWidget) -> None:
        """Reset one working value to its default."""
        if input_field.definition.default_value is None:
            return

        input_field.adapter.reset(input_field.definition.default_value)
        input_field.clear_validation()
        self._refresh_state()

    def _connect_input_field(
        self,
        input_field: InputFieldWidget,
    ) -> None:
        """Connect the controls of one field presentation."""
        input_field.adapter.value_changed.connect(
            lambda input_field=input_field: self._on_value_changed(input_field)
        )
        input_field.optional_checkbox.clicked.connect(
            lambda _checked, input_field=input_field: self._on_value_changed(
                input_field
            )
        )
        input_field.reset_button.clicked.connect(
            lambda _checked, input_field=input_field: self._reset_field(
                input_field
            )
        )

    def _on_value_changed(self, input_field: InputFieldWidget) -> None:
        """Handle a user change from one field presentation."""
        input_field.update_enabled()
        self._validate_input_field(input_field)
        self._refresh_state()

    def _validate_input_field(
        self,
        input_field: InputFieldWidget,
    ) -> bool:
        """Validate and display the result for one field."""
        field_definition = input_field.definition
        editor_adapter = input_field.adapter
        current_value = editor_adapter.get_value()
        error_message = ""
        if input_field.is_used() and field_definition.is_enabled:
            if field_definition.is_required and editor_adapter.is_empty(
                current_value
            ):
                error_message = field_definition.required_message
            elif (
                input_field.validator is not None
                and not editor_adapter.is_empty(current_value)
            ):
                value_text = str(current_value)
                validator_state, _, _ = input_field.validator.validate(
                    value_text,
                    len(value_text),
                )
                if validator_state != QValidator.State.Acceptable:
                    error_message = field_definition.invalid_message

        input_field.validation_result = not bool(error_message)
        input_field.show_error(error_message)
        return input_field.validation_result

    def _calculate_state(self) -> FormState:
        """Calculate aggregate form state."""
        dirty = any(
            input_field.adapter.is_changed
            or (
                input_field.definition.is_optional_allowed
                and input_field.is_used() != input_field.definition.is_used
            )
            for input_field in self._input_fields
        )
        validation_results = [
            input_field.validation_result for input_field in self._input_fields
        ]
        form_validity: Optional[bool] = None
        if any(result is False for result in validation_results):
            form_validity = False
        elif validation_results and all(
            result is True for result in validation_results
        ):
            form_validity = True
        elif not validation_results:
            form_validity = True
        return FormState(dirty, form_validity)

    def _refresh_state(self) -> None:
        """Refresh the aggregate form state."""
        self._state = self._calculate_state()

    def _align_titles(self) -> None:
        """Align title widths in horizontal forms."""
        if self._orientation != Qt.Orientation.Horizontal:
            return
        title_width = max(
            (
                input_field.title_label.sizeHint().width()
                for input_field in self._input_fields
                if input_field.definition.title
            ),
            default=0,
        )
        if title_width <= 0:
            return
        for input_field in self._input_fields:
            input_field.title_label.setFixedWidth(title_width)
