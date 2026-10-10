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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from nextgis_toolbox.core.logging import logger


@dataclass(frozen=True)
class ToolSemanticRelation:
    relation_type: str
    source_parameter: str

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "ToolSemanticRelation":
        return cls(
            relation_type=data["type"],
            source_parameter=data["source_parameter"],
        )

    def to_json(self) -> Dict[str, Any]:
        return {
            "type": self.relation_type,
            "source_parameter": self.source_parameter,
        }


@dataclass(frozen=True)
class ToolInputSemantic:
    kind: str
    constraints: Dict[str, Any] = field(default_factory=dict)
    relations: List[ToolSemanticRelation] = field(default_factory=list)
    validators: List[str] = field(default_factory=list)
    additional_data: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "ToolInputSemantic":
        return cls(
            kind=data["kind"],
            constraints=dict(data.get("constraints", {})),
            relations=[
                ToolSemanticRelation.from_json(item)
                for item in data.get("relations", [])
            ],
            validators=list(data.get("validators", [])),
            additional_data={
                key: value
                for key, value in data.items()
                if key
                not in {
                    "kind",
                    "constraints",
                    "relations",
                    "validators",
                }
            },
        )

    def to_json(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"kind": self.kind}
        if self.constraints:
            payload["constraints"] = self.constraints
        if self.relations:
            payload["relations"] = [
                relation.to_json() for relation in self.relations
            ]
        if self.validators:
            payload["validators"] = list(self.validators)
        payload.update(self.additional_data)
        return payload


@dataclass(frozen=True)
class ToolOutputSemantic:
    """Describe a result artifact and preserve its logical archive contents."""

    kind: str
    constraints: Dict[str, Any] = field(default_factory=dict)
    additional_data: Dict[str, Any] = field(default_factory=dict)
    archive_contents: List["ToolOutputSemantic"] = field(default_factory=list)

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "ToolOutputSemantic":
        return cls(
            kind=data["kind"],
            constraints=dict(data.get("constraints", {})),
            additional_data={
                key: value
                for key, value in data.items()
                if key not in {"kind", "constraints", "archive_contents"}
            },
            archive_contents=[
                cls.from_json(member)
                for member in data.get("archive_contents", [])
            ],
        )

    def to_json(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"kind": self.kind}
        if self.constraints:
            payload["constraints"] = self.constraints
        if self.archive_contents:
            payload["archive_contents"] = [
                member.to_json() for member in self.archive_contents
            ]
        payload.update(self.additional_data)
        return payload


class ToolSemanticsCatalog:
    """Semantic-only overlays keyed by tool and parameter names."""

    def __init__(
        self,
        overlays: Optional[Dict[str, Any]] = None,
        *,
        resource_path: Optional[Path] = None,
    ) -> None:
        self._overlays = overlays
        self._resource_path = resource_path or self.default_resource_path()

    @staticmethod
    def default_resource_path() -> Path:
        return (
            Path(__file__).resolve().parents[1]
            / "resources"
            / "tool_semantics.json"
        )

    def enrich_tool_data(self, tool_data: Dict[str, Any]) -> Dict[str, Any]:
        tool_name = tool_data.get("name")
        if not isinstance(tool_name, str):
            return dict(tool_data)
        overlays = self._load_overlays()
        overlay = overlays.get(tool_name)
        if not isinstance(overlay, dict):
            return dict(tool_data)

        overlay_inputs = overlay.get("inputs", {})
        overlay_outputs = overlay.get("outputs", {})

        enriched = dict(tool_data)
        enriched["inputs"] = [
            self._merge_input_parameter(parameter_data, overlay_inputs)
            for parameter_data in tool_data.get("inputs", [])
        ]
        enriched["outputs"] = [
            self._merge_output_parameter(parameter_data, overlay_outputs)
            for parameter_data in tool_data.get("outputs", [])
        ]
        return enriched

    def _merge_input_parameter(
        self,
        parameter_data: Dict[str, Any],
        overlay_inputs: Any,
    ) -> Dict[str, Any]:
        enriched_parameter = dict(parameter_data)
        if not isinstance(overlay_inputs, dict):
            return enriched_parameter

        semantic = overlay_inputs.get(parameter_data.get("name"))
        if isinstance(semantic, dict):
            enriched_parameter["input_semantic"] = semantic

        return enriched_parameter

    def _merge_output_parameter(
        self,
        parameter_data: Dict[str, Any],
        overlay_outputs: Any,
    ) -> Dict[str, Any]:
        enriched_parameter = dict(parameter_data)
        if not isinstance(overlay_outputs, dict):
            return enriched_parameter

        semantic = overlay_outputs.get(parameter_data.get("name"))
        if isinstance(semantic, dict):
            enriched_parameter["output_semantic"] = semantic

        return enriched_parameter

    def _load_overlays(self) -> Dict[str, Any]:
        if self._overlays is not None:
            return self._overlays

        if not self._resource_path.exists():
            logger.warning(
                "Tool semantics resource is unavailable: "
                f"{self._resource_path}"
            )
            self._overlays = {}
            return self._overlays

        self._overlays = json.loads(self._resource_path.read_text("utf-8"))
        return self._overlays
