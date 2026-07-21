"""Backward-compatibility checks for the frozen v1 transport contract."""

from __future__ import annotations

from pydantic import JsonValue


class ContractCompatibilityError(AssertionError):
    """A current contract no longer accepts or returns a baseline v1 shape."""


def _fail(path: str, detail: str) -> None:
    raise ContractCompatibilityError(f"{path}: {detail}")


JsonObject = dict[str, JsonValue]


def _types(schema: JsonObject) -> set[str]:
    value = schema.get("type")
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {str(item) for item in value}
    return set()


def _resolve(schema: JsonObject, root: JsonObject) -> JsonObject:
    reference = schema.get("$ref")
    if not isinstance(reference, str) or not reference.startswith("#/"):
        return schema
    current: JsonValue = dict(root)
    for token in reference[2:].split("/"):
        current = current[token.replace("~1", "/").replace("~0", "~")]
    if not isinstance(current, dict):
        raise ContractCompatibilityError(f"{reference}: reference is not a schema")
    return current


def assert_schema_compatible(
    baseline: JsonObject,
    current: JsonObject,
    *,
    baseline_root: JsonObject | None = None,
    current_root: JsonObject | None = None,
    path: str = "$",
) -> None:
    """Reject field removal, new requirements, narrowed values, and tighter bounds."""

    baseline_root = baseline if baseline_root is None else baseline_root
    current_root = current if current_root is None else current_root
    old_reference = baseline.get("$ref")
    new_reference = current.get("$ref")
    if (
        isinstance(old_reference, str)
        and isinstance(new_reference, str)
        and old_reference.rsplit("/", 1)[-1] == new_reference.rsplit("/", 1)[-1]
    ):
        return
    baseline = _resolve(baseline, baseline_root)
    current = _resolve(current, current_root)

    for union_key in ("anyOf", "oneOf"):
        old_options = baseline.get(union_key)
        if isinstance(old_options, list):
            new_options = current.get(union_key)
            if not isinstance(new_options, list):
                _fail(path, f"removed {union_key}")
            for index, old_option in enumerate(old_options):
                for new_option in new_options:
                    try:
                        assert_schema_compatible(
                            old_option,
                            new_option,
                            baseline_root=baseline_root,
                            current_root=current_root,
                            path=f"{path}.{union_key}[{index}]",
                        )
                        break
                    except ContractCompatibilityError:
                        pass
                else:
                    _fail(path, f"no compatible current branch for {union_key}[{index}]")
            return

    old_types = _types(baseline)
    new_types = _types(current)
    if old_types and (not new_types or not old_types <= new_types):
        _fail(path, f"type narrowed from {sorted(old_types)} to {sorted(new_types)}")

    old_enum = baseline.get("enum")
    new_enum = current.get("enum")
    if isinstance(old_enum, list):
        if not isinstance(new_enum, list) or not set(old_enum) <= set(new_enum):
            _fail(path, "enum values were removed")
    if "const" in baseline and baseline.get("const") != current.get("const"):
        _fail(path, "const value changed")

    old_required = set(baseline.get("required", []))
    new_required = set(current.get("required", []))
    if not new_required <= old_required:
        _fail(path, f"new required fields: {sorted(new_required - old_required)}")

    old_properties = baseline.get("properties", {})
    new_properties = current.get("properties", {})
    if isinstance(old_properties, dict):
        if not isinstance(new_properties, dict):
            _fail(path, "object properties were removed")
        for name, old_property in old_properties.items():
            if name not in new_properties:
                _fail(path, f"field {name!r} was removed or renamed")
            assert_schema_compatible(
                old_property,
                new_properties[name],
                baseline_root=baseline_root,
                current_root=current_root,
                path=f"{path}.{name}",
            )

    if isinstance(baseline.get("items"), dict):
        if not isinstance(current.get("items"), dict):
            _fail(path, "array item schema was removed")
        assert_schema_compatible(
            baseline["items"],
            current["items"],
            baseline_root=baseline_root,
            current_root=current_root,
            path=f"{path}[]",
        )

    for lower in ("minimum", "exclusiveMinimum", "minLength", "minItems"):
        old_value = baseline.get(lower)
        new_value = current.get(lower)
        if old_value is None and new_value is not None:
            _fail(path, f"added {lower}")
        if old_value is not None and new_value is not None and new_value > old_value:
            _fail(path, f"tightened {lower}")
    for upper in ("maximum", "exclusiveMaximum", "maxLength", "maxItems"):
        old_value = baseline.get(upper)
        new_value = current.get(upper)
        if old_value is None and new_value is not None:
            _fail(path, f"added {upper}")
        if old_value is not None and new_value is not None and new_value < old_value:
            _fail(path, f"tightened {upper}")
    for constraint in ("format", "pattern"):
        old_value = baseline.get(constraint)
        new_value = current.get(constraint)
        if new_value is not None and new_value != old_value:
            _fail(path, f"added or changed {constraint}")


