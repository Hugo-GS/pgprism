"""Data contracts and serialization for PostgreSQL query results."""

import math
import uuid
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import TypeAlias, TypedDict

JsonPrimitive: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]


class QueryResult(TypedDict):
    columns: list[str]
    rows: list[dict[str, JsonValue]]
    row_count: int
    truncated: bool


class TableInfo(TypedDict):
    table_name: str
    table_type: str


class ColumnInfo(TypedDict):
    name: str
    type: str
    nullable: bool
    default: str | None
    is_primary_key: bool


class TableDescription(TypedDict):
    table: str
    schema: str
    columns: list[ColumnInfo]


def serialize_value(val: object) -> JsonValue:
    """Convert PostgreSQL-specific or non-JSON-serializable types to Python primitives."""
    if val is None:
        return None
    if isinstance(val, (datetime, date, time)):
        return val.isoformat()
    if isinstance(val, uuid.UUID):
        return str(val)
    if isinstance(val, Decimal):
        if val.is_nan() or val.is_infinite():
            return None
        try:
            return float(val) if val % 1 else int(val)
        except InvalidOperation:
            return None
    if isinstance(val, float):
        if math.isnan(val) or math.isinf(val):
            return None
        return val
    if isinstance(val, bytes):
        return val.hex()
    if isinstance(val, (list, tuple)):
        return [serialize_value(x) for x in val]
    if isinstance(val, dict):
        return {str(k): serialize_value(v) for k, v in val.items()}
    if isinstance(val, (str, int, bool)):
        return val
    return str(val)
