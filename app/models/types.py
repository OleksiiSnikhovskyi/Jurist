import uuid
from typing import Any

from sqlalchemy.types import CHAR, JSON, TypeDecorator


class GUID(TypeDecorator[str]):
    """Platform-neutral UUID storage for SQLAlchemy models and SQLite tests."""

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import UUID

            return dialect.type_descriptor(UUID(as_uuid=False))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        return str(value)

    def process_result_value(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        return str(value)


class JSONVariant(TypeDecorator[dict[str, Any] | list[Any]]):
    """Use JSONB on PostgreSQL and portable JSON elsewhere."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import JSONB

            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


def new_uuid() -> str:
    return str(uuid.uuid4())
