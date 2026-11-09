import csv
import json
import subprocess
import sys
from pathlib import Path

from app.data_contract import DEFAULT_DATA, validate


HEAD = ['store_id', 'product_id', 'dt', 'stock_hour6_22_cnt', 'sale_amount', 'hours_stock_status']


def write_csv(path, rows):
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(HEAD)
        writer.writerows(rows)


def test_reference_data_fingerprint_and_grain():
    report = validate(DEFAULT_DATA, as_of='2024-07-01', require_reference=True)
    assert report['status'] == 'pass'
    assert (report['row_count'], report['pair_count']) == (19400, 200)
    assert report['checks']['replay_window']['runtime_filter_verified'] is False
    assert report['checks']['replay_window']['availability_time_verified'] is False


def test_missing_values_and_non_reference_are_warnings(tmp_path):
    p = tmp_path / 'input.csv'
    write_csv(p, [['a', 'p', '2024-01-01', '', '', '[1, 0]']])
    result = validate(p)
    assert result['status'] == 'warn'
    assert result['warnings']['missing_stock_hours'] == 1
    assert result['warnings']['missing_sale_amount'] == 1
    assert result['warnings']['reference_hash_mismatch'] == 1
    assert validate(p, require_reference=True)['status'] == 'fail'


def test_duplicate_keys_and_invalid_number_are_errors(tmp_path):
    p = tmp_path / 'input.csv'
    write_csv(p, [['a', 'p', '2024-01-01', '0', '2', ''],
                  ['a', 'p', '2024-01-01', '17', 'nan', '']])
    result = validate(p)
    assert result['status'] == 'fail'
    assert result['errors']['duplicate_primary_key'] == 1
    assert result['errors']['invalid_stock_hour6_22_cnt'] == 1
    assert result['errors']['invalid_sale_amount'] == 1


def test_as_of_is_context_not_false_leakage_detection(tmp_path):
    p = tmp_path / 'input.csv'
    write_csv(p, [['a', 'p', '2024-01-01', '2', '27.6', ''],
                  ['a', 'p', '2024-01-02', '0', '0', '']])
    result = validate(p, as_of='2024-01-01')
    assert result['status'] == 'warn'  # only reference mismatch
    assert result['checks']['replay_window']['future_rows_are_allowed_in_source']
    assert 'future_data' not in result['errors']
    assert validate(p, as_of='not-a-date')['errors']['invalid_as_of_date'] == 1


def test_cli_emits_json_and_nonzero_on_invalid_contract(tmp_path):
    p = tmp_path / 'input.csv'
    write_csv(p, [['a', 'p', 'not-a-date', '2', '4', '']])
    result = subprocess.run([sys.executable, '-m', 'app.data_contract', '--csv', str(p)], capture_output=True, check=False)
    assert result.returncode == 2
    assert json.loads(result.stdout.decode('utf-8'))['errors']['invalid_date'] == 1
