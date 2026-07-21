# Bunnyland 1.x Compatibility Policy

Bunnyland 1.x packages support CPython 3.12, 3.13, and 3.14. The hosted service uses the
same Bunnyland release but deliberately runs the container's Python 3.12 baseline; package
support does not imply that production runs all three interpreters. Release-candidate
versions may refine the v1 surface before `1.0.0`; the guarantees below begin with the
final `1.0.0` release.

## Stable transport surface

The stable HTTP surface is every route under `/v1` recorded in
`contracts/http-v1-routes.json`. Its OpenAPI and JSON Schema baselines are
`contracts/openapi-v1.json` and `contracts/json-schema-v1.json`. The stable MCP tools are
recorded in `contracts/mcp-v1-tools.json`.

During 1.x, transport changes may add optional fields, enum values, routes, tools, or
response variants. A 1.x release must not:

- remove or rename a route, tool, field, parameter, or response;
- remove an enum value or narrow a field's accepted type or bounds;
- make an optional field, parameter, or request body required;
- weaken or change a route's authorization surface;
- expose raw ECS component maps, relationship maps, private memory, or controller context
  through a projection.

Breaking transport changes require a `/v2` route or v2 MCP tool surface. The automated
contract tests compare current schemas with the checked-in v1 baseline and permit additive
changes while rejecting the breaking cases above.

## Stable Python surface

The following imports are supported throughout 1.x:

- `bunnyland.__version__`;
- plugin contracts and discovery exported by `bunnyland.plugins`;
- action definitions, command types, mutation-plan operations, perspective-query types,
  ECS helpers, and `WorldActor` exported by `bunnyland.core`;
- v1 request and resource DTOs exported by `bunnyland.server.v1_models`;
- the documented `bunnyland` CLI commands and plugin entry-point group.

An import shown in a player, administrator, or developer guide is also supported when that
guide explicitly presents it as an integration API. All other modules, deep imports, and
attributes are internal implementation details even though Python can import them. Adding
an item to `__all__` alone does not make it stable; it must belong to one of the documented
categories above.

Additive methods and fields may appear in 1.x. Removing a documented import, narrowing its
accepted values, or changing an async contract requires 2.x. Plugin-owned command payloads
and event extensions remain extensible JSON values, but their stable event header and
ownership rules do not change during 1.x.

## Persisted worlds

Every 1.x release must import schema-v1, schema-v2, schema-v3, and schema-v4 JSON and YAML
worlds. Migration is one-way in memory; loading an old save does not rewrite it, and the
next explicit save writes the current schema. `tests/fixtures/migrations/` is the checked-in
golden corpus. Package CI runs that corpus using the newly installed wheel and source
distribution, so a source-tree fallback cannot hide a broken release artifact.

Support for a future schema-v5 may be added during 1.x only if schema-v1 through schema-v4
imports remain intact. Removing an old migration requires 2.x.
