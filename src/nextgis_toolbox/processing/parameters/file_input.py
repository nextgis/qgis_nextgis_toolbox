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

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional, Sequence

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFile,
    QgsProcessingParameterRasterLayer,
)

from nextgis_toolbox.core.logging import logger
from nextgis_toolbox.processing.parameters.common import (
    InputParameterAdapter,
    InputParameterRepresentation,
    PresetPreparationContext,
    apply_parameter_help,
)
from nextgis_toolbox.processing.parameters.semantic_support import (
    build_semantic_file_filter,
    compatible_file_extensions,
    is_single_file_semantic,
    preferred_file_extension,
    processing_source_types,
)
from nextgis_toolbox.tools.models import (
    InputParameterType,
    ToolInputParameter,
)

if TYPE_CHECKING:
    from nextgis_toolbox.processing.parameters.registry import (
        InputParameterAdapterRegistry,
    )

_REMOTE_FILE_PREFIXES = (
    "http://",
    "https://",
    "storage/",
    "download/",
    "api/",
    "/api/",
    "/download/",
)


class FileInputAdapter(InputParameterAdapter):
    def __init__(
        self,
        file_reference_resolver: Optional["FileReferenceResolver"] = None,
        download_path_factory: Optional["PresetDownloadPathFactory"] = None,
    ) -> None:
        self._file_reference_resolver = (
            file_reference_resolver or FileReferenceResolver()
        )
        self._download_path_factory = (
            download_path_factory or PresetDownloadPathFactory()
        )

    def create_representation(
        self,
        parameter: ToolInputParameter,
    ) -> InputParameterRepresentation:
        qgis_parameter = QgsProcessingParameterFile(
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

    def prepare_preset_values(
        self,
        parameter: ToolInputParameter,
        value: Any,
        preset_context: PresetPreparationContext,
    ) -> Dict[str, Any]:
        file_reference = self._file_reference_resolver.resolve(value)
        if file_reference is None:
            return {parameter.name: value}

        download_directory = self._download_path_factory.build(
            preset_context.download_root,
            preset_context.algorithm_name,
            preset_context.preset_alias,
            parameter.name,
        )
        destination = (
            download_directory / file_reference.output_name
            if file_reference.output_name is not None
            else download_directory
        )
        logger.debug(
            f"Downloading preset file for '{parameter.name}' from '{file_reference.source_path}'"
        )
        saved_path = preset_context.client.download(
            file_reference.source_path,
            destination,
        )
        return {parameter.name: str(saved_path)}

    def resolve_runtime_value(
        self,
        parameter: ToolInputParameter,
        algorithm: QgsProcessingAlgorithm,
        parameters: Dict[Optional[str], Any],
        context: QgsProcessingContext,
    ) -> Optional[str]:
        result_parameter = algorithm.parameterAsFile(
            parameters, parameter.name, context
        )
        result = result_parameter if len(result_parameter) else None
        return result


class SemanticFileInputAdapter(InputParameterAdapter):
    def __init__(self, fallback: FileInputAdapter) -> None:
        self._fallback = fallback

    def create_representation(
        self,
        parameter: ToolInputParameter,
    ) -> InputParameterRepresentation:
        semantic = parameter.input_semantic
        if semantic is None:
            return self._fallback.create_representation(parameter)

        constraints = semantic.constraints
        if semantic.kind == "layer" and is_single_file_semantic(constraints):
            layer_type = constraints.get("layer_type")
            if layer_type == "vector":
                qgis_parameter = QgsProcessingParameterFeatureSource(
                    parameter.name,
                    parameter.label,
                    types=processing_source_types(
                        constraints.get("geometry_types", ["any"])
                    ),
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

            if layer_type == "raster":
                qgis_parameter = QgsProcessingParameterRasterLayer(
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

        style_type = None
        if semantic.kind == "style":
            style_type = str(constraints.get("style_type") or "") or None

        file_filter = build_semantic_file_filter(
            constraints,
            style_type=style_type,
        )
        if file_filter is None:
            return self._fallback.create_representation(parameter)

        qgis_parameter = QgsProcessingParameterFile(
            parameter.name,
            parameter.label,
            optional=not parameter.required,
            fileFilter=file_filter,
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
    ) -> Optional[str]:
        semantic = parameter.input_semantic
        if semantic is None:
            return self._fallback.resolve_runtime_value(
                parameter,
                algorithm,
                parameters,
                context,
            )

        constraints = semantic.constraints
        if semantic.kind == "layer" and is_single_file_semantic(constraints):
            layer_type = constraints.get("layer_type")
            if layer_type == "vector":
                return self._resolve_vector_layer(
                    parameter,
                    algorithm,
                    parameters,
                    context,
                )

            if layer_type == "raster":
                return self._resolve_raster_layer(
                    parameter,
                    algorithm,
                    parameters,
                    context,
                )

        return self._fallback.resolve_runtime_value(
            parameter,
            algorithm,
            parameters,
            context,
        )

    def _resolve_vector_layer(
        self,
        parameter: ToolInputParameter,
        algorithm: QgsProcessingAlgorithm,
        parameters: Dict[Optional[str], Any],
        context: QgsProcessingContext,
    ) -> Optional[str]:
        semantic = parameter.input_semantic
        if semantic is None:
            return self._fallback.resolve_runtime_value(
                parameter,
                algorithm,
                parameters,
                context,
            )

        constraints = semantic.constraints
        compatible_formats = compatible_file_extensions(constraints)
        allow_conversion = bool(constraints.get("allow_conversion"))

        if allow_conversion:
            preferred_format = preferred_file_extension(
                constraints,
                default="gpkg",
            )
            return algorithm.parameterAsCompatibleSourceLayerPath(
                parameters,
                parameter.name,
                context,
                compatible_formats or ["gpkg"],
                preferred_format or "gpkg",
            )

        vector_layer = algorithm.parameterAsVectorLayer(
            parameters,
            parameter.name,
            context,
        )
        if vector_layer is None:
            return ""

        layer_path = self._resolve_local_layer_path(vector_layer.source())
        if layer_path is None:
            raise ValueError(
                "Selected vector layer must use a local file-backed source "
                f"for parameter '{parameter.name}'"
            )

        if compatible_formats:
            source_suffix = Path(layer_path).suffix.lower().lstrip(".")
            if source_suffix not in compatible_formats:
                raise ValueError(
                    "Selected vector layer format is incompatible with "
                    f"parameter '{parameter.name}'"
                )

        return layer_path

    def _resolve_raster_layer(
        self,
        parameter: ToolInputParameter,
        algorithm: QgsProcessingAlgorithm,
        parameters: Dict[Optional[str], Any],
        context: QgsProcessingContext,
    ) -> Optional[str]:
        raster_layer = algorithm.parameterAsRasterLayer(
            parameters,
            parameter.name,
            context,
        )
        if raster_layer is None:
            return ""

        layer_path = self._resolve_local_layer_path(raster_layer.source())
        if layer_path is None:
            raise ValueError(
                "Selected raster layer must use a local file-backed source "
                f"for parameter '{parameter.name}'"
            )

        semantic = parameter.input_semantic
        if semantic is None:
            return layer_path

        compatible_formats = compatible_file_extensions(semantic.constraints)
        if compatible_formats:
            source_suffix = Path(layer_path).suffix.lower().lstrip(".")
            if source_suffix not in compatible_formats:
                raise ValueError(
                    "Selected raster layer format is incompatible with "
                    f"parameter '{parameter.name}'"
                )

        return layer_path

    def _resolve_local_layer_path(self, source: str) -> Optional[str]:
        path = source.split("|", 1)[0].strip()
        if not path:
            return None

        path_object = Path(path)
        if path_object.is_absolute() and path_object.exists():
            return str(path_object)

        return None


@dataclass(frozen=True)
class FileReference:
    source_path: str
    output_name: Optional[str]


class FileReferenceResolver:
    def __init__(
        self,
        remote_file_prefixes: Sequence[str] = _REMOTE_FILE_PREFIXES,
    ) -> None:
        self._remote_file_prefixes = tuple(remote_file_prefixes)

    def resolve(self, value: Any) -> Optional[FileReference]:
        if isinstance(value, str):
            if self._is_local_file(value):
                return None

            if self._looks_like_remote_file(value):
                return FileReference(value, None)

            return None

        if not isinstance(value, dict):
            return None

        name = value.get("name")
        url = value.get("url") or value.get("href")
        if isinstance(url, str) and url:
            return FileReference(
                url,
                name if isinstance(name, str) else None,
            )

        local = value.get("local")
        if isinstance(local, dict):
            uuid = local.get("uuid")
            if isinstance(uuid, str) and uuid:
                return FileReference(
                    f"download/storage/{uuid}",
                    name if isinstance(name, str) else None,
                )

        uuid = value.get("uuid")
        if isinstance(uuid, str) and uuid:
            return FileReference(
                f"download/storage/{uuid}",
                name if isinstance(name, str) else None,
            )

        return None

    def _is_local_file(self, value: str) -> bool:
        return Path(value).is_absolute() and Path(value).exists()

    def _looks_like_remote_file(self, value: str) -> bool:
        return value.strip().startswith(self._remote_file_prefixes)


class PresetDownloadPathFactory:
    def build(
        self,
        download_root: Path,
        algorithm_name: str,
        preset_alias: str,
        parameter_name: str,
    ) -> Path:
        return (
            download_root
            / self._slugify(algorithm_name)
            / self._slugify(preset_alias)
            / self._slugify(parameter_name)
        )

    def _slugify(self, value: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")
        return normalized or "preset"


class FileInputAdapterFactory:
    def __init__(
        self,
        file_reference_resolver: Optional[FileReferenceResolver] = None,
        download_path_factory: Optional[PresetDownloadPathFactory] = None,
    ) -> None:
        self._file_reference_resolver = (
            file_reference_resolver or FileReferenceResolver()
        )
        self._download_path_factory = (
            download_path_factory or PresetDownloadPathFactory()
        )

    def register_defaults(
        self, registry: "InputParameterAdapterRegistry"
    ) -> None:
        registry.register(InputParameterType.FILE, self._create())

    def _create(self) -> InputParameterAdapter:
        fallback = FileInputAdapter(
            file_reference_resolver=self._file_reference_resolver,
            download_path_factory=self._download_path_factory,
        )
        return SemanticFileInputAdapter(fallback)
