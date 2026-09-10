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

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingOutputDefinition,
    QgsProcessingParameterDefinition,
)

from nextgis_toolbox.api.client import ToolboxApiClient
from nextgis_toolbox.tools.models import (
    ToolInputParameter,
    ToolOutputParameter,
)


@dataclass(frozen=True)
class InputParameterRepresentation:
    parameters: Sequence[QgsProcessingParameterDefinition]


@dataclass(frozen=True)
class OutputParameterRepresentation:
    outputs: Sequence[QgsProcessingOutputDefinition]
    parameters: Sequence[QgsProcessingParameterDefinition]


@dataclass(frozen=True)
class PresetPreparationContext:
    client: ToolboxApiClient
    algorithm_name: str
    preset_alias: str
    download_root: Path


class InputParameterAdapter:
    def create_representation(
        self,
        parameter: ToolInputParameter,
    ) -> InputParameterRepresentation:
        raise NotImplementedError()

    def prepare_preset_values(
        self,
        parameter: ToolInputParameter,
        value: Any,
        preset_context: PresetPreparationContext,
    ) -> Dict[str, Any]:
        raise NotImplementedError()

    def resolve_runtime_value(
        self,
        parameter: ToolInputParameter,
        algorithm: QgsProcessingAlgorithm,
        parameters: Dict[Optional[str], Any],
        context: QgsProcessingContext,
    ) -> Any:
        raise NotImplementedError()


class OutputParameterAdapter:
    def create_representation(
        self,
        parameter: ToolOutputParameter,
    ) -> OutputParameterRepresentation:
        raise NotImplementedError()


def apply_parameter_help(
    parameter_definition: QgsProcessingParameterDefinition,
    help_text: Optional[str],
) -> QgsProcessingParameterDefinition:
    if help_text:
        parameter_definition.setHelp(help_text)

    return parameter_definition
