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

from typing import TYPE_CHECKING

from qgis.core import (
    QgsProcessingOutputString,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterVectorDestination,
)
from qgis.PyQt.QtCore import QCoreApplication

from nextgis_toolbox.processing.parameters.common import (
    OutputParameterAdapter,
    OutputParameterRepresentation,
    apply_parameter_help,
)
from nextgis_toolbox.processing.parameters.semantic_support import (
    build_semantic_file_filter,
    is_single_file_semantic,
    processing_source_types,
)
from nextgis_toolbox.tools.models import (
    OutputParameterType,
    ToolOutputParameter,
)

if TYPE_CHECKING:
    from nextgis_toolbox.processing.parameters.registry import (
        OutputParameterAdapterRegistry,
    )


class GenericOutputAdapter(OutputParameterAdapter):
    def create_representation(
        self,
        parameter: ToolOutputParameter,
    ) -> OutputParameterRepresentation:
        return OutputParameterRepresentation(
            outputs=[
                QgsProcessingOutputString(
                    parameter.name,
                    parameter.label,
                )
            ],
            parameters=[],
        )


class FileOutputAdapter(OutputParameterAdapter):
    def create_representation(
        self,
        parameter: ToolOutputParameter,
    ) -> OutputParameterRepresentation:
        qgis_parameter = self._create_parameter(parameter)
        return OutputParameterRepresentation(
            outputs=[],
            parameters=[
                apply_parameter_help(
                    qgis_parameter,
                    parameter.description,
                )
            ],
        )

    def _create_parameter(
        self,
        parameter: ToolOutputParameter,
    ):
        semantic = parameter.output_semantic
        if semantic is None:
            return self._create_file_destination_parameter(parameter)

        constraints = semantic.constraints
        if semantic.archive_contents:
            # Archive members are metadata, not a single layer destination.
            return self._create_file_destination_parameter(parameter)
        if semantic.kind == "layer" and is_single_file_semantic(constraints):
            layer_type = constraints.get("layer_type")
            if layer_type == "vector":
                return QgsProcessingParameterVectorDestination(
                    parameter.name,
                    parameter.label,
                    type=processing_source_types(
                        constraints.get("geometry_types", ["any"])
                    )[0],
                    optional=True,
                )

            if layer_type == "raster":
                return QgsProcessingParameterRasterDestination(
                    parameter.name,
                    parameter.label,
                    optional=True,
                )

        return self._create_file_destination_parameter(parameter)

    def _create_file_destination_parameter(
        self,
        parameter: ToolOutputParameter,
    ) -> QgsProcessingParameterFileDestination:
        semantic = parameter.output_semantic
        file_filter = None
        if semantic is not None:
            style_type = None
            if semantic.kind == "style":
                style_type = (
                    str(semantic.constraints.get("style_type") or "") or None
                )
            file_filter = build_semantic_file_filter(
                semantic.constraints,
                style_type=style_type,
            )

        return QgsProcessingParameterFileDestination(
            parameter.name,
            parameter.label,
            fileFilter=file_filter
            or QCoreApplication.translate(
                "ToolboxAlgorithm",
                "All files (*.*)",
            ),
            optional=True,
        )


class OutputParameterAdapterFactory:
    def __init__(self) -> None:
        self._generic_adapter = GenericOutputAdapter()
        self._file_adapter = FileOutputAdapter()

    def register_defaults(
        self, registry: "OutputParameterAdapterRegistry"
    ) -> None:
        for parameter_type in (
            OutputParameterType.STRING,
            OutputParameterType.INTEGER,
            OutputParameterType.FLOAT,
            OutputParameterType.BOOLEAN,
            OutputParameterType.DATE,
            OutputParameterType.BBOX,
            OutputParameterType.JSON,
        ):
            registry.register(parameter_type, self._generic_adapter)

        registry.register(OutputParameterType.FILE, self._file_adapter)
