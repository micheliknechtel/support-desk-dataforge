# support-desk (dataforge demo)

This project uses the four dataforge skills in `.github/skills/` (forge-init, forge-dbx, forge-lint, forge-builder).

- The seed manifest is `dataforge.manifest.yaml` at the repository root. After `initialize dataforge`, the resolved manifest is `dataforge.manifest.resolved.yaml`.
- The engine is local DuckDB: zone files live in `warehouse/` (run `python3 seed.py` to build them).
- Every warehouse query goes through forge-dbx. Never `SELECT *` raw rows.

Source: adapted from https://github.com/githubevents/build-once-run-on-any-agent (demos/dataforge), CC BY 4.0 / see LICENSE.
