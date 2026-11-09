"""Smoke-check the independent offline evaluation and its report contract."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_report_tracks_pass_fail_and_unassessed_separately():
    result = subprocess.run([sys.executable, str(ROOT / 'evals/run_eval.py')], cwd=ROOT, capture_output=True, text=True, encoding='utf8', timeout=60)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['contract']['contract_id'] == 'stockwatch.freshretail.daily.v1'
    assert report['contract']['status'] == 'pass'
    assert report['counts'] == {'pass': 12, 'fail': 0, 'unassessed': 1}
    cases = {case['case_id']: case for case in report['cases']}
    assert cases['T01']['observed']['results_unchanged'] is True
    assert cases['S02']['observed']['unknown_label_count'] == 1
    assert cases['L01']['status'] == 'unassessed'

def test_failed_data_contract_blocks_evaluation():
    code = """import importlib.util, json
from pathlib import Path
spec = importlib.util.spec_from_file_location('offline_eval', Path('evals/run_eval.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.data_contract.validate = lambda *a, **k: {'contract_id':'test','contract_version':'1','status':'fail','errors':{'invalid':1},'warnings':{}}
raise SystemExit(module.main())
"""
    result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True, encoding='utf8', timeout=60)
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report['status'] == 'blocked'
    assert report['reason'] == 'data_contract_failed'
    assert 'counts' not in report
