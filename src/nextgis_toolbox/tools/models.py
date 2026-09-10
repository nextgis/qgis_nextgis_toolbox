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

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from nextgis_toolbox.core.utils import nextgis_domain
from nextgis_toolbox.tools.semantics import (
    ToolInputSemantic,
    ToolOutputSemantic,
)


class SortBy(str, Enum):
    ID = "id"
    NAME = "name"
    ALIAS = "alias"

    def __str__(self) -> str:
        return self.value


class ToolsManagerState(str, Enum):
    INITIALIZATION = "initializing"
    LOADING = "loading"
    LOADED = "loaded"
    ERROR = "error"
    UNLOADED = "unloaded"

    def __str__(self) -> str:
        return self.value


@dataclass
class ToolboxTag:
    """Descriptor of a NextGIS Toolbox tag."""

    id: int
    alias: str
    icon: str
    tool_ids: List[int]

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "ToolboxTag":
        """Build a tag model from a JSON payload."""
        return cls(
            id=data["id"],
            alias=data["alias"],
            icon=data["icon"],
            tool_ids=data.get("tools", []),
        )

    def to_json(self) -> Dict[str, Any]:
        """Serialize the tag model to a JSON-compatible payload."""
        return {
            "id": self.id,
            "alias": self.alias,
            "icon": self.icon,
            "tools": self.tool_ids,
        }


@dataclass
class ToolboxTool:
    """Descriptor of a NextGIS Toolbox tool."""

    id: int
    name: str
    alias: str
    description: str
    is_dev: bool
    is_free: bool
    is_new: bool
    is_featured: bool
    can_run: bool
    tag_ids: List[int]
    tags: List[ToolboxTag] = field(default_factory=list)
    inputs: List["ToolInputParameter"] = field(default_factory=list)
    outputs: List["ToolOutputParameter"] = field(default_factory=list)
    presets: List["ToolPreset"] = field(default_factory=list)
    help: Optional[str] = None
    is_favorite: bool = False

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "ToolboxTool":
        """Build a tool model from a JSON payload."""
        return cls(
            id=data["id"],
            name=data["name"],
            alias=data["alias"],
            description=data["description"],
            is_dev=data["is_dev"],
            is_free=data["is_free"],
            is_new=data["is_new"],
            is_featured=data["is_featured"],
            can_run=data["can_run"],
            tag_ids=data.get("tags", []),
            inputs=[
                ToolInputParameter.from_json(parameter_data)
                for parameter_data in data.get("inputs", [])
            ],
            outputs=[
                ToolOutputParameter.from_json(parameter_data)
                for parameter_data in data.get("outputs", [])
            ],
            presets=[
                ToolPreset.from_json(preset_data)
                for preset_data in data.get("presets", [])
            ],
            help=data.get("docs"),
            is_favorite=data.get("is_favorite", False),
        )

    def to_json(self) -> Dict[str, Any]:
        """Serialize the tool model to a JSON-compatible payload."""
        tag_ids = self.tag_ids or [tag.id for tag in self.tags]

        return {
            "id": self.id,
            "name": self.name,
            "alias": self.alias,
            "description": self.description,
            "is_dev": self.is_dev,
            "is_free": self.is_free,
            "is_new": self.is_new,
            "is_featured": self.is_featured,
            "can_run": self.can_run,
            "tags": tag_ids,
            "inputs": [parameter.to_json() for parameter in self.inputs],
            "outputs": [parameter.to_json() for parameter in self.outputs],
            "presets": [preset.to_json() for preset in self.presets],
            "docs": self.help,
            "is_favorite": self.is_favorite,
        }

    def demo_preset(self) -> Optional["ToolPreset"]:
        if not self.presets:
            return None

        return self.presets[0]

    def web_url(self, base_url: str) -> str:
        """Construct a URL to the tool's page in NextGIS Web."""
        return urljoin(base_url, f"/t/{self.name}")

    def help_url(self) -> str:
        """Construct a URL to the tool's help page in NextGIS Web."""
        return urljoin(
            nextgis_domain("docs"),
            f"/docs_toolbox/source/{self.name}.html",
        )


