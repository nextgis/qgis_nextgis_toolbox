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

from typing import TYPE_CHECKING, Any, Dict, Iterable, Optional, cast

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingParameterEnum,
)

from nextgis_toolbox.core.logging import logger
from nextgis_toolbox.processing.parameters.common import (
    InputParameterAdapter,
    InputParameterRepresentation,
    PresetPreparationContext,
    apply_parameter_help,
)
from nextgis_toolbox.tools.models import (
    InputParameterType,
    ToolInputParameter,
)

if TYPE_CHECKING:
    from nextgis_toolbox.processing.parameters.registry import (
        InputParameterAdapterRegistry,
    )


class ChoiceInputAdapter(InputParameterAdapter):
    def __init__(
        self,
        *,
        multiple: bool,
        value_mapper: Optional["ChoiceValueMapper"] = None,
    ) -> None:
        self._multiple = multiple
        self._value_mapper = value_mapper or ChoiceValueMapper()

    def create_representation(
        self,
        parameter: ToolInputParameter,
    ) -> InputParameterRepresentation:
        choices = [
            choice.get("alias") or choice.get("value", "")
            for choice in (parameter.choices or [])
        ]
        qgis_parameter = QgsProcessingParameterEnum(
            parameter.name,
            parameter.label,
            options=choices,
            allowMultiple=self._multiple,
            optional=not parameter.required,
        )
        return InputParameterRepresentation(
            parameters=[
                apply_parameter_help(
                    qgis_parameter,
                    parameter.description,
                )
            ]
        )

    def prepare_preset_values(
        self,
        parameter: ToolInputParameter,
        value: Any,
        preset_context: PresetPreparationContext,
    ) -> Dict[str, Any]:
        del preset_context
        if self._multiple:
            return {
                parameter.name: self._value_mapper.indexes(parameter, value)
            }

        return {parameter.name: self._value_mapper.index(parameter, value)}

    def resolve_runtime_value(
        self,
        parameter: ToolInputParameter,
        algorithm: QgsProcessingAlgorithm,
        parameters: Dict[Optional[str], Any],
        context: QgsProcessingContext,
    ) -> Any:
        if parameters[parameter.name] is None:
            return None
        choices = parameter.choices or []
        qgis_parameters = cast(Dict[Optional[str], Any], parameters)
        if self._multiple:
            selected_indexes = algorithm.parameterAsEnums(
                qgis_parameters,
                parameter.name,
                context,
            )
            return [choices[index]["value"] for index in selected_indexes]

        selected_index = algorithm.parameterAsEnum(
            qgis_parameters,
            parameter.name,
            context,
        )
        if not choices:
            return None
        return choices[selected_index]["value"]


class ChoiceValueMapper:
    def index(self, parameter: ToolInputParameter, value: Any) -> Any:
        if isinstance(value, int):
            return value

        for index, choice in enumerate(parameter.choices or []):
            if value in self._candidates(choice):
                return index

        logger.warning(
            f"Unsupported preset value '{value}' for choice '{parameter.name}'"
        )
        return value

    def indexes(self, parameter: ToolInputParameter, value: Any) -> Any:
        if isinstance(value, list):
            return [self.index(parameter, item) for item in value]

        return self.index(parameter, value)

    def _candidates(self, choice: Dict[str, Any]) -> Iterable[Any]:
        return (
            choice.get("value"),
            choice.get("alias"),
            choice.get("name"),
            choice.get("id"),
        )


class ChoiceInputAdapterFactory:
    def __init__(
        self,
        value_mapper: Optional[ChoiceValueMapper] = None,
    ) -> None:
        self._value_mapper = value_mapper or ChoiceValueMapper()

    def register_defaults(
        self, registry: "InputParameterAdapterRegistry"
    ) -> None:
        registry.register(
            InputParameterType.SINGLE_CHOICE,
            self._create(multiple=False),
        )
        registry.register(
            InputParameterType.MULTIPLE_CHOICE,
            self._create(multiple=True),
        )

    def _create(self, *, multiple: bool) -> ChoiceInputAdapter:
        return ChoiceInputAdapter(
            multiple=multiple,
            value_mapper=self._value_mapper,
        )
