from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, inspect

from app.storage.database import Base


@dataclass(frozen=True)
class SchemaGuardResult:
    safe: bool
    missing_tables: tuple[str, ...]
    missing_columns: dict[str, tuple[str, ...]]
    unexpected_tables: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "safe": self.safe,
            "missing_tables": list(self.missing_tables),
            "missing_columns": {key: list(value) for key, value in self.missing_columns.items()},
            "unexpected_tables": list(self.unexpected_tables),
        }


def inspect_schema_against_models(engine: Engine) -> SchemaGuardResult:
    """Read-only check that the deployed database contains the modeled schema.

    The guard deliberately does not mutate the database and does not consider
    extra tables unsafe because managed platforms/extensions may add their own
    metadata. Missing modeled tables or modeled columns are fail-closed blockers.
    """
    inspector = inspect(engine)
    actual_tables = set(inspector.get_table_names())
    expected_tables = set(Base.metadata.tables)

    missing_tables = tuple(sorted(expected_tables - actual_tables))
    unexpected_tables = tuple(sorted(actual_tables - expected_tables - {"alembic_version"}))
    missing_columns: dict[str, tuple[str, ...]] = {}

    for table_name in sorted(expected_tables & actual_tables):
        expected_columns = set(Base.metadata.tables[table_name].columns.keys())
        actual_columns = {column["name"] for column in inspector.get_columns(table_name)}
        missing = tuple(sorted(expected_columns - actual_columns))
        if missing:
            missing_columns[table_name] = missing

    return SchemaGuardResult(
        safe=not missing_tables and not missing_columns,
        missing_tables=missing_tables,
        missing_columns=missing_columns,
        unexpected_tables=unexpected_tables,
    )
