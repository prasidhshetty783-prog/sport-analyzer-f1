"""Generate frontend/src/lib/ws/types.ts from schema.py. Deterministic output;
test_schema.py asserts the generated file is current."""
from __future__ import annotations

import typing
from pathlib import Path

from pydantic import BaseModel

from backend.api import schema

HEADER = """\
// GENERATED FILE - do not edit.
// Source of truth: backend/api/schema.py  (python -m backend.api.gen_types)

"""


def ts_type(ann) -> str:
    origin = typing.get_origin(ann)
    args = typing.get_args(ann)
    if origin is typing.Literal:
        return " | ".join(f'"{a}"' if isinstance(a, str) else str(a) for a in args)
    if origin in (list, typing.List):
        return f"{ts_type(args[0])}[]"
    if origin is typing.Union:  # Optional[X] -> X | null
        parts = [a for a in args if a is not type(None)]
        inner = " | ".join(ts_type(p) for p in parts)
        return f"{inner} | null"
    if isinstance(ann, type) and issubclass(ann, BaseModel):
        return ann.__name__
    return {str: "string", int: "number", float: "number", bool: "boolean"}[ann]


def collect_models() -> list[type[BaseModel]]:
    """All message models + nested models they reference, declaration order."""
    seen: dict[str, type[BaseModel]] = {}

    def visit(model: type[BaseModel]) -> None:
        for f in model.model_fields.values():
            for sub in _nested(f.annotation):
                if sub.__name__ not in seen:
                    visit(sub)
                    seen[sub.__name__] = sub
        if model.__name__ not in seen:
            seen[model.__name__] = model

    def _nested(ann):
        out = []
        if isinstance(ann, type) and issubclass(ann, BaseModel):
            out.append(ann)
        for a in typing.get_args(ann):
            out.extend(_nested(a))
        return out

    for m in [*schema.SERVER_MESSAGES, *schema.CLIENT_MESSAGES]:
        visit(m)
    return list(seen.values())


def render() -> str:
    out = [HEADER]
    out.append(f"export const PROTOCOL_VERSION = {schema.PROTOCOL_VERSION};\n\n")
    for model in collect_models():
        out.append(f"export interface {model.__name__} {{\n")
        for name, f in model.model_fields.items():
            optional = "" if (f.is_required() or name == "kind") else "?"
            out.append(f"  {name}{optional}: {ts_type(f.annotation)};\n")
        out.append("}\n\n")
    server = " | ".join(m.__name__ for m in schema.SERVER_MESSAGES)
    client = " | ".join(m.__name__ for m in schema.CLIENT_MESSAGES)
    out.append(f"export type ServerMessage = {server};\n")
    out.append(f"export type ClientMessage = {client};\n")
    return "".join(out)


def main(dest: str | None = None) -> Path:
    dest_path = Path(dest) if dest else (
        Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "ws" / "types.ts")
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_text(render(), encoding="utf-8")
    print(f"wrote {dest_path}")
    return dest_path


if __name__ == "__main__":
    import sys

    main(sys.argv[1] if len(sys.argv) > 1 else None)
