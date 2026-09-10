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
import json
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Optional,
    Sequence,
    Type,
    cast,
)

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterColor,
    QgsProcessingParameterCrs,
    QgsProcessingParameterDateTime,
    QgsProcessingParameterDefinition,
    QgsProcessingParameterExtent,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
)

from nextgis_toolbox.core.compat import ProcessingNumberParameterType
from nextgis_toolbox.processing.parameters.common import (
    InputParameterAdapter,
    InputParameterRepresentation,
    PresetPreparationContext,
    apply_parameter_help,
)
from nextgis_toolbox.processing.parameters.semantic_support import (
    processing_field_data_type,
)
from nextgis_toolbox.tools.models import (
    InputParameterType,
    ToolInputParameter,
)

if TYPE_CHECKING:
    from nextgis_toolbox.processing.parameters.registry import (
        InputParameterAdapterRegistry,
    )

RuntimeResolver = Callable[
    [
        QgsProcessingAlgorithm,
        Dict[Optional[str], Any],
        str,
        QgsProcessingContext,
    ],
    Any,
]
PresetConverter = Callable[[Any], Any]


@dataclass(frozen=True)
class ScalarAdapterDefinition:
    parameter_type: InputParameterType
    parameter_class: Any
    resolver: RuntimeResolver
    preset_converter: PresetConverter
    number_type: Optional[ProcessingNumberParameterType] = None


