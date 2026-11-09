import csv
import hashlib
import json
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from app import services, risk_model, train_risk


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "data.csv"
        os.environ["FRESHRETAIL_PATH"] = str(self.path)
        os.environ["STOCKWATCH_DB"] = str(Path(self.temp.name) / "test.sqlite")
        self.rows = []
        for i in range(9):
            self.rows.append({"store_id":"1", "product_id":"2", "dt":(date(2024,5,1)+timedelta(days=i)).isoformat(), "stock_hour6_22_cnt": 1 if i in (1, 3, 6) else 0, "sale_amount": 0.1})
        self.write()

    def tearDown(self):
        self.temp.cleanup()
        os.environ.pop("FRESHRETAIL_PATH", None)
        os.environ.pop("STOCKWATCH_DB", None)

    def write(self):
        with self.path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(self.rows[0]))
            writer.writeheader()
            writer.writerows(self.rows)

    def test_replay_and_idempotent(self):
        batch = services.build_batch("2024-05-07", 10)
        self.assertEqual(batch["batch_id"], services.build_batch("2024-05-07", 10)["batch_id"])
        cases = services.get_cases(batch["batch_id"])["items"]
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["stockout_days_7d"], 3)
        self.assertEqual(len(services.get_history(cases[0]["id"], 7)), 7)
        evaluation = services.evaluate_batch(batch["batch_id"])
        self.assertEqual(evaluation["selected_known_count"], 1)
        self.assertEqual(evaluation["hits"], 0)
        self.assertEqual(services.review_case(cases[0]["id"], "REVIEWED", "done")["status"], "REVIEWED")

    def test_future_values_do_not_change_ranking(self):
        batch = services.build_batch("2024-05-07", 10)
        before = services.get_cases(batch["batch_id"])["items"][0]["score"]
        self.rows[7]["stock_hour6_22_cnt"] = 14
        self.write()
        next_batch = services.build_batch("2024-05-07", 10)
        after = services.get_cases(next_batch["batch_id"])["items"][0]["score"]
        self.assertEqual(before, after)

    def test_missing_not_treated_as_zero(self):
        self.rows[1]["stock_hour6_22_cnt"] = ""
        self.write()
        result = services.build_batch("2024-05-07", 10)
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["excluded_count"], 1)

    def test_model_cutoff_and_model_batch(self):
        original = risk_model.MODEL_PATH
        risk_model.MODEL_PATH = Path(self.temp.name) / "model.json"
        try:
            risk_model.MODEL_PATH.write_text(json.dumps({"dataset_sha": hashlib.sha256(self.path.read_bytes()).hexdigest(), "available_from_as_of": "2024-05-07", "model_version": "test", "bias": 0, "means": [0,0,0,0], "scales": [1,1,1,1], "weights": [1,0,0,0]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "未来信息泄漏"):
                services.build_batch("2024-05-06", 1, "model")
            batch = services.build_batch("2024-05-07", 1, "model")
            case = services.get_case(services.get_cases(batch["batch_id"])["items"][0]["id"])
            self.assertEqual(case["method_key"], "model")
            self.assertEqual(case["model_version"], "test")
        finally:
            risk_model.MODEL_PATH = original

    def test_training_target_uses_only_previous_seven_days(self):
        first = train_risk.samples(services.read_data())[0]
        self.assertEqual(first["target"], "2024-05-08")
        self.assertEqual(first["x"][0], 3)
        self.rows[7]["stock_hour6_22_cnt"] = 4
        self.write()
        changed = train_risk.samples(services.read_data())[0]
        self.assertEqual(first["x"], changed["x"])
        self.assertNotEqual(first["y"], changed["y"])


if __name__ == "__main__":
    unittest.main()
