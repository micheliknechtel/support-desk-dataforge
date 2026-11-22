"""Exercise runner-generated SQL in disposable DuckDB files."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[4]
ENTITY = Path(__file__).resolve().parent.parent
SOURCE = "demo_gold_source_a"
TARGET = "demo_gold_support_metric_store"
GRAINS = {
    "Account": ["account_id"],
    "Workspace": ["account_id", "workspace_id"],
    "User": ["account_id", "user_id"],
}


class IncidentMetricsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = Path(self.temp_dir.name) / "test.duckdb"
        ddl = f"""
CREATE SCHEMA {SOURCE};
CREATE SCHEMA {TARGET};
CREATE TABLE {SOURCE}.incidents (
    incident_id BIGINT, account_id BIGINT, workspace_id BIGINT, user_id BIGINT,
    created_at TIMESTAMP, closed_at TIMESTAMP, is_deleted BOOLEAN
);
INSERT INTO {SOURCE}.incidents VALUES
    (1, 10, 101, 1001, '2026-01-01 09:00:00', '2026-01-03 23:59:59', false),
    (1, 10, 101, 1001, '2026-01-01 09:00:00', '2026-01-03 23:59:59', false),
    (2, 10, 102, 1002, '2026-01-03 00:00:00', NULL, false),
    (3, 20, 201, 2001, '2026-01-03 23:59:59', '2026-01-03 23:59:59', false),
    (4, 20, 201, 2001, '2026-01-03 09:00:00', '2026-01-03 17:00:00', true),
    (5, 20, 201, 2001, '2026-01-04 00:00:00', '2026-01-05 17:00:00', false),
    (6, 10, 101, 1001, '2026-01-01 09:00:00', '2026-01-02 17:00:00', false),
    (7, 10, 102, 1002, '2026-01-03 09:00:00', '2026-01-04 00:00:00', false);
"""
        ddl += "\n".join(
            path.read_text().format(TARGET_CATALOG=TARGET)
            for path in sorted((ENTITY / "Schema").glob("*.sql"))
        )
        self.execute(ddl)

    def execute(self, sql):
        result = subprocess.run(
            ["duckdb", str(self.database), "-json"],
            input=sql,
            text=True,
            capture_output=True,
            check=True,
        )
        return result.stdout

    def query(self, sql):
        return json.loads(self.execute(sql))

    def pipeline_sql(self, cadence, date="2026-01-03", zone="test"):
        runner = ROOT / "support_metric_store" / "common" / f"{cadence.lower()}_runner.py"
        pipeline = ENTITY / "Code" / f"Incident_Metrics_Snapshot_{cadence}.py"
        result = subprocess.run(
            [sys.executable, str(runner), str(pipeline)],
            env=dict(os.environ, ENGINE="duckdb", SNAPSHOT_DATE=date, SOURCE_ZONE=zone),
            text=True,
            capture_output=True,
            check=True,
        )
        return result.stdout

    def test_event_counts_and_source_reconciliation(self):
        template = (ENTITY / "Code" / "__incident_test.sql").read_text()
        for cadence, operator, totals in (
            ("Daily", "=", (3, 2)),
            ("Cumulative", "<=", (5, 3)),
        ):
            for day in ("01", "02", "03"):
                self.execute(self.pipeline_sql(cadence, f"2026-01-{day}"))
            for grain, keys in GRAINS.items():
                with self.subTest(cadence=cadence, grain=grain):
                    table = f"Incident_{grain}_Metrics_Snapshot_{cadence}"
                    counts = self.query(f"""
SELECT metric_name, CAST(SUM(metric_value) AS BIGINT) AS total
FROM {TARGET}.{table}
WHERE SNAPSHOT_DATE = DATE '2026-01-03'
GROUP BY ALL ORDER BY metric_name;
""")
                    self.assertEqual([row["total"] for row in counts], list(totals))
                    result = self.query(template.format(
                        START_DATE="2026-01-01",
                        END_DATE="2026-01-03",
                        SOURCE_CATALOG=SOURCE,
                        TARGET_CATALOG=TARGET,
                        SOURCE_ZONE="test",
                        TABLE_NAME=table,
                        GRAIN_COLUMNS=", ".join(keys),
                        DATE_OPERATOR=operator,
                    ))[0]
                    self.assertEqual(result["expected_rows"], result["actual_rows"])
                    self.assertEqual(result["mismatches"], 0)
                    self.assertEqual(result["duplicate_keys"], 0)

    def test_reruns_replace_empty_partitions_without_touching_others(self):
        for cadence in ("Daily", "Cumulative"):
            with self.subTest(cadence=cadence):
                sql = self.pipeline_sql(cadence)
                self.execute(sql)
                before = self.query(f"""
SELECT COUNT(*) AS rows, SUM(metric_value) AS total
FROM {TARGET}.Incident_Account_Metrics_Snapshot_{cadence};
""")
                self.execute(sql)
                self.assertEqual(before, self.query(f"""
SELECT COUNT(*) AS rows, SUM(metric_value) AS total
FROM {TARGET}.Incident_Account_Metrics_Snapshot_{cadence};
"""))
                self.execute(self.pipeline_sql(cadence, "2026-01-02"))
                self.execute(self.pipeline_sql(cadence, zone="other"))
        self.execute(f"UPDATE {SOURCE}.incidents SET is_deleted = true;")
        for cadence in ("Daily", "Cumulative"):
            self.execute(self.pipeline_sql(cadence))
            for grain in GRAINS:
                with self.subTest(cadence=cadence, grain=grain):
                    counts = self.query(f"""
SELECT
    COUNT(*) FILTER (
        WHERE SNAPSHOT_DATE = DATE '2026-01-03' AND SOURCE_ZONE = 'test'
    ) AS replaced_rows
    , COUNT(*) FILTER (WHERE SNAPSHOT_DATE = DATE '2026-01-02') AS other_date_rows
    , COUNT(*) FILTER (WHERE SOURCE_ZONE = 'other') AS other_zone_rows
FROM {TARGET}.Incident_{grain}_Metrics_Snapshot_{cadence};
""")[0]
                    self.assertEqual(counts["replaced_rows"], 0)
                    self.assertGreater(counts["other_date_rows"], 0)
                    self.assertGreater(counts["other_zone_rows"], 0)

    def test_failed_load_rolls_back_prior_grains(self):
        for cadence in ("Daily", "Cumulative"):
            with self.subTest(cadence=cadence):
                sql = self.pipeline_sql(cadence)
                self.execute(sql)
                table = f"{TARGET}.Incident_Account_Metrics_Snapshot_{cadence}"
                before = self.query(
                    f"SELECT COUNT(*) AS rows, SUM(metric_value) AS total FROM {table};"
                )
                self.execute(
                    f"DROP TABLE {TARGET}.Incident_User_Metrics_Snapshot_{cadence};"
                )
                self.execute(f"UPDATE {SOURCE}.incidents SET is_deleted = true;")
                with self.assertRaises(subprocess.CalledProcessError):
                    self.execute(sql)
                self.assertEqual(before, self.query(
                    f"SELECT COUNT(*) AS rows, SUM(metric_value) AS total FROM {table};"
                ))
                self.execute(f"UPDATE {SOURCE}.incidents SET is_deleted = false;")


if __name__ == "__main__":
    unittest.main()