class ScalarInputAdapter(InputParameterAdapter):
    def __init__(
        self,
        parameter_class: Type[QgsProcessingParameterDefinition],
        resolver: RuntimeResolver,
        *,
        preset_converter: Optional[PresetConverter] = None,
        number_type: Optional[ProcessingNumberParameterType] = None,
    ) -> None:
        if (
            parameter_class is QgsProcessingParameterNumber
            and number_type is None
        ):
            raise ValueError("Number parameters require explicit number_type")

        self._parameter_class = parameter_class
        self._resolver = resolver
        self._preset_converter = preset_converter or (lambda value: value)
        self._number_type = number_type

    def create_representation(
        self,
        parameter: ToolInputParameter,
    ) -> InputParameterRepresentation:
        optional = not parameter.required
        label = parameter.label

        if self._parameter_class is QgsProcessingParameterNumber:
            qgis_parameter = QgsProcessingParameterNumber(
                parameter.name,
                label,
                type=cast(
                    ProcessingNumberParameterType,
                    self._number_type,
                ),
                optional=optional,
            )
        else:
            qgis_parameter = self._parameter_class(
                parameter.name,
                label,
                optional=optional,
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
        return {parameter.name: self._preset_converter(value)}

    def resolve_runtime_value(
        self,
        parameter: ToolInputParameter,
        algorithm: QgsProcessingAlgorithm,
        parameters: Dict[Optional[str], Any],
        context: QgsProcessingContext,
    ) -> Any:
        return self._resolver(algorithm, parameters, parameter.name, context)


class SemanticStringInputAdapter(InputParameterAdapter):
    def __init__(self, fallback: ScalarInputAdapter) -> None:
        self._fallback = fallback

    def create_representation(
        self,
        parameter: ToolInputParameter,
    ) -> InputParameterRepresentation:
        semantic = parameter.input_semantic
        if semantic is None:
            return self._fallback.create_representation(parameter)

        if semantic.kind == "field":
            source_parameter_name = self._field_source_parameter_name(
                parameter
            )
            if source_parameter_name is not None:
                qgis_parameter = QgsProcessingParameterField(
                    parameter.name,
                    parameter.label,
                    parentLayerParameterName=source_parameter_name,
                    type=processing_field_data_type(
                        semantic.constraints.get("field_types", [])
                    ),
                    allowMultiple=False,
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

        if semantic.kind == "crs":
            qgis_parameter = QgsProcessingParameterCrs(
                parameter.name,
                parameter.label,
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

        if semantic.kind == "color":
            qgis_parameter = QgsProcessingParameterColor(
                parameter.name,
                parameter.label,
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

        return self._fallback.create_representation(parameter)

    def prepare_preset_values(
        self,
        parameter: ToolInputParameter,
        value: Any,
        preset_context: PresetPreparationContext,
    ) -> Dict[str, Any]:
        return self._fallback.prepare_preset_values(
            parameter,
            value,
            preset_context,
        )

    def resolve_runtime_value(
        self,
        parameter: ToolInputParameter,
        algorithm: QgsProcessingAlgorithm,
        parameters: Dict[Optional[str], Any],
        context: QgsProcessingContext,
    ) -> Any:
        semantic = parameter.input_semantic
        if semantic is None:
            return self._fallback.resolve_runtime_value(
                parameter,
                algorithm,
                parameters,
                context,
            )

        if semantic.kind == "field":
            return algorithm.parameterAsString(
                parameters,
                parameter.name,
                context,
            )

        if semantic.kind == "crs":
            crs = algorithm.parameterAsCrs(
                parameters,
                parameter.name,
                context,
            )
            if not crs.isValid():
                return ""
            return crs.authid()

        if semantic.kind == "color":
            color = algorithm.parameterAsColor(
                parameters,
                parameter.name,
                context,
            )
            if not color.isValid():
                return ""
            return color.name()

        return self._fallback.resolve_runtime_value(
            parameter,
            algorithm,
            parameters,
            context,
        )

    def _field_source_parameter_name(
        self,
        parameter: ToolInputParameter,
    ) -> Optional[str]:
        semantic = parameter.input_semantic
        if semantic is None:
            return None

        for relation in semantic.relations:
            if relation.relation_type == "fields":
                return relation.source_parameter

        return None


class ScalarRuntimeValueResolver:
    def resolve_string(
        self,
        algorithm: QgsProcessingAlgorithm,
        parameters: Dict[Optional[str], Any],
        name: str,
        context: QgsProcessingContext,
    ) -> Optional[str]:
        result_parametr = algorithm.parameterAsString(
            parameters, name, context
        )
        if len(result_parametr):
            result = result_parametr
        else:
            result = None
        return result

    def resolve_boolean(
        self,
        algorithm: QgsProcessingAlgorithm,
        parameters: Dict[Optional[str], Any],
        name: str,
        context: QgsProcessingContext,
    ) -> bool:
        return algorithm.parameterAsBool(parameters, name, context)

    def resolve_int(
        self,
        algorithm: QgsProcessingAlgorithm,
        parameters: Dict[Optional[str], Any],
        name: str,
        context: QgsProcessingContext,
    ) -> Optional[int]:
        return algorithm.parameterAsInt(parameters, name, context)

    def resolve_float(
        self,
        algorithm: QgsProcessingAlgorithm,
        parameters: Dict[Optional[str], Any],
        name: str,
        context: QgsProcessingContext,
    ) -> Optional[float]:
        return algorithm.parameterAsDouble(parameters, name, context)

    def resolve_bbox(
        self,
        algorithm: QgsProcessingAlgorithm,
        parameters: Dict[Optional[str], Any],
        name: str,
        context: QgsProcessingContext,
    ) -> Optional[dict]:
        extent = algorithm.parameterAsExtent(parameters, name, context)
        if extent.isNull():
            result = None
        else:
            result = {
                "east": extent.xMaximum(),
                "west": extent.xMinimum(),
                "north": extent.yMaximum(),
                "south": extent.yMinimum(),
            }
        return result

    def resolve_json(
        self,
        algorithm: QgsProcessingAlgorithm,
        parameters: Dict[Optional[str], Any],
        name: str,
        context: QgsProcessingContext,
    ) -> Any:
        parameter = parameters[name]
        if len(parameter):
            result = json.loads(parameter)
        else:
            result = None
        return result

    def resolve_date(
        self,
        algorithm: QgsProcessingAlgorithm,
        parameters: Dict[Optional[str], Any],
        name: str,
        context: QgsProcessingContext,
    ) -> Optional[str]:
        datetime = algorithm.parameterAsDateTime(parameters, name, context)
        if not datetime.isValid():
            return None
        else:
            return datetime.toString("yyyy-MM-dd")


class ScalarPresetValueConverter:
    def pass_through(self, value: Any) -> Any:
        return value

    def coerce_int(self, value: Any) -> Any:
        if isinstance(value, str):
            return int(value)
        return value

    def coerce_float(self, value: Any) -> Any:
        if isinstance(value, str):
            return float(value)
        return value

    def coerce_boolean(self, value: Any) -> Any:
        if isinstance(value, str):
            return value.lower() in {"1", "true", "yes", "on"}
        return value

    def coerce_string_extent(self, value: Any) -> str:
        if isinstance(value, dict):
            xMin = value["west"]
            yMin = value["south"]
            xMax = value["east"]
            yMax = value["north"]
            result = f"{xMin},{yMin},{xMax},{yMax}"
        else:
            raise Exception(f"Preset bbox not dict: {value} {type(value)}")
        return result

    def coerce_string_json(self, value: Any) -> str:
        result = json.dumps(value)
        return result


class ScalarInputAdapterFactory:
    def __init__(
        self,
        runtime_resolver: Optional[ScalarRuntimeValueResolver] = None,
        preset_converter: Optional[ScalarPresetValueConverter] = None,
    ) -> None:
        self._runtime_resolver = (
            runtime_resolver or ScalarRuntimeValueResolver()
        )
        self._preset_converter = (
            preset_converter or ScalarPresetValueConverter()
        )

    def register_defaults(
        self, registry: "InputParameterAdapterRegistry"
    ) -> None:
        for definition in self._definitions():
            registry.register(
                definition.parameter_type,
                self._create_adapter(definition),
            )

    def _definitions(self) -> Sequence[ScalarAdapterDefinition]:
        return (
            ScalarAdapterDefinition(
                InputParameterType.STRING,
                QgsProcessingParameterString,
                self._runtime_resolver.resolve_string,
                self._preset_converter.pass_through,
            ),
            ScalarAdapterDefinition(
                InputParameterType.BOOLEAN,
                QgsProcessingParameterBoolean,
                self._runtime_resolver.resolve_boolean,
                self._preset_converter.coerce_boolean,
            ),
            ScalarAdapterDefinition(
                InputParameterType.INTEGER,
                QgsProcessingParameterNumber,
                self._runtime_resolver.resolve_int,
                self._preset_converter.coerce_int,
                ProcessingNumberParameterType.Integer,
            ),
            ScalarAdapterDefinition(
                InputParameterType.FLOAT,
                QgsProcessingParameterNumber,
                self._runtime_resolver.resolve_float,
                self._preset_converter.coerce_float,
                ProcessingNumberParameterType.Double,
            ),
            ScalarAdapterDefinition(
                InputParameterType.BBOX,
                QgsProcessingParameterExtent,
                self._runtime_resolver.resolve_bbox,
                self._preset_converter.coerce_string_extent,
            ),
            ScalarAdapterDefinition(
                InputParameterType.DATE,
                QgsProcessingParameterDateTime,
                self._runtime_resolver.resolve_date,
                self._preset_converter.pass_through,
            ),
            ScalarAdapterDefinition(
                InputParameterType.JSON,
                QgsProcessingParameterString,
                self._runtime_resolver.resolve_json,
                self._preset_converter.coerce_string_json,
            ),
        )

    def _create_adapter(
        self,
        definition: ScalarAdapterDefinition,
    ) -> ScalarInputAdapter:
        adapter = ScalarInputAdapter(
            definition.parameter_class,
            definition.resolver,
            preset_converter=definition.preset_converter,
            number_type=definition.number_type,
        )
        if definition.parameter_type == InputParameterType.STRING:
            return SemanticStringInputAdapter(adapter)

        return adapter
