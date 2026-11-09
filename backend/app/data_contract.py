"""Static byte-snapshot validation shared by offline audit and local batch creation."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
CONTRACT = BASE / 'contracts' / 'freshretail_v1.json'
DEFAULT_DATA = BASE / 'data' / 'freshretail_sample.csv'


def validate(path: Path, *, as_of: str | None = None, require_reference: bool = False) -> dict:
    """Return deterministic JSON-serializable results; errors fail, warnings do not.

    as_of is an audit context, not a filter or proof that data was available at T.
    """
    path = Path(path)
    try:
        raw = path.read_bytes()
        read_error = 'file_not_found'
    except FileNotFoundError:
        raw, read_error = None, 'file_not_found'
    except OSError:
        raw, read_error = None, 'file_read_error'
    return validate_bytes(raw, as_of=as_of, require_reference=require_reference, read_error=read_error)


def validate_bytes(raw: bytes | None, *, as_of: str | None = None, require_reference: bool = False, read_error: str = 'file_not_found') -> dict:
    """Validate the exact byte snapshot which a caller will subsequently parse."""
    contract = json.loads(CONTRACT.read_text(encoding='utf-8'))
    errors, warnings = Counter(), Counter()
    report = {'contract_id': contract['contract_id'], 'contract_version': contract['version'],
              'validation_scope': 'static_snapshot_only', 'reference_source': contract['source'],
              'dataset_sha256': None, 'row_count': 0, 'pair_count': 0,
              'date_min': None, 'date_max': None, 'as_of': as_of,
              'checks': {}, 'errors': {}, 'warnings': {}}
    if as_of is not None:
        try:
            if date.fromisoformat(as_of).isoformat() != as_of:
                raise ValueError
        except ValueError:
            errors['invalid_as_of_date'] += 1
    if raw is None:
        errors[read_error] += 1
        report.update(status='fail', errors=dict(errors))
        return report
    try:
        report['dataset_sha256'] = hashlib.sha256(raw).hexdigest()
        text = raw.decode('utf-8-sig')
        import io
        reader = csv.DictReader(io.StringIO(text, newline=''), strict=True)
        headers = reader.fieldnames or []
        required = {name for name, spec in contract['fields'].items() if spec['required']}
        if len(headers) != len(set(headers)):
            errors['duplicate_column_names'] += 1
        missing_columns = sorted(required - set(headers))
        if missing_columns:
            errors['missing_required_columns'] += len(missing_columns)
            report['checks']['missing_required_columns'] = missing_columns
        if not missing_columns and len(headers) == len(set(headers)):
            keys, dates = set(), set()
            pairs = defaultdict(set)
            missing_stock = missing_sale = 0
            for row in reader:
                report['row_count'] += 1
                if None in row or any(v is None for v in row.values()):
                    errors['malformed_row'] += 1
                    continue
                store, product, day = (row[k].strip() for k in ('store_id', 'product_id', 'dt'))
                if not store or not product:
                    errors['missing_primary_key'] += 1
                try:
                    parsed = date.fromisoformat(day)
                    if parsed.isoformat() != day:
                        raise ValueError
                except ValueError:
                    errors['invalid_date'] += 1
                    parsed = None
                if store and product and parsed:
                    key = (store, product, day)
                    if key in keys:
                        errors['duplicate_primary_key'] += 1
                    keys.add(key); dates.add(day); pairs[(store, product)].add(day)
                for field, maximum in (('stock_hour6_22_cnt', 16), ('sale_amount', None)):
                    value = row[field].strip()
                    if not value:
                        if field == 'stock_hour6_22_cnt': missing_stock += 1
                        else: missing_sale += 1
                        continue
                    try:
                        number = float(value)
                        if not math.isfinite(number) or number < 0 or (maximum is not None and number > maximum):
                            raise ValueError
                    except ValueError:
                        errors['invalid_' + field] += 1
            if not report['row_count']:
                errors['no_data_rows'] += 1
            if missing_stock: warnings['missing_stock_hours'] = missing_stock
            if missing_sale: warnings['missing_sale_amount'] = missing_sale
            report['pair_count'] = len(pairs)
            if dates:
                report['date_min'], report['date_max'] = min(dates), max(dates)
                calendar_days = (date.fromisoformat(report['date_max']) - date.fromisoformat(report['date_min'])).days + 1
                missing_days = sum(calendar_days - len(ds) for ds in pairs.values())
                if missing_days: warnings['missing_pair_days_in_observed_range'] = missing_days
                report['checks']['observed_calendar_days'] = calendar_days
                if as_of and 'invalid_as_of_date' not in errors:
                    t = date.fromisoformat(as_of)
                    start = (t - timedelta(days=6)).isoformat()
                    report['checks']['replay_window'] = {'start': start, 'end': as_of, 'future_rows_are_allowed_in_source': True,
                        'runtime_filter_verified': False, 'availability_time_verified': False}
                    if as_of not in dates: warnings['as_of_not_in_dataset'] += 1
    except UnicodeDecodeError:
        errors['invalid_utf8'] += 1
    except csv.Error:
        errors['invalid_csv'] += 1
    except OSError:
        errors['file_read_error'] += 1
    ref = contract['source']
    reference_checks = {'reference_hash_mismatch': report['dataset_sha256'] != ref['reference_sha256'],
                        'reference_row_count_mismatch': report['row_count'] != ref['reference_rows'],
                        'reference_date_range_mismatch': (report['date_min'], report['date_max']) != (ref['reference_date_min'], ref['reference_date_max'])}
    report['checks']['reference_match'] = not any(reference_checks.values())
    for name, mismatch in reference_checks.items():
        if mismatch: (errors if require_reference else warnings)[name] += 1
    report['checks']['as_of_runtime_and_availability_verified'] = False
    report.update(status='fail' if errors else 'warn' if warnings else 'pass', errors=dict(sorted(errors.items())), warnings=dict(sorted(warnings.items())))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description='FreshRetail 静态数据合同离线检查；不会修改数据或拦截线上请求')
    parser.add_argument('--csv', type=Path, default=DEFAULT_DATA, help='待检查 CSV 路径')
    parser.add_argument('--as-of', help='历史回放截止日期 YYYY-MM-DD；不证明运行时过滤或可用时间')
    parser.add_argument('--require-reference', action='store_true', help='将参考样本哈希、行数及日期范围不一致视为错误')
    parser.add_argument('--output', type=Path, help='将报告保存为 JSON 文件')
    args = parser.parse_args()
    result = validate(args.csv, as_of=args.as_of, require_reference=args.require_reference)
    serialized = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding='utf-8')
    else:
        sys.stdout.buffer.write(serialized.encode('utf-8'))
    return 2 if result['status'] == 'fail' else 0


if __name__ == '__main__':
    raise SystemExit(main())
