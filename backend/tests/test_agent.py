import csv
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.main import app


def test_investigation_uses_only_history_and_refuses_unavailable_facts(tmp_path, monkeypatch, admin_client):
    data = tmp_path / "data.csv"
    with data.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["store_id", "product_id", "dt", "stock_hour6_22_cnt", "sale_amount"])
        w.writeheader()
        for i in range(8):
            w.writerow({"store_id": 1, "product_id": 2, "dt": (date(2024, 5, 1) + timedelta(days=i)).isoformat(), "stock_hour6_22_cnt": 5 if i in (0, 6, 7) else 0, "sale_amount": 0.1})
    monkeypatch.setenv("FRESHRETAIL_PATH", str(data))
    monkeypatch.setenv("STOCKWATCH_DB", str(tmp_path / "state.sqlite"))
    for name in ("STOCKWATCH_LLM_API_KEY", "STOCKWATCH_LLM_BASE_URL", "STOCKWATCH_LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    with admin_client as client:
        batch = client.post("/api/v1/batches", json={"as_of_date": "2024-05-07", "k": 10}).json()
        case = client.get(f"/api/v1/batches/{batch['batch_id']}/cases").json()["items"][0]
        r = client.post(f"/api/v1/cases/{case['id']}/messages", json={"message": "最近7天缺货了几天？"})
        assert r.status_code == 200
        result = r.json()
        assert result["evidence"]["stockout_days"] == 2
        assert "2024-05-08" not in result["evidence"]["stockout_dates"]
        assert "规则路由" in result["mode"]
        r = client.post(f"/api/v1/cases/{case['id']}/messages", json={"message": "供应商延迟了吗？应该补货多少？"})
        assert "无法确定" in r.json()["answer"]
        assert client.post("/api/v1/cases/missing/messages", json={"message": "缺货"}).status_code == 404
