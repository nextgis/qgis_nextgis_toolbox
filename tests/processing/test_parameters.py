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

import importlib
from pathlib import Path
from unittest.mock import Mock

from qgis.core import (
    QgsProcessingContext,
    QgsProcessingParameterColor,
    QgsProcessingParameterCrs,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterFile,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorDestination,
)

from nextgis_toolbox.processing.parameters import (
    create_default_parameter_registry,
)
from nextgis_toolbox.processing.parameters.common import (
    apply_parameter_help,
)
from nextgis_toolbox.processing.parameters.resolvers import (
    AlgorithmOutputDestinationResolver,
    AlgorithmParameterResolver,
)
from nextgis_toolbox.tools.models import (
    InputParameterType,
    OutputParameterType,
    ToolInputParameter,
    ToolOutputParameter,
)
from nextgis_toolbox.tools.semantics import (
    ToolInputSemantic,
    ToolOutputSemantic,
    ToolSemanticRelation,
)


def test_input_parameter_label_prefers_alias_then_description_then_name() -> (
    None
):
    aliased_parameter = ToolInputParameter(
        name="source",
        parameter_type=InputParameterType.STRING,
        alias="Source alias",
        description="Source description",
        required=True,
        choices=None,
    )
    described_parameter = ToolInputParameter(
        name="source",
        parameter_type=InputParameterType.STRING,
        alias=None,
        description="Source description",
        required=True,
        choices=None,
    )
    unnamed_parameter = ToolInputParameter(
        name="source",
        parameter_type=InputParameterType.STRING,
        alias=None,
        description=None,
        required=True,
        choices=None,
    )

    assert aliased_parameter.label == "Source alias"
    assert described_parameter.label == "Source description"
    assert unnamed_parameter.label == "source"


def test_output_parameter_label_prefers_alias_then_name() -> None:
    aliased_parameter = ToolOutputParameter(
        name="result",
        parameter_type=OutputParameterType.FILE,
        alias="Result alias",
        description="Result description",
        required=False,
    )
    unnamed_parameter = ToolOutputParameter(
        name="result",
        parameter_type=OutputParameterType.FILE,
        alias=None,
        description="Result description",
        required=False,
    )

    assert aliased_parameter.label == "Result alias"
    assert unnamed_parameter.label == "result"


def test_apply_parameter_help_sets_help_text(qgis_app) -> None:
    del qgis_app

    parameter_definition = QgsProcessingParameterString("source", "Source")

    returned_definition = apply_parameter_help(
        parameter_definition,
        "Source help",
    )

    assert returned_definition is parameter_definition
    assert parameter_definition.help() == "Source help"


def test_ngw_connection_representation_expands_into_three_fields(
    qgis_app,
) -> None:
    del qgis_app

    parameter = ToolInputParameter(
        name="connection",
        parameter_type=InputParameterType.NGW_CONNECTION,
        alias="Connection",
        description=None,
        required=True,
        choices=None,
    )
    parameter_registry = create_default_parameter_registry()

    representation = parameter_registry.create_input_representation(parameter)

    assert [item.name() for item in representation.parameters] == [
        "connection_url",
        "connection_login",
        "connection_password",
    ]


def test_single_choice_runtime_resolution_returns_toolbox_value(
    qgis_app,
) -> None:
    del qgis_app

    parameter = ToolInputParameter(
        name="mode",
        parameter_type=InputParameterType.SINGLE_CHOICE,
        alias="Mode",
        description=None,
        required=True,
        choices=[
            {"alias": "First", "value": "a"},
            {"alias": "Second", "value": "b"},
        ],
    )
    algorithm = Mock()
    algorithm.parameterAsEnum.return_value = 1
    parameter_registry = create_default_parameter_registry()

    resolved_value = parameter_registry.resolve_input_value(
        parameter,
        algorithm,
        {},
        QgsProcessingContext(),
    )

    assert resolved_value == "b"


def test_ngw_connection_runtime_resolution_collects_split_fields(
    qgis_app,
) -> None:
    del qgis_app

    parameter = ToolInputParameter(
        name="connection",
        parameter_type=InputParameterType.NGW_CONNECTION,
        alias="Connection",
        description=None,
        required=True,
        choices=None,
    )
    values = {
        "connection_url": "https://demo.nextgis.com",
        "connection_login": "demo-user",
        "connection_password": "demo-pass",  # pragma: allowlist secret
    }
    algorithm = Mock()
    algorithm.parameterAsString.side_effect = (
        lambda parameters, name, context: values[name]
    )
    parameter_registry = create_default_parameter_registry()

    resolved_value = parameter_registry.resolve_input_value(
        parameter,
        algorithm,
        {},
        QgsProcessingContext(),
    )

    assert resolved_value == {
        "url": "https://demo.nextgis.com",
        "login": "demo-user",
        "password": "demo-pass",  # pragma: allowlist secret
    }


