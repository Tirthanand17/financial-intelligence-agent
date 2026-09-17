from sqlalchemy import Column, Integer, MetaData, Table, create_engine

from app.storage.database import Base
from app.storage.schema_guard import inspect_schema_against_models


def test_schema_guard_passes_for_current_metadata() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    result = inspect_schema_against_models(engine)

    assert result.safe is True
    assert result.missing_tables == ()
    assert result.missing_columns == {}


def test_schema_guard_fails_closed_on_missing_modeled_schema() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata = MetaData()
    Table("documents", metadata, Column("id", Integer, primary_key=True))
    metadata.create_all(engine)

    result = inspect_schema_against_models(engine)

    assert result.safe is False
    assert result.missing_tables
    assert "documents" in result.missing_columns
    assert result.missing_columns["documents"]


def test_schema_guard_allows_unrelated_platform_tables_but_reports_them() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    metadata = MetaData()
    Table("platform_metadata", metadata, Column("id", Integer, primary_key=True))
    metadata.create_all(engine)

    result = inspect_schema_against_models(engine)

    assert result.safe is True
    assert "platform_metadata" in result.unexpected_tables
