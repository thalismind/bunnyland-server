"""Load reusable ECS patch fragments for editors and DM prompts."""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any

from pydantic import BaseModel, Field


class FragmentEdge(BaseModel):
    type: str
    fields: dict[str, Any] = Field(default_factory=dict)


class ContentFragment(BaseModel):
    schema_version: int = 1
    id: str
    title: str
    kind: str
    description: str = ""
    tags: tuple[str, ...] = ()
    root_client_id: str | None = None
    attach_edge: FragmentEdge | None = None
    operations: list[dict[str, Any]] = Field(default_factory=list)


class ContentLibrary(BaseModel):
    schema_version: int = 1
    library_id: str
    title: str
    description: str = ""
    fragments: list[ContentFragment] = Field(default_factory=list)


@cache
def load_content_library() -> ContentLibrary:
    """Return the bundled base fragment library."""

    path = resources.files("bunnyland.content.fragments").joinpath("base.json")
    return ContentLibrary.model_validate(json.loads(path.read_text()))


def content_library_context() -> str:
    """Return compact fragment examples for DM prompts."""

    library = load_content_library()
    payload = {
        "library_id": library.library_id,
        "fragments": [
            {
                "id": fragment.id,
                "title": fragment.title,
                "kind": fragment.kind,
                "tags": list(fragment.tags),
                "components": [
                    component.get("type")
                    for operation in fragment.operations
                    if operation.get("op") == "add_entity"
                    for component in operation.get("components", [])
                    if component.get("type")
                ],
            }
            for fragment in library.fragments
        ],
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


__all__ = [
    "ContentFragment",
    "ContentLibrary",
    "content_library_context",
    "load_content_library",
]