def test_file_output_representation_uses_destination_parameter(
    qgis_app,
) -> None:
    del qgis_app

    parameter = ToolOutputParameter(
        name="result",
        parameter_type=OutputParameterType.FILE,
        alias="Result",
        description=None,
        required=False,
    )
    parameter_registry = create_default_parameter_registry()

    representation = parameter_registry.create_output_representation(parameter)

    assert representation.outputs == []
    assert [item.name() for item in representation.parameters] == ["result"]
    assert representation.parameters[0].isDestination() is True


def test_algorithm_exposes_file_output_as_destination_parameter(
    qgis_app,
) -> None:
    del qgis_app

    algorithm_module = importlib.import_module(
        "nextgis_toolbox.processing.toolbox_algorithm"
    )
    models_module = importlib.import_module("nextgis_toolbox.tools.models")
    output_parameter = ToolOutputParameter(
        name="result",
        parameter_type=OutputParameterType.FILE,
        alias="Result",
        description=None,
        required=False,
    )
    tool = models_module.ToolboxTool(
        alias="Demo Tool",
        can_run=True,
        description="Description",
        help="<p>Docs</p>",
        id=1,
        is_dev=False,
        is_featured=False,
        is_free=True,
        is_new=False,
        inputs=[],
        outputs=[output_parameter],
        name="demo-tool",
        tag_ids=[],
        presets=[],
    )
    tasks_manager = Mock()
    tasks_manager.api.return_value.api_client.endpoint = (
        "https://toolbox.nextgis.com"
    )
    algorithm = algorithm_module.ToolboxAlgorithm(
        tool,
        tasks_manager,
        parameter_registry=create_default_parameter_registry(),
    )

    algorithm.initAlgorithm()

    assert [
        parameter.name()
        for parameter in algorithm.destinationParameterDefinitions()
    ] == ["result"]


def test_algorithm_parameter_resolver_uses_supplied_registry(
    qgis_app,
) -> None:
    del qgis_app

    parameter = ToolInputParameter(
        name="mode",
        parameter_type=InputParameterType.STRING,
        alias="Mode",
        description=None,
        required=True,
        choices=None,
    )
    algorithm = Mock()
    registry = Mock()
    registry.resolve_input_value.return_value = "resolved"
    parameters = {"mode": "raw"}
    context = QgsProcessingContext()

    resolver = AlgorithmParameterResolver(algorithm, registry)

    assert resolver(parameter, parameters, context) == "resolved"
    registry.resolve_input_value.assert_called_once_with(
        parameter,
        algorithm,
        parameters,
        context,
    )


def test_algorithm_output_destination_resolver_returns_file_path(
    qgis_app,
) -> None:
    del qgis_app

    parameter = ToolOutputParameter(
        name="result",
        parameter_type=OutputParameterType.FILE,
        alias="Result",
        description=None,
        required=False,
    )
    algorithm = Mock()
    algorithm.parameterAsFileOutput.return_value = "/tmp/result.gpkg"

    resolved_path = AlgorithmOutputDestinationResolver(algorithm)(
        parameter,
        {},
        QgsProcessingContext(),
    )

    assert resolved_path == Path("/tmp/result.gpkg")


def test_semantic_style_input_uses_qml_file_filter(qgis_app) -> None:
    del qgis_app

    parameter = ToolInputParameter(
        name="style",
        parameter_type=InputParameterType.FILE,
        alias="Style",
        description=None,
        required=False,
        choices=None,
        input_semantic=ToolInputSemantic(
            kind="style",
            constraints={"style_type": "qml"},
        ),
    )
    parameter_registry = create_default_parameter_registry()

    representation = parameter_registry.create_input_representation(parameter)

    assert isinstance(representation.parameters[0], QgsProcessingParameterFile)
    assert "*.qml" in representation.parameters[0].fileFilter()


def test_semantic_vector_input_uses_feature_source_parameter(
    qgis_app,
) -> None:
    del qgis_app

    parameter = ToolInputParameter(
        name="source",
        parameter_type=InputParameterType.FILE,
        alias="Source",
        description=None,
        required=True,
        choices=None,
        input_semantic=ToolInputSemantic(
            kind="layer",
            constraints={
                "layer_type": "vector",
                "geometry_types": ["polygon"],
                "dataset_count": "single",
            },
        ),
    )
    parameter_registry = create_default_parameter_registry()

    representation = parameter_registry.create_input_representation(parameter)

    assert isinstance(
        representation.parameters[0],
        QgsProcessingParameterFeatureSource,
    )