def _content_schemas(content: JsonValue) -> list[JsonObject]:
    if not isinstance(content, dict):
        return []
    schemas = []
    for media in content.values():
        if isinstance(media, dict) and isinstance(media.get("schema"), dict):
            schemas.append(media["schema"])
    return schemas


def assert_openapi_compatible(
    baseline: JsonObject, current: JsonObject
) -> None:
    """Check the stable HTTP operations and their request/response schemas."""

    baseline_paths = baseline.get("paths", {})
    current_paths = current.get("paths", {})
    for route, old_path in baseline_paths.items():
        if route not in current_paths:
            _fail(route, "route was removed")
        new_path = current_paths[route]
        for method, old_operation in old_path.items():
            if method.startswith("x-") or method == "parameters":
                continue
            if method not in new_path:
                _fail(f"{method.upper()} {route}", "operation was removed")
            new_operation = new_path[method]
            operation_path = f"{method.upper()} {route}"
            if old_operation.get("security") != new_operation.get("security"):
                _fail(operation_path, "authorization declaration changed")

            old_parameters = {
                (item.get("in"), item.get("name")): item
                for item in old_operation.get("parameters", [])
            }
            new_parameters = {
                (item.get("in"), item.get("name")): item
                for item in new_operation.get("parameters", [])
            }
            for key, old_parameter in old_parameters.items():
                if key not in new_parameters:
                    _fail(operation_path, f"parameter {key!r} was removed or renamed")
                new_parameter = new_parameters[key]
                if old_parameter.get("required") and not new_parameter.get("required"):
                    continue
                assert_schema_compatible(
                    old_parameter.get("schema", {}),
                    new_parameter.get("schema", {}),
                    baseline_root=baseline,
                    current_root=current,
                    path=f"{operation_path} parameter {key!r}",
                )
            for key, new_parameter in new_parameters.items():
                if key not in old_parameters and new_parameter.get("required"):
                    _fail(operation_path, f"new required parameter {key!r}")

            old_body = old_operation.get("requestBody")
            new_body = new_operation.get("requestBody")
            if isinstance(old_body, dict):
                if not isinstance(new_body, dict):
                    _fail(operation_path, "request body was removed")
                for index, old_schema in enumerate(_content_schemas(old_body.get("content"))):
                    new_schemas = _content_schemas(new_body.get("content"))
                    if index >= len(new_schemas):
                        _fail(operation_path, "request media type was removed")
                    assert_schema_compatible(
                        old_schema,
                        new_schemas[index],
                        baseline_root=baseline,
                        current_root=current,
                        path=f"{operation_path} request",
                    )
            elif isinstance(new_body, dict) and new_body.get("required"):
                _fail(operation_path, "new required request body")

            old_responses = old_operation.get("responses", {})
            new_responses = new_operation.get("responses", {})
            for status, old_response in old_responses.items():
                if status not in new_responses:
                    _fail(operation_path, f"response {status} was removed")
                old_schemas = _content_schemas(old_response.get("content"))
                new_schemas = _content_schemas(new_responses[status].get("content"))
                for index, old_schema in enumerate(old_schemas):
                    if index >= len(new_schemas):
                        _fail(operation_path, f"response {status} media type was removed")
                    assert_schema_compatible(
                        old_schema,
                        new_schemas[index],
                        baseline_root=baseline,
                        current_root=current,
                        path=f"{operation_path} response {status}",
                    )


__all__ = [
    "ContractCompatibilityError",
    "assert_openapi_compatible",
    "assert_schema_compatible",
]
