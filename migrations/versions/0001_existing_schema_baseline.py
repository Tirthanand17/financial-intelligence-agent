"""Mark the already-deployed SQLAlchemy schema as the Alembic baseline.

Revision ID: 0001_existing_schema_baseline
Revises: None

IMPORTANT: this revision intentionally performs no DDL. The production database
predates Alembic and must only be stamped to this revision after the read-only
schema guard confirms that every modeled table/column already exists. Future
schema changes must be represented by normal Alembic revisions after this
baseline.
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0001_existing_schema_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing production schema is the baseline. Do not create/drop/alter here.
    pass


def downgrade() -> None:
    # Never destroy a pre-Alembic production schema by downgrading the baseline.
    pass
