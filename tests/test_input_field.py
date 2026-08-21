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

from typing import Optional

import pytest
from qgis.PyQt.QtWidgets import QLineEdit

from nextgis_toolbox.shared.ui.input_field import (
    CheckableComboBoxAdapter,
    ComboBoxAdapter,
    DoubleSpinBoxAdapter,
    EditorAdapter,
    EditorType,
    FieldsForm,
    InputField,
    IntegerSpinBoxAdapter,
    TextEditAdapter,
)


class CustomTextEditAdapter(EditorAdapter[str]):
    """Adapter that exposes its editor without using the base private field."""

    def __init__(self) -> None:
        super().__init__()
        self._text_edit = QLineEdit()
        self._text_edit.textChanged.connect(
            lambda _text: self.value_changed.emit()
        )

    @property
    def editor(self) -> QLineEdit:
        return self._text_edit

    def get_value(self) -> str:
        return self._text_edit.text()

    def set_value(self, value: Optional[str]) -> None:
        signals_were_blocked = self._text_edit.blockSignals(True)
        try:
            self._text_edit.setText("" if value is None else str(value))
        finally:
            self._text_edit.blockSignals(signals_were_blocked)


def _create_text_form():
    input_field = InputField(
        title="Text",
        editor_type=EditorType.TEXT_EDIT,
        value="saved value",
    )
    form = FieldsForm()
    editor = form.add_field(input_field)
    return form, editor


def test_text_edit_adapter_treats_falsy_values_as_empty(qgis_app) -> None:
    del qgis_app

    adapter = TextEditAdapter()

    try:
        assert adapter.is_empty("") is True
        assert adapter.is_empty("value") is False
    finally:
        adapter.editor.deleteLater()


def test_form_remains_dirty_after_value_is_restored(qgis_app) -> None:
    del qgis_app

    form, editor = _create_text_form()

    try:
        assert form.dirty is False

        editor.setText("changed value")
        assert form.dirty is True

        editor.setText("saved value")
        assert form.dirty is True
    finally:
        form.deleteLater()


def test_form_creates_builtin_editor_adapters(qgis_app) -> None:
    del qgis_app

    form = FieldsForm()
    editor_types = [
        (EditorType.TEXT_EDIT, TextEditAdapter),
        (EditorType.INTEGER_SPIN_BOX, IntegerSpinBoxAdapter),
        (EditorType.DOUBLE_SPIN_BOX, DoubleSpinBoxAdapter),
        (EditorType.COMBO_BOX, ComboBoxAdapter),
        (EditorType.CHECKABLE_COMBO_BOX, CheckableComboBoxAdapter),
    ]

    try:
        for editor_type, _adapter_type in editor_types:
            combo_box_items = [("Option", "option")]
            if editor_type not in (
                EditorType.COMBO_BOX,
                EditorType.CHECKABLE_COMBO_BOX,
            ):
                combo_box_items = None
            form.add_field(
                InputField(
                    title="Field",
                    editor_type=editor_type,
                    combo_box_items=combo_box_items,
                )
            )

        actual_adapter_types = [
            type(input_field.adapter) for input_field in form._input_fields
        ]
        expected_adapter_types = [
            adapter_type for _editor_type, adapter_type in editor_types
        ]
        assert actual_adapter_types == expected_adapter_types
    finally:
        form.deleteLater()


def test_form_initializes_combo_adapters_from_combo_box_items(
    qgis_app,
) -> None:
    del qgis_app

    form = FieldsForm()
    combo_box_items = [("One", "one"), ("Two", "two")]

    try:
        form.add_field(
            InputField(
                title="Single choice",
                editor_type=EditorType.COMBO_BOX,
                value="two",
                combo_box_items=combo_box_items,
            )
        )
        form.add_field(
            InputField(
                title="Multiple choice",
                editor_type=EditorType.CHECKABLE_COMBO_BOX,
                value=["one", "two"],
                combo_box_items=combo_box_items,
            )
        )

        single_choice_adapter = form._input_fields[0].adapter
        multiple_choice_adapter = form._input_fields[1].adapter
        assert isinstance(single_choice_adapter, ComboBoxAdapter)
        assert isinstance(multiple_choice_adapter, CheckableComboBoxAdapter)
        assert single_choice_adapter.get_value() == "two"
        assert multiple_choice_adapter.get_value() == ["one", "two"]
    finally:
        form.deleteLater()


def test_form_uses_supplied_custom_adapter(qgis_app) -> None:
    del qgis_app

    form = FieldsForm()
    adapter = CustomTextEditAdapter()

    try:
        editor = form.add_field(
            InputField(
                title="Custom",
                editor_type=EditorType.CUSTOM,
                value="saved value",
            ),
            adapter=adapter,
        )

        assert form._input_fields[0].adapter is adapter
        assert editor is adapter.editor
        assert adapter.get_value() == "saved value"
    finally:
        form.deleteLater()


def test_form_rejects_invalid_editor_configuration(qgis_app) -> None:
    del qgis_app

    form = FieldsForm()

    try:
        with pytest.raises(ValueError, match="requires an adapter"):
            form.add_field(
                InputField(
                    title="Custom",
                    editor_type=EditorType.CUSTOM,
                )
            )

        with pytest.raises(ValueError, match="requires TextEditAdapter"):
            form.add_field(
                InputField(
                    title="Text edit",
                    editor_type=EditorType.TEXT_EDIT,
                ),
                adapter=ComboBoxAdapter(),
            )

        with pytest.raises(
            ValueError, match="does not support combo box items"
        ):
            form.add_field(
                InputField(
                    title="Text edit",
                    editor_type=EditorType.TEXT_EDIT,
                    combo_box_items=[("Option", "option")],
                )
            )

        with pytest.raises(
            ValueError,
            match="Combo box items cannot be combined with a supplied adapter",
        ):
            form.add_field(
                InputField(
                    title="Combo box",
                    editor_type=EditorType.COMBO_BOX,
                    combo_box_items=[("Option", "option")],
                ),
                adapter=ComboBoxAdapter(),
            )
    finally:
        form.deleteLater()
