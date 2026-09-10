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

from typing import Any, Dict, List, Optional, cast

from qgis.core import QgsProcessingAlgorithm, QgsProcessingContext

from nextgis_toolbox.processing.parameters.common import (
    InputParameterAdapter,
    InputParameterRepresentation,
    OutputParameterAdapter,
    OutputParameterRepresentation,
    PresetPreparationContext,
)
from nextgis_toolbox.processing.parameters.factories import (
    BuiltinParameterAdapterFactory,
)
from nextgis_toolbox.tools.models import (
    InputParameterType,
    OutputParameterType,
    ToolInputParameter,
    ToolOutputParameter,
)


class InputParameterAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: Dict[
            InputParameterType,
            List[InputParameterAdapter],
        ] = {}

    def register(
        self,
        parameter_type: InputParameterType,
        adapter: InputParameterAdapter,
        *,
        prepend: bool = False,
    ) -> None:
        adapters = self._adapters.setdefault(parameter_type, [])
        if prepend:
            adapters.insert(0, adapter)
            return

        adapters.append(adapter)

    def adapter_for(
        self, parameter: ToolInputParameter
    ) -> InputParameterAdapter:
        adapters = self._adapters.get(parameter.parameter_type, [])
        if not adapters:
            raise KeyError(
                f"No input parameter adapter for '{parameter.parameter_type.value}'"
            )
        return adapters[0]


class OutputParameterAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: Dict[
            OutputParameterType,
            List[OutputParameterAdapter],
        ] = {}

    def register(
        self,
        parameter_type: OutputParameterType,
        adapter: OutputParameterAdapter,
        *,
        prepend: bool = False,
    ) -> None:
        adapters = self._adapters.setdefault(parameter_type, [])
        if prepend:
            adapters.insert(0, adapter)
            return

        adapters.append(adapter)

    def adapter_for(
        self,
        parameter: ToolOutputParameter,
    ) -> OutputParameterAdapter:
        adapters = self._adapters.get(parameter.parameter_type, [])
        if not adapters:
            raise KeyError(
                f"No output parameter adapter for '{parameter.parameter_type.value}'"
            )
        return adapters[0]


class ProcessingParameterRegistry:
    def __init__(
        self,
        input_registry: Optional[InputParameterAdapterRegistry] = None,
        output_registry: Optional[OutputParameterAdapterRegistry] = None,
    ) -> None:
        self._input_registry = (
            input_registry or InputParameterAdapterRegistry()
        )
        self._output_registry = (
            output_registry or OutputParameterAdapterRegistry()
        )

    def register_input_adapter(
        self,
        parameter_type: InputParameterType,
        adapter: InputParameterAdapter,
        *,
        prepend: bool = False,
    ) -> None:
        self._input_registry.register(
            parameter_type,
            adapter,
            prepend=prepend,
        )

    def register_output_adapter(
        self,
        parameter_type: OutputParameterType,
        adapter: OutputParameterAdapter,
        *,
        prepend: bool = False,
    ) -> None:
        self._output_registry.register(
            parameter_type,
            adapter,
            prepend=prepend,
        )

    @property
    def input_registry(self) -> InputParameterAdapterRegistry:
        return self._input_registry

    @property
    def output_registry(self) -> OutputParameterAdapterRegistry:
        return self._output_registry

    def create_input_representation(
        self,
        parameter: ToolInputParameter,
    ) -> InputParameterRepresentation:
        return self._input_registry.adapter_for(
            parameter
        ).create_representation(parameter)

    def prepare_input_preset_values(
        self,
        parameter: ToolInputParameter,
        value: Any,
        preset_context: PresetPreparationContext,
    ) -> Dict[str, Any]:
        return self._input_registry.adapter_for(
            parameter
        ).prepare_preset_values(
            parameter,
            value,
            preset_context,
        )

    def resolve_input_value(
        self,
        parameter: ToolInputParameter,
        algorithm: QgsProcessingAlgorithm,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
    ) -> Any:
        return self._input_registry.adapter_for(
            parameter
        ).resolve_runtime_value(
            parameter,
            algorithm,
            cast(Dict[Optional[str], Any], parameters),
            context,
        )

    def create_output_representation(
        self,
        parameter: ToolOutputParameter,
    ) -> OutputParameterRepresentation:
        return self._output_registry.adapter_for(
            parameter
        ).create_representation(parameter)


def create_default_parameter_registry(
    adapter_factory: Optional[BuiltinParameterAdapterFactory] = None,
) -> ProcessingParameterRegistry:
    registry = ProcessingParameterRegistry()
    builtin_factory = adapter_factory or BuiltinParameterAdapterFactory()
    builtin_factory.register_defaults(
        registry.input_registry,
        registry.output_registry,
    )
    return registry