class InputParameterType(Enum):
    STRING = "string"
    INTEGER = "int"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DATE = "date"
    BBOX = "bbox"
    FILE = "file"
    JSON = "json"
    SINGLE_CHOICE = "single_choice"
    MULTIPLE_CHOICE = "multiple_choice"
    NGW_CONNECTION = "ngw_connection"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def from_json(cls, name: str) -> "InputParameterType":
        return cls(name)

    def to_json(self) -> str:
        return self.value


class OutputParameterType(Enum):
    STRING = "string"
    INTEGER = "int"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DATE = "date"
    BBOX = "bbox"
    FILE = "file"
    JSON = "json"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def from_json(cls, name: str) -> "OutputParameterType":
        return cls(name)

    def to_json(self) -> str:
        return self.value


@dataclass(frozen=True)
class ToolInputParameter:
    """Immutable descriptor of a Toolbox input parameter."""

    name: str
    parameter_type: InputParameterType
    alias: Optional[str]
    description: Optional[str]
    required: bool
    choices: Optional[List[Dict[str, Any]]]
    input_semantic: Optional[ToolInputSemantic] = None

    @property
    def label(self) -> str:
        return self.alias or self.description or self.name

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "ToolInputParameter":
        """Build a parameter model from a JSON payload."""
        return cls(
            name=data["name"],
            parameter_type=InputParameterType.from_json(data["type"]),
            alias=data.get("alias"),
            description=data.get("description"),
            required=data.get("required", False),
            choices=data.get("choices"),
            input_semantic=(
                ToolInputSemantic.from_json(data["input_semantic"])
                if isinstance(data.get("input_semantic"), dict)
                else None
            ),
        )

    def to_json(self) -> Dict[str, Any]:
        """Serialize the parameter model to a JSON-compatible payload."""
        payload = {
            "name": self.name,
            "type": self.parameter_type,
            "alias": self.alias,
            "description": self.description,
            "required": self.required,
            "choices": self.choices,
        }
        if self.input_semantic is not None:
            payload["input_semantic"] = self.input_semantic.to_json()

        return payload


@dataclass(frozen=True)
class ToolOutputParameter:
    """Immutable descriptor of a Toolbox input or output parameter."""

    name: str
    parameter_type: OutputParameterType
    alias: Optional[str]
    description: Optional[str]
    required: bool
    output_semantic: Optional[ToolOutputSemantic] = None

    @property
    def label(self) -> str:
        return self.alias or self.name

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "ToolOutputParameter":
        """Build a parameter model from a JSON payload."""
        return cls(
            name=data["name"],
            parameter_type=OutputParameterType.from_json(data["type"]),
            alias=data.get("alias"),
            description=data.get("description"),
            required=data.get("required", False),
            output_semantic=(
                ToolOutputSemantic.from_json(data["output_semantic"])
                if isinstance(data.get("output_semantic"), dict)
                else None
            ),
        )

    def to_json(self) -> Dict[str, Any]:
        """Serialize the parameter model to a JSON-compatible payload."""
        payload = {
            "name": self.name,
            "type": self.parameter_type.to_json(),
            "alias": self.alias,
            "description": self.description,
            "required": self.required,
        }
        if self.output_semantic is not None:
            payload["output_semantic"] = self.output_semantic.to_json()

        return payload


@dataclass(frozen=True)
class ToolPreset:
    alias: str
    inputs: Dict[str, Any]
    outputs: Dict[str, Any]

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "ToolPreset":
        return cls(
            alias=data["alias"],
            inputs=data.get("inputs", {}),
            outputs=data.get("outputs", {}),
        )

    def to_json(self) -> Dict[str, Any]:
        return {
            "alias": self.alias,
            "inputs": self.inputs,
            "outputs": self.outputs,
        }