def test_semantic_vector_input_resolves_compatible_source_path(
    qgis_app,
) -> None:
    del qgis_app

    parameter = ToolInputParameter(
        name="source",
        parameter_type=InputParameterType.FILE,
        alias="Source",
        description=None,
        required=True,
        choices=None,
        input_semantic=ToolInputSemantic(
            kind="layer",
            constraints={
                "allow_conversion": True,
                "drivers": ["GPKG"],
                "dataset_count": "single",
                "layer_type": "vector",
            },
        ),
    )
    algorithm = Mock()
    algorithm.parameterAsCompatibleSourceLayerPath.return_value = (
        "/tmp/source.gpkg"
    )
    parameter_registry = create_default_parameter_registry()

    resolved_value = parameter_registry.resolve_input_value(
        parameter,
        algorithm,
        {},
        QgsProcessingContext(),
    )

    assert resolved_value == "/tmp/source.gpkg"
    algorithm.parameterAsCompatibleSourceLayerPath.assert_called_once()


def test_semantic_field_input_uses_field_parameter(qgis_app) -> None:
    del qgis_app

    parameter = ToolInputParameter(
        name="field_name",
        parameter_type=InputParameterType.STRING,
        alias="Field",
        description=None,
        required=True,
        choices=None,
        input_semantic=ToolInputSemantic(
            kind="field",
            constraints={"field_types": ["string"]},
            relations=[
                ToolSemanticRelation(
                    relation_type="fields",
                    source_parameter="source",
                )
            ],
        ),
    )
    parameter_registry = create_default_parameter_registry()

    representation = parameter_registry.create_input_representation(parameter)

    assert isinstance(
        representation.parameters[0], QgsProcessingParameterField
    )
    assert representation.parameters[0].parentLayerParameterName() == "source"


def test_semantic_crs_input_uses_crs_parameter(qgis_app) -> None:
    del qgis_app

    parameter = ToolInputParameter(
        name="crs_id",
        parameter_type=InputParameterType.STRING,
        alias="CRS",
        description=None,
        required=True,
        choices=None,
        input_semantic=ToolInputSemantic(kind="crs"),
    )
    parameter_registry = create_default_parameter_registry()

    representation = parameter_registry.create_input_representation(parameter)

    assert isinstance(representation.parameters[0], QgsProcessingParameterCrs)


def test_semantic_color_input_uses_color_parameter(qgis_app) -> None:
    del qgis_app

    parameter = ToolInputParameter(
        name="color",
        parameter_type=InputParameterType.STRING,
        alias="Color",
        description=None,
        required=True,
        choices=None,
        input_semantic=ToolInputSemantic(kind="color"),
    )
    parameter_registry = create_default_parameter_registry()

    representation = parameter_registry.create_input_representation(parameter)

    assert isinstance(
        representation.parameters[0],
        QgsProcessingParameterColor,
    )


def test_semantic_vector_output_uses_vector_destination_parameter(
    qgis_app,
) -> None:
    del qgis_app

    parameter = ToolOutputParameter(
        name="result",
        parameter_type=OutputParameterType.FILE,
        alias="Result",
        description=None,
        required=False,
        output_semantic=ToolOutputSemantic(
            kind="layer",
            constraints={
                "dataset_count": "single",
                "geometry_types": ["polygon"],
                "layer_type": "vector",
            },
        ),
    )
    parameter_registry = create_default_parameter_registry()

    representation = parameter_registry.create_output_representation(parameter)

    assert isinstance(
        representation.parameters[0],
        QgsProcessingParameterVectorDestination,
    )


def test_semantic_raster_output_uses_raster_destination_parameter(
    qgis_app,
) -> None:
    del qgis_app

    parameter = ToolOutputParameter(
        name="result",
        parameter_type=OutputParameterType.FILE,
        alias="Result",
        description=None,
        required=False,
        output_semantic=ToolOutputSemantic(
            kind="layer",
            constraints={
                "dataset_count": "single",
                "layer_type": "raster",
            },
        ),
    )
    parameter_registry = create_default_parameter_registry()

    representation = parameter_registry.create_output_representation(parameter)

    assert isinstance(
        representation.parameters[0],
        QgsProcessingParameterRasterDestination,
    )


def test_semantic_table_output_uses_file_filter(qgis_app) -> None:
    del qgis_app

    parameter = ToolOutputParameter(
        name="result",
        parameter_type=OutputParameterType.FILE,
        alias="Result",
        description=None,
        required=False,
        output_semantic=ToolOutputSemantic(
            kind="table",
            constraints={
                "extensions": ["csv"],
                "dataset_count": "single",
            },
        ),
    )
    parameter_registry = create_default_parameter_registry()

    representation = parameter_registry.create_output_representation(parameter)

    assert isinstance(
        representation.parameters[0],
        QgsProcessingParameterFileDestination,
    )
    assert "*.csv" in representation.parameters[0].fileFilter()
