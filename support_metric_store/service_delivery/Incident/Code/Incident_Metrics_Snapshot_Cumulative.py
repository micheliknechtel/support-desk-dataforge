"""Incident lifecycle counts up to and including the injected SNAPSHOT_DATE.

Computed from source events, never from prior snapshots. The transaction
replaces this snapshot's metrics, including empty results.
"""

GRAIN_KEYS = {
    "Account": ["account_id"],
    "Workspace": ["account_id", "workspace_id"],
    "User": ["account_id", "user_id"],
}

METRICS = {
    "total_incident_create_count": "created_at",
    "total_incident_resolve_count": "closed_at",
}

metric_names = ", ".join(f"'{metric}'" for metric in METRICS)
STATEMENTS = ["BEGIN TRANSACTION"]

for grain, keys in GRAIN_KEYS.items():
    key_list = ",\n    ".join(keys)
    table_name = f"{TARGET_CATALOG}.Incident_{grain}_Metrics_Snapshot_Cumulative"
    STATEMENTS.append(
        f"""
DELETE FROM {table_name}
WHERE SNAPSHOT_DATE = DATE '{SNAPSHOT_DATE}'
  AND SOURCE_ZONE = '{SOURCE_ZONE}'
  AND metric_name IN ({metric_names})
"""
    )
    for metric, event_column in METRICS.items():
        STATEMENTS.append(
            f"""
INSERT INTO {table_name}
SELECT
    DATE '{SNAPSHOT_DATE}' AS SNAPSHOT_DATE
    , {key_list}
    , '{metric}' AS metric_name
    , COUNT(DISTINCT incident_id) AS metric_value
    , CURRENT_TIMESTAMP AS LOAD_TIMESTAMP
    , '{SOURCE_ZONE}' AS SOURCE_ZONE
FROM {SOURCE_CATALOG}.incidents
WHERE is_deleted = false
  AND {event_column} IS NOT NULL
  AND CAST({event_column} AS DATE) <= DATE '{SNAPSHOT_DATE}'
GROUP BY ALL
"""
        )

STATEMENTS.append("COMMIT")
