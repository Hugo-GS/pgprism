"""PostgreSQL database access package."""

from src.database.manager import DatabaseManager
from src.database.pool import PoolManager
from src.database.types import (
    ColumnInfo,
    JsonPrimitive,
    JsonValue,
    QueryResult,
    TableDescription,
    TableInfo,
    serialize_value,
)

_serialize_value = serialize_value
_pool_cache = PoolManager._cache


def close_all_pools() -> None:
    """Closes all cached connection pools."""
    PoolManager.close_all()


__all__ = [
    "ColumnInfo",
    "DatabaseManager",
    "JsonPrimitive",
    "JsonValue",
    "PoolManager",
    "QueryResult",
    "TableDescription",
    "TableInfo",
    "close_all_pools",
    "serialize_value",
]
