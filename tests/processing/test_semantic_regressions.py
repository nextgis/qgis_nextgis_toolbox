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
from dataclasses import replace
from unittest.mock import Mock

import pytest
from qgis.core import (
    QgsProcessingContext,
    QgsProcessingParameterColor,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterFile,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterString,
)

from nextgis_toolbox.core.compat import ProcessingSourceType
from nextgis_toolbox.processing.parameters import (
    create_default_parameter_registry,
)
from nextgis_toolbox.processing.parameters.semantic_support import (
    is_single_file_semantic,
)
from nextgis_toolbox.processing.toolbox_algorithm import ToolboxAlgorithm
from nextgis_toolbox.tools.models import (
    InputParameterType,
    OutputParameterType,
    ToolboxTool,
    ToolInputParameter,
    ToolOutputParameter,
)
from nextgis_toolbox.tools.semantics import (
    ToolInputSemantic,
    ToolOutputSemantic,
    ToolSemanticRelation,
    ToolSemanticsCatalog,
)


@pytest.fixture
def catalog():
    return json.loads(
        ToolSemanticsCatalog.default_resource_path().read_text("utf-8")
    )


def file_input(constraints):
    return ToolInputParameter(
        name="source",
        parameter_type=InputParameterType.FILE,
        alias="Source",
        description=None,
        required=True,
        choices=None,
        input_semantic=ToolInputSemantic(
            kind="layer", constraints=constraints
        ),
    )


@pytest.mark.parametrize(
    "tool, parameter, extensions",
    [
        ("ai2geo", "pdf_file", ["pdf", "ai"]),
        ("coords2poly", "source", ["txt", "csv", "xls", "xlsx"]),
        ("import_dwg", "dwg_file", ["dwg"]),
        ("import_dwg_libdxfrw", "dwg_file", ["dwg"]),
        ("tropomi2geotiff", "netcdf_file", ["nc"]),
        ("pointcloud2tileset", "pointcloud", ["las", "laz", "ply", "xyz"]),
    ],
)
def test_restored_logical_formats(catalog, tool, parameter, extensions):
    assert (
        catalog[tool]["inputs"][parameter]["constraints"]["extensions"]
        == extensions
    )


@pytest.mark.parametrize(
    "tool, parameter, driver",
    [
        ("tropomi2geotiff", "geotiff_file", "GTiff"),
        ("water_usage", "output_file", "GPKG"),
        ("aggregate_raster_layer_to_h3", "result", "GPKG"),
        ("layerstack", "result", "GTiff"),
        ("raster2mbtiles", "result", "MBTILES"),
        ("plk_attrs", "result_file", "GPKG"),
    ],
)
def test_output_driver_has_no_redundant_extensions(
    catalog, tool, parameter, driver
):
    constraints = catalog[tool]["outputs"][parameter]["constraints"]
    assert driver in constraints["drivers"]
    assert "extensions" not in constraints


def test_water_usage_filter_preserves_object_number_format(catalog):
    assert catalog["water_usage"]["inputs"]["uniq_number"]["constraints"] == {
        "pattern": r"^\d{23}$",
        "min_length": 23,
        "max_length": 23,
    }


def test_hello_sleep_clamping_is_not_an_input_upper_bound(catalog):
    constraints = catalog["hello"]["inputs"]["sleep"]["constraints"]
    assert constraints == {"min_value": 0, "unit": "s"}


