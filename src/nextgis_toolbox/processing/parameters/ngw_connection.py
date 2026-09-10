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
from typing import TYPE_CHECKING, Any, Dict, Optional, Union

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingParameterString,
)
from qgis.PyQt.QtCore import QCoreApplication

from nextgis_toolbox.processing.parameters.common import (
    InputParameterAdapter,
    InputParameterRepresentation,
    PresetPreparationContext,
)
from nextgis_toolbox.tools.models import (
    InputParameterType,
    ToolInputParameter,
)

if TYPE_CHECKING:
    from nextgis_toolbox.processing.parameters.registry import (
        InputParameterAdapterRegistry,
    )

NGW_URL_SUFFIX = "_url"
NGW_LOGIN_SUFFIX = "_login"
NGW_PASSWORD_SUFFIX = "_password"  # nosec B105  # pragma: allowlist secret


@dataclass(frozen=True)
class NgwConnectionFields:
    url_name: str
    login_name: str
    password_name: str

    @classmethod
    def from_parameter_name(cls, name: str) -> "NgwConnectionFields":
        return cls(
            f"{name}{NGW_URL_SUFFIX}",
            f"{name}{NGW_LOGIN_SUFFIX}",
            f"{name}{NGW_PASSWORD_SUFFIX}",
        )


class SplitNgwConnectionInputAdapter(InputParameterAdapter):
    def create_representation(
        self,
        parameter: ToolInputParameter,
    ) -> InputParameterRepresentation:
        optional = not parameter.required
        fields = NgwConnectionFields.from_parameter_name(parameter.name)

        url_param = QgsProcessingParameterString(
            fields.url_name,
            QCoreApplication.translate(
                "ToolboxAlgorithm",
                "Web GIS URL",
            ),
            optional=optional,
        )
        url_param.setHelp(
            QCoreApplication.translate(
                "ToolboxAlgorithm",
                "Web GIS address, e.g. https://demo.nextgis.com.",
            )
        )

        login_param = QgsProcessingParameterString(
            fields.login_name,
            QCoreApplication.translate(
                "ToolboxAlgorithm",
                "Web GIS login",
            ),
            optional=True,
        )
        login_param.setHelp(
            QCoreApplication.translate(
                "ToolboxAlgorithm",
                "Username for the Web GIS (leave empty if public).",
            )
        )

        password_param = QgsProcessingParameterString(
            fields.password_name,
            QCoreApplication.translate(
                "ToolboxAlgorithm",
                "Web GIS password",
            ),
            optional=True,
        )
        password_param.setHelp(
            QCoreApplication.translate(
                "ToolboxAlgorithm",
                "Password for the Web GIS (leave empty if public).",
            )
        )

        return InputParameterRepresentation(
            parameters=[url_param, login_param, password_param]
        )

    def prepare_preset_values(
        self,
        parameter: ToolInputParameter,
        value: Union[str, Dict[str, str]],
        preset_context: PresetPreparationContext,
    ) -> Dict[str, Any]:
        del preset_context
        fields = NgwConnectionFields.from_parameter_name(parameter.name)
        if isinstance(value, str):
            return {fields.url_name: value}

        if not isinstance(value, dict):
            return {}

        return {
            fields.url_name: value.get("url", ""),
            fields.login_name: value.get("login", ""),
            fields.password_name: value.get("password", ""),
        }

    def resolve_runtime_value(
        self,
        parameter: ToolInputParameter,
        algorithm: QgsProcessingAlgorithm,
        parameters: Dict[Optional[str], Any],
        context: QgsProcessingContext,
    ) -> Optional[Dict[str, Optional[str]]]:
        fields = NgwConnectionFields.from_parameter_name(parameter.name)

        url = (
            algorithm.parameterAsString(
                parameters,
                fields.url_name,
                context,
            )
            or None
        )
        if url is None:
            return None

        login = (
            algorithm.parameterAsString(
                parameters,
                fields.login_name,
                context,
            )
            or None
        )
        password = (
            algorithm.parameterAsString(
                parameters,
                fields.password_name,
                context,
            )
            or None
        )
        result = {"url": url, "login": login, "password": password}
        return result


class NgwConnectionInputAdapterFactory:
    def register_defaults(
        self, registry: "InputParameterAdapterRegistry"
    ) -> None:
        registry.register(
            InputParameterType.NGW_CONNECTION,
            self.create(),
        )

    def create(self) -> SplitNgwConnectionInputAdapter:
        return SplitNgwConnectionInputAdapter()
