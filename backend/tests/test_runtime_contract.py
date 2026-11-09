import csv
import hashlib
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import data_contract, services, local_auth
from app.main import app

FIELDS = ['store_id', 'product_id', 'dt', 'stock_hour6_22_cnt', 'sale_amount']

@pytest.fixture
def dataset(tmp_path, monkeypatch):
    path = tmp_path / 'data.csv'
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f); writer.writerow(FIELDS)
        for day in range(1, 9): writer.writerow([' x ', 'p', f'2024-05-{day:02d}', '1', '0.2'])
    monkeypatch.setenv('FRESHRETAIL_PATH', str(path))
    monkeypatch.setenv('STOCKWATCH_DB', str(tmp_path/'cases.sqlite3'))
    return path

def test_runtime_warns_and_uses_same_validated_snapshot(dataset, monkeypatch):
    expected_hash = hashlib.sha256(dataset.read_bytes()).hexdigest()
    original = data_contract.validate_bytes
    def change_disk(raw, **kwargs):
        report = original(raw, **kwargs)
        dataset.write_text('different bytes', encoding='utf-8')
        return report
    monkeypatch.setattr(data_contract, 'validate_bytes', change_disk)
    result = services.build_batch('2024-05-07', 10)
    assert result['data_quality']['status'] == 'warn'
    assert result['dataset_sha256'] == expected_hash == result['data_quality']['dataset_sha256']
    assert services.get_batch(result['batch_id'])['dataset_sha'] == expected_hash
    assert services.get_cases(result['batch_id'])['items'][0]['store_id'] == 'x'

@pytest.mark.parametrize('row', [
    'x,p,2024-05-09,nan,1\n',
    'x,p,2024-05-09,17,1\n',
    'x,p,2024-05-09,-1,1\n',
    'x,p,2024-05-01,1,1\n',
])
def test_invalid_data_blocks_before_database_write(dataset, row):
    with dataset.open('a', encoding='utf-8') as f: f.write(row)
    with pytest.raises(services.DataContractError) as err:
        services.build_batch('2024-05-07', 10)
    assert err.value.report['status'] == 'fail'
    assert not services.db_path().exists()

def test_duplicate_columns_block(dataset):
    dataset.write_text('store_id,product_id,dt,stock_hour6_22_cnt,sale_amount,sale_amount\nx,p,2024-05-01,1,2,2\n',encoding='utf-8')
    with pytest.raises(services.DataContractError) as err:
        services.build_batch('2024-05-01', 1)
    assert err.value.report['errors']['duplicate_column_names'] == 1
    assert not services.db_path().exists()

def test_missing_file_returns_quality_report_without_writing(dataset):
    dataset.unlink()
    with pytest.raises(services.DataContractError) as err:
        services.build_batch('2024-05-01', 1)
    assert err.value.report['errors']['file_not_found'] == 1
    assert not services.db_path().exists()

def test_quality_endpoint_and_batch_require_admin(dataset, monkeypatch):
    monkeypatch.setattr(local_auth, 'loopback_request', lambda request: True)
    monkeypatch.setattr(local_auth, 'current_user', lambda request: None)
    client = TestClient(app, base_url='http://127.0.0.1:8765')
    assert client.get('/api/v1/data-quality').status_code == 401
    monkeypatch.setattr(local_auth, 'current_user', lambda request: {'id':'u','roles':['user']})
    assert client.get('/api/v1/data-quality').status_code == 403
    monkeypatch.setattr(local_auth, 'current_user', lambda request: {'id':'a','roles':['super_admin']})
    quality = client.get('/api/v1/data-quality?as_of=2024-05-07')
    assert quality.status_code == 200 and quality.json()['status'] == 'warn'
    with dataset.open('a', encoding='utf-8') as f: f.write('x,p,2024-05-09,17,1\n')
    reply = client.post('/api/v1/batches', json={'as_of_date':'2024-05-07','k':1}, headers={'origin':'http://127.0.0.1:8765'})
    assert reply.status_code == 422 and reply.json()['data_quality']['status'] == 'fail'
    assert not services.db_path().exists()