@pytest.mark.parametrize(
    "tool, name",
    [
        ("geocodetable", "result_file"),
        ("mapinfo2qgis", "result_file"),
        ("plk_catalog", "result_file"),
        ("improvedem", "result_file"),
        ("zmu_data_analysis", "result_file"),
        ("import_egrn", "converted"),
        ("webmap2qgis", "output_file"),
        ("kptbatch_validator", "result"),
        ("xml_decl_to_vector", "result"),
        ("xml_lpo_to_vector", "result"),
        ("xml_plv_to_vector", "result"),
        ("xml_tol_to_vector", "result"),
        ("table2geo", "result"),
        ("temporal_split", "result"),
        ("flood_analysis", "result_file"),
        ("landslide_analysis", "result_file"),
        ("terrain_analysis", "result_file"),
        ("wildfire_analysis", "result_file"),
        ("planetary_search", "result_file"),
        ("panotag", "photos_with_tags"),
    ],
)
def test_archive_destination_uses_artifact_not_member_formats(
    qgis_app, catalog, tool, name
):
    payload = catalog[tool]["outputs"][name]
    semantic = ToolOutputSemantic.from_json(payload)
    assert semantic.archive_contents
    assert semantic.to_json() == payload
    parameter = ToolOutputParameter(
        name=name,
        parameter_type=OutputParameterType.FILE,
        alias=None,
        description=None,
        required=True,
        output_semantic=semantic,
    )
    representation = (
        create_default_parameter_registry().create_output_representation(
            parameter
        )
    )
    definition = representation.parameters[0]
    assert isinstance(definition, QgsProcessingParameterFileDestination)
    assert "*.zip" in definition.fileFilter()
    assert "*.gpkg" not in definition.fileFilter()
    assert "*.log" not in definition.fileFilter()


def test_xml_plv_archive_contains_vector_layers(catalog):
    member = catalog["xml_plv_to_vector"]["outputs"]["result"][
        "archive_contents"
    ][0]
    assert member["kind"] == "layer"
    assert member["constraints"]["layer_type"] == "vector"
    assert member["constraints"]["drivers"] == [
        "GPKG",
        "GeoJSON",
        "ESRI Shapefile",
        "MapInfo File",
    ]


@pytest.mark.parametrize(
    "constraints, expected",
    [
        ({"dataset_count": "single"}, True),
        ({"dataset_count": 1}, True),
        ({"dataset_count": "multiple"}, False),
        ({"dataset_count": 2}, False),
        ({}, False),
        ({"dataset_count": None}, False),
        ({"dataset_count": True}, False),
        ({"dataset_count": 1.0}, False),
        ({"file_count": "single"}, True),
        ({"file_count": "multiple"}, False),
        ({"dataset_count": "multiple", "file_count": "single"}, False),
    ],
)
def test_logical_dataset_cardinality(constraints, expected):
    assert is_single_file_semantic(constraints) is expected


@pytest.mark.parametrize("cardinality", ["multiple", 2, None])
@pytest.mark.parametrize("layer_type", ["vector", "raster"])
def test_collection_or_unknown_cardinality_keeps_file_input(
    qgis_app, cardinality, layer_type
):
    constraints = {"layer_type": layer_type}
    if cardinality is not None:
        constraints["dataset_count"] = cardinality
    parameter = file_input(constraints)
    registry = create_default_parameter_registry()
    representation = registry.create_input_representation(parameter)
    assert isinstance(representation.parameters[0], QgsProcessingParameterFile)

    algorithm = Mock()
    algorithm.parameterAsFile.return_value = "/tmp/collection.zip"
    assert (
        registry.resolve_input_value(
            parameter, algorithm, {}, QgsProcessingContext()
        )
        == "/tmp/collection.zip"
    )
    algorithm.parameterAsFile.assert_called_once()
    algorithm.parameterAsVectorLayer.assert_not_called()
    algorithm.parameterAsRasterLayer.assert_not_called()


@pytest.mark.parametrize("cardinality", ["multiple", 2, None])
@pytest.mark.parametrize("layer_type", ["vector", "raster"])
def test_collection_or_unknown_cardinality_keeps_file_destination(
    qgis_app, cardinality, layer_type
):
    constraints = {"layer_type": layer_type}
    if cardinality is not None:
        constraints["dataset_count"] = cardinality
    parameter = ToolOutputParameter(
        name="result",
        parameter_type=OutputParameterType.FILE,
        alias=None,
        description=None,
        required=True,
        output_semantic=ToolOutputSemantic(
            kind="layer", constraints=constraints
        ),
    )
    representation = (
        create_default_parameter_registry().create_output_representation(
            parameter
        )
    )
    assert isinstance(
        representation.parameters[0], QgsProcessingParameterFileDestination
    )


