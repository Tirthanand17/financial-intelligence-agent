from __future__ import annotations

import json

from sqlalchemy import create_engine

from app.core.config import get_settings
from app.storage.schema_guard import inspect_schema_against_models


def main() -> int:
    settings = get_settings()
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        result = inspect_schema_against_models(engine)
    finally:
        engine.dispose()

    print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    return 0 if result.safe else 2


if __name__ == "__main__":
    raise SystemExit(main())
