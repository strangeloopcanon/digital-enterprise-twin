"""Scaffold a VEI BlueprintAsset from an OpenAPI specification.

Reads a JSON or YAML OpenAPI spec and produces:
- A skeleton BlueprintAsset with capability graph entries per endpoint
- Pydantic model stubs for request/response schemas
- Router handler stubs that can be filled in with business logic

The output is a *starting point* — the user fills in causal links and
cross-surface effects.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from vei.blueprint.models import (
    BlueprintAsset,
    BlueprintCapabilityGraphsAsset,
    BlueprintWorkGraphAsset,
    BlueprintTicketAsset,
)


def scaffold_from_openapi(
    spec_path: str | Path,
    *,
    service_name: str | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Generate a VEI scaffold from an OpenAPI spec.

    Returns a dict with keys:
    - "blueprint_asset": BlueprintAsset (serializable)
    - "router_stubs": str (Python source for router handlers)
    - "model_stubs": str (Pydantic model source)
    - "files_written": list[str] (paths if output_dir was provided)
    """
    spec = _load_spec(Path(spec_path))
    resolved_name = service_name or _infer_name(spec)
    slug = _slug(resolved_name)

    endpoints = _extract_endpoints(spec)
    schemas = _extract_schemas(spec)

    asset = _build_blueprint_asset(resolved_name, slug, endpoints, schemas)
    model_source = _generate_model_stubs(slug, schemas)
    router_source = _generate_router_stubs(slug, resolved_name, endpoints)

    files_written: list[str] = []
    if output_dir is not None:
        out = Path(output_dir).expanduser().resolve()
        out.mkdir(parents=True, exist_ok=True)

        asset_path = out / f"{slug}_blueprint.json"
        asset_path.write_text(
            json.dumps(asset.model_dump(mode="json"), indent=2),
            encoding="utf-8",
        )
        files_written.append(str(asset_path))

        models_path = out / f"{slug}_models.py"
        models_path.write_text(model_source, encoding="utf-8")
        files_written.append(str(models_path))

        router_path = out / f"{slug}_router.py"
        router_path.write_text(router_source, encoding="utf-8")
        files_written.append(str(router_path))

    return {
        "blueprint_asset": asset,
        "router_stubs": router_source,
        "model_stubs": model_source,
        "files_written": files_written,
    }


# ---------------------------------------------------------------------------
# Spec parsing
# ---------------------------------------------------------------------------


