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

from pathlib import Path
from typing import Any, Callable, Dict, Optional, cast

from qgis.core import QgsProcessingAlgorithm, QgsProcessingContext

from nextgis_toolbox.processing.parameters.registry import (
    ProcessingParameterRegistry,
)
from nextgis_toolbox.tools.models import (
    ToolInputParameter,
    ToolOutputParameter,
)

ParameterValueResolver = Callable[
    [ToolInputParameter, Dict[str, Any], QgsProcessingContext],
    Any,
]
OutputDestinationResolver = Callable[
    [ToolOutputParameter, Dict[str, Any], QgsProcessingContext],
    Optional[Path],
]


class AlgorithmParameterResolver:
    """Resolve Processing values for Toolbox parameters."""

    def __init__(
        self,
        algorithm: QgsProcessingAlgorithm,
        parameter_registry: ProcessingParameterRegistry,
    ) -> None:
        self._algorithm = algorithm
        self._parameter_registry = parameter_registry

    def __call__(
        self,
        parameter: ToolInputParameter,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
    ) -> Any:
        return self._parameter_registry.resolve_input_value(
            parameter,
            self._algorithm,
            parameters,
            context,
        )


class AlgorithmOutputDestinationResolver:
    """Resolve Processing destination paths for Toolbox file outputs."""

    def __init__(self, algorithm: QgsProcessingAlgorithm) -> None:
        self._algorithm = algorithm

    def __call__(
        self,
        parameter: ToolOutputParameter,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
    ) -> Optional[Path]:
        output_path = self._algorithm.parameterAsFileOutput(
            cast(Dict[Optional[str], Any], parameters),
            parameter.name,
            context,
        )
        if not output_path:
            return None

        return Path(output_path)
