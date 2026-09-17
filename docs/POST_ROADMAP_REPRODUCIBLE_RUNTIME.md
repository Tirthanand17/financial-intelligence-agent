# Post-Roadmap Reproducible Python Runtime

## Purpose

This milestone reduces deployment drift between GitHub Actions and Render by making the validated Python runtime and dependency graph explicit in the repository.

## Runtime source of truth

The repository root now contains:

```text
.python-version
```

with an exact Python patch version. GitHub Actions reads this same file instead of maintaining a separate Python version string. Render's native Python runtime also reads this repository-level version file, so CI and the deployed web service use the same interpreter line.

## Dependency source of truth

Two dependency files have distinct responsibilities:

- `requirements.in` records the project's direct dependency intent at explicitly reviewed versions.
- `requirements.txt` is the fully pinned Linux/Python 3.11.16 dependency graph validated by the CI resolver on 2026-09-17.

The production Render build command remains unchanged:

```text
pip install -r requirements.txt
```

so no manual Render configuration change is required for the dependency lock.

## CI safeguards

CI now:

1. reads `.python-version` through `actions/setup-python`;
2. caches using `requirements.txt` as the dependency-cache key;
3. installs the exact locked graph;
4. runs `pip check` to verify installed dependency compatibility; and
5. executes the complete pytest suite.

Repository regression tests additionally require an exact Python patch declaration and exact `==` pins in both the direct dependency input and production lock, and verify every direct dependency exists in the lock.

## Upgrade policy

Dependency updates are deliberate rather than ambient. To upgrade:

1. change the reviewed direct version in `requirements.in`;
2. regenerate the complete lock in the pinned Python/Linux environment;
3. run `pip check` and the full test suite;
4. review the resulting lock diff;
5. deploy through the normal pull-request/CI path; and
6. verify the Render deployment before accepting the new environment as the baseline.

Do not casually edit only one transitive package in `requirements.txt` without validating the complete graph.

## Safety boundary

This milestone changes only software-environment reproducibility. It does not change:

- evidence or provenance data;
- PostgreSQL schema or migration state;
- Qdrant points;
- Backblaze B2 evidence objects;
- source-monitor cadence;
- ingestion limits;
- claim verification state;
- trust promotion; or
- dashboard permissions.

No data is deleted or rewritten.
