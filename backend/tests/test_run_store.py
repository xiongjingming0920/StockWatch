import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import run_store

CASE = '0123456789abcdefabcd'

@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / 'runs.sqlite3'
    monkeypatch.setenv('STOCKWATCH_RUN_DB', str(path))
    return path


def test_lifecycle_persistence_and_rejected_sensitive_metadata(db):
    owner = str(uuid.uuid4())
    run = run_store.start_run(owner, CASE)
    secret = 'sk-secret-api-key-with-private-message'
    for kw in ({'event_type': secret}, {'event_type':'tool_call','tool_name':secret},
               {'event_type':'model_call','error_code':secret}, {'event_type':'plan','status':secret}):
        with pytest.raises(ValueError):
            run_store.record_event(run, **kw)
    with pytest.raises(ValueError):
        run_store.start_run(owner, secret)
    run_store.record_event(run, 'tool_call', status='success', tool_name='get_case_summary', duration_ms=12)
    run_store.finish_run(run, 'succeeded')
    result = run_store.get_run(run, owner)
    assert result['run']['status'] == 'succeeded' and result['run']['finished_at']
    assert [x['sequence'] for x in result['events']] == [1,2,3]
    assert [x['event_type'] for x in result['events']] == ['run_started','tool_call','run_finished']
    assert run_store.get_run(run, str(uuid.uuid4())) is None
    with pytest.raises(ValueError): run_store.finish_run(run, 'failed')
    with pytest.raises(ValueError): run_store.record_event(run, 'plan')
    assert secret.encode() not in db.read_bytes()


def test_concurrent_events_have_unique_order(db):
    owner = str(uuid.uuid4())
    run = run_store.start_run(owner, CASE)
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda _: run_store.record_event(run, 'plan', status='success'), range(30)))
    run_store.finish_run(run, 'degraded')
    result = run_store.get_run(run, owner)
    assert [event['sequence'] for event in result['events']] == list(range(1,33))
    assert result['events'][-1]['status'] == result['run']['status'] == 'degraded'


def test_api_only_run_owner_can_read(db, admin_client, tmp_path, monkeypatch):
    own = admin_client.get('/api/v1/session').json()['user']['id']
    run = run_store.start_run(own, CASE)
    assert admin_client.get('/api/v1/runs/'+run).json()['run']['id'] == run
    assert admin_client.get('/api/v1/runs/'+str(uuid.uuid4())).status_code == 404
    other = TestClient(app, base_url='http://127.0.0.1:8765', client=('127.0.0.1',50000), headers={'origin':'http://127.0.0.1:8765'})
    assert other.get('/api/v1/runs/'+run).status_code == 401
    creds = {'email':'other@example.test','password':'password-for-testing'}
    assert other.post('/api/v1/auth/register', json=creds).status_code == 200
    # Simulate a second admin to verify owner isolation independently of role checks.
    with sqlite3.connect(tmp_path / 'auth.sqlite3') as auth:
        auth.execute("UPDATE users SET role='super_admin' WHERE email=?", (creds['email'],))
    assert other.post('/api/v1/auth/login', json=creds).status_code == 200
    assert other.get('/api/v1/runs/'+run).status_code == 404
