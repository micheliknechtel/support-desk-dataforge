WITH snapshot_dates AS (
    SELECT CAST(snapshot_date AS DATE) AS SNAPSHOT_DATE
    FROM generate_series(
        DATE '{START_DATE}', DATE '{END_DATE}', INTERVAL 1 DAY
    ) AS dates(snapshot_date)
)
, incident_events AS (
    SELECT
        {GRAIN_COLUMNS}
        , incident_id
        , CAST(created_at AS DATE) AS event_date
        , 'total_incident_create_count' AS metric_name
    FROM {SOURCE_CATALOG}.incidents
    WHERE is_deleted = false AND created_at IS NOT NULL
    UNION ALL
    SELECT
        {GRAIN_COLUMNS}
        , incident_id
        , CAST(closed_at AS DATE) AS event_date
        , 'total_incident_resolve_count' AS metric_name
    FROM {SOURCE_CATALOG}.incidents
    WHERE is_deleted = false AND closed_at IS NOT NULL
)
, expected_metrics AS (
    SELECT
        dates.SNAPSHOT_DATE
        , {GRAIN_COLUMNS}
        , metric_name
        , COUNT(DISTINCT incident_id) AS metric_value
    FROM snapshot_dates AS dates
    JOIN incident_events AS events
        ON events.event_date {DATE_OPERATOR} dates.SNAPSHOT_DATE
    GROUP BY ALL
)
, actual_metrics AS (
    SELECT
        SNAPSHOT_DATE
        , {GRAIN_COLUMNS}
        , metric_name
        , metric_value
    FROM {TARGET_CATALOG}.{TABLE_NAME}
    WHERE SOURCE_ZONE = '{SOURCE_ZONE}'
      AND SNAPSHOT_DATE BETWEEN DATE '{START_DATE}' AND DATE '{END_DATE}'
)
, duplicate_keys AS (
    SELECT SNAPSHOT_DATE, {GRAIN_COLUMNS}, metric_name
    FROM actual_metrics
    GROUP BY ALL
    HAVING COUNT(*) > 1
)
SELECT
    (SELECT COUNT(*) FROM expected_metrics) AS expected_rows
    , (SELECT COUNT(*) FROM actual_metrics) AS actual_rows
    , COUNT(*) FILTER (
        WHERE expected.metric_value IS DISTINCT FROM actual.metric_value
    ) AS mismatches
    , (SELECT COUNT(*) FROM duplicate_keys) AS duplicate_keys
FROM expected_metrics AS expected
FULL OUTER JOIN actual_metrics AS actual
    USING (SNAPSHOT_DATE, {GRAIN_COLUMNS}, metric_name);
