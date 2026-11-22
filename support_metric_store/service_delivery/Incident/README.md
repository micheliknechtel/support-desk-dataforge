# Incident

Incident lifecycle counts for the service delivery domain, matching Ticket's
account, workspace, and user grains and long-format `metric_name`/`metric_value`
tables.

## Metrics

| Metric | Grains | Cadences | Source |
| :--- | :--- | :--- | :--- |
| `total_incident_create_count` | account, workspace, user | Daily, Cumulative | `incidents.created_at` |
| `total_incident_resolve_count` | account, workspace, user | Daily, Cumulative | `incidents.closed_at` |

Each metric counts distinct `incident_id` values within its grain. Rows with
`is_deleted = true` are excluded. Daily uses the event's calendar date equal to
`SNAPSHOT_DATE`, while Cumulative includes events through that date.

Discovery confirmed that `closed_at` is recorded exactly for resolved incidents
in both zones. Resolution is counted by that timestamp, not `updated_at` or a
current-status filter. The source is current-state data, not a complete
transition history, so repeated resolutions cannot be reconstructed.

Like Ticket, output is sparse: a grain with no qualifying event has no metric
row rather than an explicit zero. Cumulative counts are recomputed from source
events, never from prior snapshots.

## Running

The shared runners emit DuckDB SQL. After rendering and deploying the six
`Schema/*.sql` files with `{TARGET_CATALOG}` set to the manifest's resolved
target schema, run from the repository root through forge-dbx:

```bash
set -o pipefail
SOURCE_ZONE=zone1 SNAPSHOT_DATE=2026-11-21 \
  python3 support_metric_store/common/daily_runner.py \
  support_metric_store/service_delivery/Incident/Code/Incident_Metrics_Snapshot_Daily.py \
  | duckdb warehouse/zone1.duckdb -json

SOURCE_ZONE=zone1 SNAPSHOT_DATE=2026-11-21 \
  python3 support_metric_store/common/cumulative_runner.py \
  support_metric_store/service_delivery/Incident/Code/Incident_Metrics_Snapshot_Cumulative.py \
  | duckdb warehouse/zone1.duckdb -json
```

Set both `SOURCE_ZONE` and the database path to zone2 for that zone. Change
`SNAPSHOT_DATE` to the date being loaded. DuckDB has no Spark runtime,
`TO_DATE`, or `INSERT OVERWRITE`, so these pipelines use `CAST(... AS DATE)`
and transactional `DELETE` + `INSERT`. Each run atomically replaces only its
date, zone, and two metric names across all grains. Reruns cannot duplicate
rows, and an empty result removes stale rows. No scheduler is configured.

## Validation and deployment

```bash
python3 -m unittest discover \
  -s support_metric_store/service_delivery/Incident/Code -p 'test_*.py' -v
```

The suite exercises both cadences and all grains with duplicate IDs, deleted
rows, null/future resolution dates, midnight boundaries, reruns, empty results,
partition isolation, and rollback on a failed grain.

`Code/__incident_test.sql` independently reconciles source and target counts.
Render its catalog, table, zone, grain-column, and date-window placeholders,
using `DATE_OPERATOR` of `=` for Daily and `<=` for Cumulative, then execute
through forge-dbx. Expected and actual rows must agree, with zero mismatches
and duplicate keys. This check handles event-free dates without requiring
artificial zero rows.

The #1 build backfilled 2026-07-25 through 2026-11-21 in both zones. All six
tables per zone reconciled exactly, and existing Ticket totals were unchanged.
At the final snapshot, zone1 has 261 created and 54 resolved incidents, while
zone2 has 108 created and 18 resolved incidents.

For the next 48 hours, compare output with source aggregates: investigate
row-count deviations over 20%, all-zero metrics across the full window, an
unexpected empty zone, or missing expected event dates. These are manual
checks, not automated alerts.

## Development history

| Date | Contributors | Change | Issue |
| :--- | :--- | :--- | :--- |
| 2026-11-22 | @micheliknechtel, Copilot | Add create/resolve counts, six schemas, atomic reruns, source reconciliation, and two-zone historical backfill | #1 |