@pytest.mark.parametrize(
    "source_kind", ["local", "ngw", "archive", "missing", "missing_first"]
)
@pytest.mark.parametrize("field_count", ["single", "multiple", 2])
@pytest.mark.parametrize("value", ["name", "", "name,other"])
def test_field_editor_requires_a_local_layer_parent(
    qgis_app, source_kind, field_count, value
):
    source = file_input({"layer_type": "vector", "dataset_count": "single"})
    if source_kind == "ngw":
        source = replace(
            source,
            parameter_type=InputParameterType.INTEGER,
            input_semantic=ToolInputSemantic(kind="ngw_resource_id"),
        )
    elif source_kind == "archive":
        source = replace(
            source,
            input_semantic=ToolInputSemantic(
                kind="layer",
                constraints={"layer_type": "vector"},
            ),
        )
    parameter = ToolInputParameter(
        name="field",
        parameter_type=InputParameterType.STRING,
        alias="Field",
        description="Source field name",
        required=False,
        choices=None,
        input_semantic=ToolInputSemantic(
            kind="field",
            constraints={"field_count": field_count},
            relations=[ToolSemanticRelation("fields", "source")],
        ),
    )
    inputs = [parameter] if source_kind == "missing" else [source, parameter]
    if source_kind == "missing_first":
        parameter.input_semantic.relations.insert(
            0, ToolSemanticRelation("fields", "missing")
        )
    registry = create_default_parameter_registry()
    representation = registry.create_input_representation(
        parameter, tool_inputs=inputs
    )
    expected_type = (
        QgsProcessingParameterField
        if source_kind == "local" and field_count == "single"
        else QgsProcessingParameterString
    )
    definition = representation.parameters[0]
    assert isinstance(definition, expected_type)
    assert definition.help() == "Source field name"
    assert parameter.input_semantic.kind == "field"

    tool = ToolboxTool(
        alias="Field tool",
        can_run=True,
        description="",
        help=None,
        id=1,
        is_dev=False,
        is_featured=False,
        is_free=True,
        is_new=False,
        inputs=inputs,
        outputs=[],
        name="field_tool",
        tag_ids=[],
        presets=[],
    )
    tasks_manager = Mock()
    tasks_manager.api.return_value.api_client.endpoint = (
        "https://toolbox.nextgis.com"
    )
    processing_algorithm = ToolboxAlgorithm(tool, tasks_manager, registry)
    processing_algorithm.initAlgorithm()
    assert isinstance(
        processing_algorithm.parameterDefinition("field"), expected_type
    )

    assert registry.resolve_input_value(
        parameter,
        processing_algorithm,
        {"field": value},
        QgsProcessingContext(),
    ) == (value or None)


def test_reviewed_catalog_preserves_proven_semantics(catalog):
    assert catalog["ngw_intersect"]["inputs"]["wkt"] == {
        "kind": "geometry",
        "constraints": {
            "geometry_format": "wkt",
            "crs_required": "EPSG:3857",
        },
    }
    for name in ("color", "strokeColor"):
        assert catalog["cadastre2img"]["inputs"][name] == {"kind": "color"}
    assert catalog["ngw_webmap2image"]["inputs"]["link"]["kind"] == "url"
    for name in ("webmap1", "webmap2"):
        assert catalog["ngw_webmap_combiner"]["inputs"][name][
            "constraints"
        ] == {"ngw_resource_types": ["webmap"]}
    assert catalog["import_glr"]["inputs"]["src"]["constraints"] == {
        "extensions": ["xml"]
    }
    assert catalog["panotag"]["inputs"]["photos"] == {"kind": "image"}
    panorama_result = catalog["panotag"]["outputs"]["photos_with_tags"]
    assert panorama_result["constraints"]["extensions"] == ["zip"]
    assert panorama_result["archive_contents"][0]["kind"] == "image"
    result = catalog["layerstack"]["outputs"]["result"]["constraints"]
    assert result["dataset_count"] == "single"
    assert result["drivers"] == ["GTiff"]
    assert "extensions" not in result


@pytest.mark.parametrize(
    "tool_name, parameter_name",
    [("check_geometries", "input_file"), ("layerstack", "raster_archive")],
)
def test_spatial_archive_semantics_do_not_force_single_layer_upload(
    qgis_app, catalog, tool_name, parameter_name
):
    semantic = catalog[tool_name]["inputs"][parameter_name]
    parameter = replace(
        file_input({}),
        input_semantic=ToolInputSemantic.from_json(semantic),
    )
    representation = (
        create_default_parameter_registry().create_input_representation(
            parameter
        )
    )
    assert isinstance(representation.parameters[0], QgsProcessingParameterFile)
    assert not isinstance(
        representation.parameters[0], QgsProcessingParameterFeatureSource
    )


