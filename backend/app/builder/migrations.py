"""Plans Alembic migrations by comparing the previous and next AppSpec.

Migrations are append-only: once generated they are never rewritten. Dropping a table or column,
or changing a column's type, is destructive and must be approved before it is generated.
"""

from .spec import AppSpec, FieldSpec


def _field(field: FieldSpec) -> dict:
    return {"name": field.name, "type": field.type}


def _tables(spec: AppSpec | None) -> dict[str, dict[str, str]]:
    if spec is None or "api" not in spec.targets:
        return {}
    tables = {e.table: {f.name: f.type for f in e.fields} for e in spec.entities}
    if spec.auth:
        tables["users"] = {}
    return tables


def plan(previous: AppSpec | None, current: AppSpec, existing: list[dict]) -> dict | None:
    """Returns the next migration, or None when the schema is unchanged."""
    if "api" not in current.targets:
        return None
    before = _tables(previous) if existing else {}
    after = _tables(current)
    entities = {e.table: e for e in current.entities}
    ops: list[dict] = []
    for table in after:
        if table not in before:
            fields = [_field(f) for f in entities[table].fields] if table in entities else []
            ops.append({"op": "create_table", "table": table, "fields": fields})
    for table, columns in after.items():
        if table not in before or table == "users":
            continue
        old = before[table]
        for name, type_ in columns.items():
            if name not in old:
                ops.append(
                    {"op": "add_column", "table": table, "field": {"name": name, "type": type_}}
                )
            elif old[name] != type_:
                ops.append(
                    {
                        "op": "drop_column",
                        "table": table,
                        "column": name,
                        "reason": f"type changes from {old[name]} to {type_}",
                    }
                )
                ops.append(
                    {"op": "add_column", "table": table, "field": {"name": name, "type": type_}}
                )
        for name in old:
            if name not in columns:
                ops.append({"op": "drop_column", "table": table, "column": name})
    for table in before:
        if table not in after:
            ops.append({"op": "drop_table", "table": table})
    if not ops:
        return None
    number = len(existing) + 1
    destructive = [op for op in ops if op["op"] in {"drop_table", "drop_column"}]
    message = "Initial schema" if not existing else _describe(ops)
    return {
        "revision": f"{number:04d}",
        "down_revision": existing[-1]["revision"] if existing else None,
        "slug": "initial" if not existing else f"update_{number:04d}",
        "message": message,
        "ops": ops,
        "destructive": bool(destructive),
        "destructive_summary": [_describe([op]) for op in destructive],
    }


def _describe(ops: list[dict]) -> str:
    parts = []
    for op in ops:
        kind = op["op"]
        if kind == "create_table":
            parts.append(f"create {op['table']}")
        elif kind == "add_column":
            parts.append(f"add {op['table']}.{op['field']['name']}")
        elif kind == "drop_column":
            parts.append(
                f"drop {op['table']}.{op['column']}"
                + (f" ({op['reason']})" if op.get("reason") else "")
            )
        elif kind == "drop_table":
            parts.append(f"drop table {op['table']} and all its data")
    text = ", ".join(parts)
    return text[:1].upper() + text[1:]
