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

from typing import Any, Dict, Iterable, List, Optional, Sequence

from nextgis_toolbox.core.compat import (
    ProcessingFieldParameterDataType,
    ProcessingSourceType,
)

_DRIVER_EXTENSIONS = {
    "GPKG": ("GeoPackage", ("gpkg",)),
    "GeoJSON": ("GeoJSON", ("geojson", "json")),
    "ESRI Shapefile": ("ESRI Shapefile", ("shp",)),
    "KML": ("KML", ("kml",)),
    "CSV": ("CSV", ("csv",)),
    "GTiff": ("GeoTIFF", ("tif", "tiff")),
    "SQLite": ("SQLite", ("sqlite", "db")),
    "MapInfo File": ("MapInfo", ("tab", "mif", "mid")),
    "DXF": ("DXF", ("dxf",)),
    "XLSX": ("Excel", ("xlsx",)),
}

_EXTENSION_LABELS = {
    "csv": "CSV",
    "doc": "DOC",
    "docx": "DOCX",
    "dwg": "DWG",
    "gpkg": "GeoPackage",
    "html": "HTML",
    "jpeg": "JPEG",
    "jpg": "JPEG",
    "json": "JSON",
    "kml": "KML",
    "log": "Log",
    "pdf": "PDF",
    "png": "PNG",
    "qgs": "QGIS Project",
    "qgz": "QGIS Project",
    "qml": "QGIS Style",
    "shp": "ESRI Shapefile",
    "svg": "SVG",
    "tab": "MapInfo",
    "tif": "GeoTIFF",
    "tiff": "GeoTIFF",
    "txt": "Text",
    "xlsx": "Excel",
    "xml": "XML",
    "zip": "ZIP Archive",
}

_GEOMETRY_SOURCE_TYPES = {
    "any": ProcessingSourceType.VectorAnyGeometry,
    "line": ProcessingSourceType.VectorLine,
    "mixed": ProcessingSourceType.VectorAnyGeometry,
    "no_geometry": ProcessingSourceType.Vector,
    "point": ProcessingSourceType.VectorPoint,
    "polygon": ProcessingSourceType.VectorPolygon,
}

_FIELD_TYPE_MAPPING = {
    "boolean": ProcessingFieldParameterDataType.Boolean,
    "bool": ProcessingFieldParameterDataType.Boolean,
    "date": ProcessingFieldParameterDataType.DateTime,
    "datetime": ProcessingFieldParameterDataType.DateTime,
    "double": ProcessingFieldParameterDataType.Numeric,
    "float": ProcessingFieldParameterDataType.Numeric,
    "int": ProcessingFieldParameterDataType.Numeric,
    "integer": ProcessingFieldParameterDataType.Numeric,
    "number": ProcessingFieldParameterDataType.Numeric,
    "numeric": ProcessingFieldParameterDataType.Numeric,
    "string": ProcessingFieldParameterDataType.String,
    "text": ProcessingFieldParameterDataType.String,
    "time": ProcessingFieldParameterDataType.DateTime,
}


def is_single_file_semantic(constraints: Dict[str, Any]) -> bool:
    # Missing cardinality does not guarantee a single logical dataset.
    dataset_count = constraints.get(
        "dataset_count", constraints.get("file_count")
    )
    return dataset_count == "single" or (
        isinstance(dataset_count, int)
        and not isinstance(dataset_count, bool)
        and dataset_count == 1
    )


def compatible_file_extensions(constraints: Dict[str, Any]) -> List[str]:
    extensions: List[str] = []

    for driver_name in constraints.get("drivers", []) or []:
        driver_info = _DRIVER_EXTENSIONS.get(driver_name)
        if driver_info is None:
            continue
        for extension in driver_info[1]:
            if extension not in extensions:
                extensions.append(extension)

    for extension in constraints.get("extensions", []) or []:
        normalized = str(extension).lower().lstrip(".")
        if normalized and normalized not in extensions:
            extensions.append(normalized)

    return extensions


def preferred_file_extension(
    constraints: Dict[str, Any],
    default: Optional[str] = None,
) -> Optional[str]:
    extensions = compatible_file_extensions(constraints)
    if extensions:
        return extensions[0]

    return default


def build_semantic_file_filter(
    constraints: Dict[str, Any],
    *,
    style_type: Optional[str] = None,
) -> Optional[str]:
    if style_type == "qml":
        return "QGIS Style (*.qml);;All files (*.*)"

    patterns: List[str] = []
    labels: List[str] = []

    for driver_name in constraints.get("drivers", []) or []:
        driver_info = _DRIVER_EXTENSIONS.get(driver_name)
        if driver_info is None:
            continue
        labels.append(driver_info[0])
        for extension in driver_info[1]:
            pattern = f"*.{extension}"
            if pattern not in patterns:
                patterns.append(pattern)

    for extension in constraints.get("extensions", []) or []:
        normalized = str(extension).lower().lstrip(".")
        if not normalized:
            continue
        labels.append(_EXTENSION_LABELS.get(normalized, normalized.upper()))
        pattern = f"*.{normalized}"
        if pattern not in patterns:
            patterns.append(pattern)

    if not patterns:
        return None

    label = labels[0] if len(set(labels)) == 1 else "Supported files"
    return f"{label} ({' '.join(patterns)});;All files (*.*)"


def processing_source_types(
    geometry_types: Sequence[str],
) -> List[ProcessingSourceType]:
    source_types: List[ProcessingSourceType] = []

    for geometry_type in geometry_types:
        mapped = _GEOMETRY_SOURCE_TYPES.get(geometry_type)
        if mapped is not None and mapped not in source_types:
            source_types.append(mapped)

    if source_types:
        return source_types

    return [ProcessingSourceType.VectorAnyGeometry]


def processing_field_data_type(
    field_types: Iterable[str],
) -> ProcessingFieldParameterDataType:
    normalized_types = {
        str(field_type).lower() for field_type in field_types if field_type
    }
    if not normalized_types:
        return ProcessingFieldParameterDataType.Any

    mapped_types = {
        _FIELD_TYPE_MAPPING[field_type]
        for field_type in normalized_types
        if field_type in _FIELD_TYPE_MAPPING
    }
    if len(mapped_types) != 1:
        return ProcessingFieldParameterDataType.Any

    return next(iter(mapped_types))