def test_catalog_colors_use_color_editor(qgis_app, catalog):
    parameter = ToolInputParameter(
        name="color",
        parameter_type=InputParameterType.STRING,
        alias=None,
        description=None,
        required=False,
        choices=None,
        input_semantic=ToolInputSemantic.from_json(
            catalog["cadastre2img"]["inputs"]["color"]
        ),
    )
    representation = (
        create_default_parameter_registry().create_input_representation(
            parameter
        )
    )
    assert isinstance(
        representation.parameters[0], QgsProcessingParameterColor
    )


@pytest.mark.parametrize(
    "tool_name, side, parameter_name, expected",
    [
        ("add_regions", "inputs", "dataextract", ["polygon"]),
        ("crossing_borders", "inputs", "borders", ["polygon"]),
        ("grid", "inputs", "src", ["polygon"]),
        ("image_classification", "inputs", "src_file_vector", ["polygon"]),
        ("lesis2sqlite", "inputs", "areas_zip", ["polygon"]),
        ("polysimplifier", "inputs", "boundaries", ["line", "polygon"]),
        ("predict_overpass", "inputs", "aoi", ["polygon"]),
        ("split180", "inputs", "src", ["polygon"]),
        ("split180", "outputs", "result", ["polygon"]),
        ("split_to_rect", "inputs", "src_shape_file", ["polygon"]),
        ("split_to_rect", "outputs", "result_shape_file", ["polygon"]),
        ("splitcomplex", "inputs", "polygons", ["polygon"]),
        ("splitcomplex", "outputs", "result", ["polygon"]),
    ],
)
def test_catalog_geometry_families(
    catalog, tool_name, side, parameter_name, expected
):
    constraints = catalog[tool_name][side][parameter_name]["constraints"]
    assert constraints["layer_type"] == "vector"
    assert constraints["geometry_types"] == expected


@pytest.mark.parametrize(
    "tool_name, parameter_name",
    [
        ("grid", "src"),
        ("image_classification", "src_file_vector"),
        ("lesis2sqlite", "areas_zip"),
        ("split_to_rect", "src_shape_file"),
    ],
)
def test_polygon_catalog_inputs_filter_qgis_layer_types(
    qgis_app, catalog, tool_name, parameter_name
):
    semantic = catalog[tool_name]["inputs"][parameter_name]
    parameter = replace(
        file_input({}),
        input_semantic=ToolInputSemantic.from_json(semantic),
    )
    representation = (
        create_default_parameter_registry().create_input_representation(
            parameter
        )
    )
    definition = representation.parameters[0]
    assert isinstance(definition, QgsProcessingParameterFeatureSource)
    assert definition.dataTypes() == [ProcessingSourceType.VectorPolygon]


def test_archive_members_preserve_nested_metadata():
    payload = {
        "kind": "other",
        "constraints": {"extensions": ["zip"]},
        "archive_contents": [
            {
                "kind": "other",
                "member_pattern": "nested/*.zip",
                "archive_contents": [
                    {
                        "kind": "layer",
                        "constraints": {"drivers": ["GPKG"]},
                        "member_pattern": "*.gpkg",
                    }
                ],
            }
        ],
    }
    assert ToolOutputSemantic.from_json(payload).to_json() == payload


def test_single_dataset_archive_is_not_a_layer_destination(qgis_app):
    parameter = ToolOutputParameter(
        name="result",
        parameter_type=OutputParameterType.FILE,
        alias=None,
        description=None,
        required=True,
        output_semantic=ToolOutputSemantic(
            kind="layer",
            constraints={
                "layer_type": "vector",
                "dataset_count": "single",
                "extensions": ["zip"],
            },
            archive_contents=[ToolOutputSemantic(kind="layer")],
        ),
    )
    representation = (
        create_default_parameter_registry().create_output_representation(
            parameter
        )
    )
    definition = representation.parameters[0]
    assert isinstance(definition, QgsProcessingParameterFileDestination)
    assert definition.defaultFileExtension() == "zip"