def _load_spec(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore[import-untyped]

            return yaml.safe_load(text)
        except ImportError:
            pass
    return json.loads(text)


def _infer_name(spec: dict[str, Any]) -> str:
    info = spec.get("info", {})
    return str(info.get("title", "custom_service"))


def _extract_endpoints(spec: dict[str, Any]) -> list[dict[str, Any]]:
    endpoints: list[dict[str, Any]] = []
    paths = spec.get("paths", {})
    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method, operation in methods.items():
            if method.lower() in ("get", "post", "put", "patch", "delete"):
                if not isinstance(operation, dict):
                    continue
                op_id = operation.get(
                    "operationId",
                    f"{method.lower()}_{_path_to_snake(path)}",
                )
                endpoints.append(
                    {
                        "path": path,
                        "method": method.upper(),
                        "operation_id": _sanitize_id(op_id),
                        "summary": operation.get("summary", ""),
                        "description": operation.get("description", ""),
                        "parameters": operation.get("parameters", []),
                        "request_body": operation.get("requestBody"),
                        "responses": operation.get("responses", {}),
                        "tags": operation.get("tags", []),
                    }
                )
    return endpoints


def _extract_schemas(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    components = spec.get("components", {})
    return dict(components.get("schemas", {}))


# ---------------------------------------------------------------------------
# Blueprint asset generation
# ---------------------------------------------------------------------------


def _build_blueprint_asset(
    name: str,
    slug: str,
    endpoints: list[dict[str, Any]],
    schemas: dict[str, dict[str, Any]],
) -> BlueprintAsset:
    tickets = []
    for i, ep in enumerate(endpoints):
        tickets.append(
            BlueprintTicketAsset(
                ticket_id=f"{slug.upper()}-EP-{i + 1}",
                title=ep["summary"] or f"{ep['method']} {ep['path']}",
                status="active",
                assignee=None,
                description=(
                    f"Endpoint: {ep['method']} {ep['path']}\n"
                    f"Operation: {ep['operation_id']}\n"
                    f"{ep['description']}"
                ).strip(),
            )
        )

    work_graph = BlueprintWorkGraphAsset(tickets=tickets) if tickets else None

    facade_list = [slug]
    tool_names = [f"{slug}.{ep['operation_id']}" for ep in endpoints]

    asset = BlueprintAsset(
        name=f"{slug}.scaffold.blueprint",
        title=name,
        description=f"Scaffolded from OpenAPI spec for {name}",
        scenario_name=f"{slug}_scaffold",
        workflow_name=f"{slug}_scaffold",
        requested_facades=facade_list,
        capability_graphs=BlueprintCapabilityGraphsAsset(
            organization_name=name,
            organization_domain=f"{slug}.local",
            work_graph=work_graph,
        ),
        metadata={
            "scaffolded_from": "openapi",
            "endpoint_count": len(endpoints),
            "schema_count": len(schemas),
            "tool_names": tool_names,
            "causal_links": [
                {
                    "note": "TODO: Define causal links between tools. Example:",
                    "source": tool_names[0] if tool_names else "service.action_a",
                    "target": "slack.send_message",
                    "description": "When action completes, notify a Slack channel",
                }
            ],
        },
    )
    return asset


# ---------------------------------------------------------------------------
# Code generation
# ---------------------------------------------------------------------------


def _generate_model_stubs(
    slug: str,
    schemas: dict[str, dict[str, Any]],
) -> str:
    lines = [
        '"""Pydantic models scaffolded from OpenAPI schemas."""',
        "",
        "from __future__ import annotations",
        "",
        "from typing import Any, List, Optional",
        "",
        "from pydantic import BaseModel, Field",
        "",
        "",
    ]

    if not schemas:
        lines.append(f"# No schemas found in spec for {slug}.")
        lines.append(f"class {_pascal(slug)}Item(BaseModel):")
        lines.append("    id: str = ''")
        lines.append("    name: str = ''")
        lines.append("")
        return "\n".join(lines)

    for schema_name, schema_def in schemas.items():
        class_name = _pascal(schema_name)
        lines.append(f"class {class_name}(BaseModel):")
        props = schema_def.get("properties", {})
        required = set(schema_def.get("required", []))
        if not props:
            lines.append("    pass")
            lines.append("")
            lines.append("")
            continue
        for prop_name, prop_def in props.items():
            py_type = _openapi_type_to_python(prop_def)
            is_required = prop_name in required
            if is_required:
                lines.append(f"    {_snake(prop_name)}: {py_type}")
            else:
                default = _python_default(py_type)
                lines.append(f"    {_snake(prop_name)}: {py_type} = {default}")
        lines.append("")
        lines.append("")

    return "\n".join(lines)


def _generate_router_stubs(
    slug: str,
    name: str,
    endpoints: list[dict[str, Any]],
) -> str:
    lines = [
        f'"""Router stubs for {name}, scaffolded from OpenAPI."""',
        "",
        "from __future__ import annotations",
        "",
        "from typing import Any",
        "",
        "",
        f"def register_{slug}_tools(router) -> None:",
        f'    """Register {name} tools on the VEI router."""',
        "",
    ]

    if not endpoints:
        lines.append("    pass")
        return "\n".join(lines)

    for ep in endpoints:
        op = ep["operation_id"]
        method = ep["method"]
        path = ep["path"]
        summary = ep["summary"] or f"{method} {path}"

        lines.append(f"    @router.tool('{slug}.{op}')")
        lines.append(f"    def {op}(args: dict[str, Any]) -> dict[str, Any]:")
        lines.append(f'        """{summary}"""')
        lines.append(f"        # TODO: implement {method} {path}")
        lines.append(f"        return {{'status': 'ok', 'tool': '{slug}.{op}'}}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# String utilities
# ---------------------------------------------------------------------------


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _snake(value: str) -> str:
    s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", value)
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1)
    return re.sub(r"[^a-z0-9]+", "_", s2.lower()).strip("_")


def _pascal(value: str) -> str:
    return "".join(word.capitalize() for word in re.split(r"[_\-\s]+", value) if word)


def _sanitize_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", value).strip("_")


def _path_to_snake(path: str) -> str:
    cleaned = re.sub(r"\{[^}]+\}", "by_id", path)
    return _snake(cleaned.strip("/"))


def _openapi_type_to_python(prop: dict[str, Any]) -> str:
    t = prop.get("type", "")
    if t == "string":
        return "str"
    if t == "integer":
        return "int"
    if t == "number":
        return "float"
    if t == "boolean":
        return "bool"
    if t == "array":
        items = prop.get("items", {})
        inner = _openapi_type_to_python(items)
        return f"List[{inner}]"
    if t == "object":
        return "dict[str, Any]"
    ref = prop.get("$ref", "")
    if ref:
        name = ref.rsplit("/", 1)[-1]
        return _pascal(name)
    return "Any"


def _python_default(py_type: str) -> str:
    if py_type == "str":
        return "''"
    if py_type == "int":
        return "0"
    if py_type == "float":
        return "0.0"
    if py_type == "bool":
        return "False"
    if py_type.startswith("List"):
        return "Field(default_factory=list)"
    if py_type.startswith("dict"):
        return "Field(default_factory=dict)"
    return "None"
