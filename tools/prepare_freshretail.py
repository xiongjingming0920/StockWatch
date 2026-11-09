"""Download the original data and prepare a small, reproducible real-data subset.

Usage: python tools/prepare_freshretail.py --limit 200
Requires: pip install duckdb. Raw files are cached locally and not committed.
The pairs are chosen solely by their IDs on the first training date, in blocks
of ten products per store; all train and eval dates for each pair are retained.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
VENDOR = HERE / "vendor"
if VENDOR.exists():
    sys.path.insert(0, str(VENDOR))
import duckdb

REVISION = "c374e85975c82816c495acfa904cc55ab14a47d3"
BASE = f"https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K/resolve/{REVISION}/data"
FILES = {"train.parquet": 106436287, "eval.parquet": 8440124}


def download(name: str, expected_size: int, folder: Path) -> Path:
    target = folder / name
    if target.exists() and target.stat().st_size == expected_size:
        return target
    partial = target.with_suffix(".partial")
    req = urllib.request.Request(f"{BASE}/{name}", headers={"User-Agent": "StockWatch-educational-project/1.0"})
    print(f"Downloading {name} ({expected_size / 1_000_000:.1f} MB)...", flush=True)
    with urllib.request.urlopen(req, timeout=120) as response, partial.open("wb") as out:
        while block := response.read(1024 * 1024):
            out.write(block)
    if partial.stat().st_size != expected_size:
        raise ValueError(f"Incomplete {name}: {partial.stat().st_size} bytes")
    os.replace(partial, target)
    return target


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=200)
    args = p.parse_args()
    if not 1 <= args.limit <= 5000:
        p.error("--limit must be 1..5000")
    cache = PROJECT / "data" / "raw"
    output = PROJECT / "backend" / "data"
    cache.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    files = [download(name, size, cache) for name, size in FILES.items()]
    con = duckdb.connect()
    # Paths are generated locally, not accepted from a model or an HTTP client.
    # DuckDB does not support bound parameters in CREATE VIEW. These paths are
    # locally generated above, not external input; quote SQL literals safely.
    sql_train, sql_eval = ("'" + str(path).replace("'", "''") + "'" for path in files)
    con.execute(f"CREATE VIEW train AS SELECT * FROM read_parquet({sql_train})")
    con.execute(f"CREATE VIEW all_records AS SELECT * FROM read_parquet({sql_train}) UNION ALL SELECT * FROM read_parquet({sql_eval})")
    earliest = con.execute("SELECT min(dt) FROM train").fetchone()[0]
    con.execute("""CREATE TEMP TABLE selected_pairs AS
        WITH pairs AS (SELECT DISTINCT store_id, product_id FROM train WHERE dt = ?),
        numbered AS (SELECT *, row_number() OVER (PARTITION BY store_id ORDER BY product_id) AS rn FROM pairs)
        SELECT store_id, product_id FROM numbered
        ORDER BY floor((rn - 1) / 10), store_id, rn LIMIT ?""", [earliest, args.limit])
    result = con.execute("SELECT a.store_id,a.product_id,a.dt,a.stock_hour6_22_cnt,a.sale_amount, a.hours_stock_status FROM all_records a JOIN selected_pairs p USING(store_id, product_id) ORDER BY a.store_id,a.product_id,a.dt")
    csv_path = output / "freshretail_sample.csv"
    import csv
    count = 0
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["store_id", "product_id", "dt", "stock_hour6_22_cnt", "sale_amount", "hours_stock_status"])
        while rows := result.fetchmany(10000):
            for row in rows:
                writer.writerow([*row[:5], json.dumps(row[5], ensure_ascii=False)])
                count += 1
    digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    metadata = {"source": "FreshRetailNet-50K", "kind": "real", "citation": "https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K", "revision": REVISION, "license": "CC-BY-4.0", "selection": f"first {args.limit} pairs on training start {earliest}, ordered by 10-product blocks per store; all available train/eval dates", "rows": count, "sha256": digest}
    (output / "source.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved {count} authentic rows to {csv_path}")


if __name__ == "__main__":
    main()
