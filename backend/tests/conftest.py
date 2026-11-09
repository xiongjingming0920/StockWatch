import pytest
from fastapi.testclient import TestClient
from app.main import app

@pytest.fixture
def admin_client(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKWATCH_AUTH_DB", str(tmp_path / "auth.sqlite3"))
    monkeypatch.setenv("STOCKWATCH_RUN_DB", str(tmp_path / "runs.sqlite3"))
    with TestClient(app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000), headers={"origin": "http://127.0.0.1:8765"}) as client:
        credentials = {"email": "admin@example.test", "password": "test-password-123"}
        assert client.post("/api/v1/auth/register", json=credentials).status_code == 200
        assert client.post("/api/v1/auth/login", json=credentials).status_code == 200
        yield client
