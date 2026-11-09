"""StockWatch historical replay. All calculations are deterministic and read-only."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sqlite3
import io
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
REQUIRED = {"store_id", "product_id", "dt", "stock_hour6_22_cnt", "sale_amount"}


def data_path() -> Path:
    return Path(os.getenv("FRESHRETAIL_PATH", str(BASE / "data" / "freshretail_sample.csv")))


def db_path() -> Path:
    return Path(os.getenv("STOCKWATCH_DB", str(BASE / "data" / "stockwatch.sqlite3")))


@contextmanager
def connect():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.executescript("""
        CREATE TABLE IF NOT EXISTS batches (id TEXT PRIMARY KEY, as_of_date TEXT NOT NULL, target_date TEXT NOT NULL, k INTEGER NOT NULL, dataset_sha TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES batches(id), store_id TEXT NOT NULL, product_id TEXT NOT NULL, score REAL NOT NULL, rank INTEGER NOT NULL, history_days INTEGER NOT NULL, stockout_days_7d INTEGER NOT NULL, stockout_hours_7d REAL NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING', UNIQUE(batch_id,store_id,product_id));
        CREATE TABLE IF NOT EXISTS reviews (id INTEGER PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id), action TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    """)
    if "method_key" not in {r[1] for r in c.execute("PRAGMA table_info(batches)")}:
        c.execute("ALTER TABLE batches ADD COLUMN method_key TEXT NOT NULL DEFAULT 'rule'")
    if "model_version" not in {r[1] for r in c.execute("PRAGMA table_info(batches)")}:
        c.execute("ALTER TABLE batches ADD COLUMN model_version TEXT")
    if "model_sha" not in {r[1] for r in c.execute("PRAGMA table_info(batches)")}:
        c.execute("ALTER TABLE batches ADD COLUMN model_sha TEXT")
    try:
        with c:
            yield c
    finally:
        c.close()


class DataContractError(ValueError):
    def __init__(self, report):
        super().__init__("数据合同检查失败，请查看质量报告。")
        self.report = report


def read_data(raw=None):
    path = data_path()
    if raw is None:
        if not path.is_file():
            raise FileNotFoundError("真实数据尚未导入。请设置 FRESHRETAIL_PATH 或运行数据准备脚本。")
        raw = path.read_bytes()
    with io.StringIO(raw.decode('utf-8-sig'), newline='') as f:
        reader = csv.DictReader(f)
        if not REQUIRED.issubset(set(reader.fieldnames or [])):
            raise ValueError("CSV 缺少必要字段: " + ", ".join(sorted(REQUIRED - set(reader.fieldnames or []))))
        rows = []
        keys = set()
        for n, row in enumerate(reader, 2):
            try:
                day = date.fromisoformat(row["dt"].strip()).isoformat()
                store, product = str(row["store_id"]).strip(), str(row["product_id"]).strip()
                stock = float(row["stock_hour6_22_cnt"]) if row["stock_hour6_22_cnt"] and row["stock_hour6_22_cnt"].strip() else None
                sale = float(row["sale_amount"]) if row["sale_amount"] and row["sale_amount"].strip() else None
            except (ValueError, TypeError, KeyError) as exc:
                raise ValueError(f"第 {n} 行日期或数值无效") from exc
            key = (store, product, day)
            if key in keys:
                raise ValueError(f"重复的门店、商品和日期记录: {key}")
            keys.add(key)
            rows.append({"store_id": store, "product_id": product, "dt": day, "stock_hour6_22_cnt": stock, "sale_amount": sale})
    if not rows:
        raise ValueError("CSV 文件为空")
    return rows


def dataset_info():
    path = data_path()
    try:
        rows = read_data()
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        source_file = path.parent / "source.json"
        info = json.loads(source_file.read_text(encoding="utf-8")) if source_file.exists() else {}
        return {"available": True, "source": info.get("source", "外部 CSV（来源未核实）"), "kind": info.get("kind", "unknown"), "citation": info.get("citation"), "row_count": len(rows), "min_date": min(r["dt"] for r in rows), "max_date": max(r["dt"] for r in rows), "dataset_sha": sha}
    except (FileNotFoundError, ValueError, OSError, json.JSONDecodeError) as exc:
        return {"available": False, "source": "尚未载入", "row_count": 0, "min_date": None, "max_date": None, "error": str(exc)}


def available_dates():
    return sorted({r["dt"] for r in read_data()})


def build_batch(as_of_date: str, k: int, method: str = "rule"):
    end = date.fromisoformat(as_of_date)
    if k < 1 or k > 1000:
        raise ValueError("k 必须在 1 到 1000 之间")
    from .data_contract import validate_bytes
    try:
        raw = data_path().read_bytes()
    except FileNotFoundError:
        raise DataContractError(validate_bytes(None, as_of=as_of_date, read_error='file_not_found')) from None
    except OSError:
        raise DataContractError(validate_bytes(None, as_of=as_of_date, read_error='file_read_error')) from None
    quality = validate_bytes(raw, as_of=as_of_date)
    if quality['status'] == 'fail':
        raise DataContractError(quality)
    rows = read_data(raw)
    if as_of_date not in {r["dt"] for r in rows}:
        raise ValueError("回放日期不在数据中")
    dataset_sha = quality['dataset_sha256']
    if method not in {"rule", "model"}:
        raise ValueError("method 必须是 rule 或 model")
    model = None
    model_fingerprint = "freq7-v1"
    if method == "model":
        from . import risk_model
        model = risk_model.load_model(dataset_sha, as_of_date)
        model_fingerprint = hashlib.sha256(risk_model.MODEL_PATH.read_bytes()).hexdigest()
    batch_id = hashlib.sha256(f"{dataset_sha}|{as_of_date}|{k}|{method}|{model_fingerprint}".encode()).hexdigest()[:20]
    start = (end - timedelta(days=6)).isoformat()
    grouped = {}
    for row in rows:
        if start <= row["dt"] <= as_of_date:
            grouped.setdefault((row["store_id"], row["product_id"]), []).append(row)
    candidates = []
    for (store, product), hist in grouped.items():
        if len(hist) != 7 or any(r["stock_hour6_22_cnt"] is None for r in hist):
            continue
        n = sum(r["stock_hour6_22_cnt"] > 0 for r in hist)
        h = sum(r["stock_hour6_22_cnt"] for r in hist)
        if method == "model":
            from . import risk_model
            values = risk_model.features(hist)
            if values is None:
                continue
            score = risk_model.score(model, values)
        else:
            score = n / 7
        candidates.append((store, product, n, h, score))
    candidates.sort(key=lambda x: (-x[4], x[0], x[1]))
    with connect() as c:
        c.execute("INSERT OR IGNORE INTO batches (id,as_of_date,target_date,k,dataset_sha,method_key,model_version,model_sha) VALUES (?,?,?,?,?,?,?,?)", (batch_id, as_of_date, (end + timedelta(days=1)).isoformat(), k, dataset_sha, method, model["model_version"] if model else "freq7-v1", model_fingerprint))
        for rank, (store, product, n, hours, score) in enumerate(candidates[:k], 1):
            case_id = hashlib.sha256(f"{batch_id}|{store}|{product}".encode()).hexdigest()[:20]
            c.execute("INSERT OR IGNORE INTO cases (id,batch_id,store_id,product_id,score,rank,history_days,stockout_days_7d,stockout_hours_7d) VALUES (?,?,?,?,?,?,?,?,?)", (case_id,batch_id,store,product,score,rank,7,n,hours))
    label = "过去7天缺货天数 / 7（规则分数，非概率）" if method == "rule" else "逻辑回归模型风险分数（未校准，非可靠概率）"
    return {"batch_id": batch_id, "status": "completed", "as_of_date": as_of_date, "target_date": (end + timedelta(days=1)).isoformat(), "candidate_count": len(candidates), "excluded_count": len(grouped)-len(candidates), "method": label, "method_key": method, "dataset_sha256": dataset_sha, "data_quality": quality}


def get_batch(batch_id):
    with connect() as c:
        row = c.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
        return dict(row) if row else None


def get_cases(batch_id):
    if get_batch(batch_id) is None:
        return None
    with connect() as c:
        items = [dict(r) for r in c.execute("SELECT * FROM cases WHERE batch_id=? ORDER BY rank", (batch_id,))]
    return {"batch_id": batch_id, "items": items, "next_cursor": None}


def evaluate_batch(batch_id):
    batch = get_batch(batch_id)
    if batch is None:
        return None
    rows = read_data()
    if hashlib.sha256(data_path().read_bytes()).hexdigest() != batch["dataset_sha"]:
        raise ValueError("数据版本与原始批次不一致，请重新生成批次")
    start = (date.fromisoformat(batch["as_of_date"]) - timedelta(days=6)).isoformat()
    histories, labels = {}, {}
    for row in rows:
        key = (row["store_id"], row["product_id"])
        if start <= row["dt"] <= batch["as_of_date"]:
            histories.setdefault(key, []).append(row)
        elif row["dt"] == batch["target_date"]:
            labels[key] = row["stock_hour6_22_cnt"]
    eligible = [key for key, hist in histories.items() if len(hist) == 7 and all(r["stock_hour6_22_cnt"] is not None for r in hist)]
    if batch["method_key"] == "model":
        from . import risk_model
        eligible = [key for key in eligible if risk_model.features(histories[key]) is not None]
    known = {key for key in eligible if labels.get(key) is not None}
    cases = get_cases(batch_id)["items"]
    selected = [(x["store_id"], x["product_id"]) for x in cases]
    selected_known = [key for key in selected if key in known]
    hits = sum(labels[key] > 0 for key in selected_known)
    positives = sum(labels[key] > 0 for key in known)
    return {"batch_id": batch_id, "target_date": batch["target_date"], "eligible_count": len(eligible), "known_label_count": len(known), "unknown_label_count": len(eligible)-len(known), "selected_count": len(selected), "selected_known_count": len(selected_known), "hits": hits, "positive_count": positives, "precision_at_k_known": hits/len(selected_known) if selected_known else None, "recall_at_k_known": hits/positives if positives else None, "note": "仅对有真实次日标签的对象计算；历史回放并不能证明干预减少缺货。"}


def get_case(case_id):
    with connect() as c:
        row = c.execute("SELECT c.*, b.as_of_date, b.target_date, b.dataset_sha, b.method_key, b.model_version, b.model_sha FROM cases c JOIN batches b ON b.id=c.batch_id WHERE c.id=?", (case_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["method"] = "过去7天缺货天数 / 7（规则分数，非概率）" if result["method_key"] == "rule" else "逻辑回归模型风险分数（未校准，非可靠概率）"
        return result


def get_history(case_id, days=7):
    case = get_case(case_id)
    if case is None:
        raise ValueError("工单不存在")
    if not 1 <= days <= 90:
        raise ValueError("days 必须在 1 到 90 之间")
    current_sha = hashlib.sha256(data_path().read_bytes()).hexdigest()
    if current_sha != case["dataset_sha"]:
        raise ValueError("数据版本与原始批次不一致，请重新生成批次")
    start = (date.fromisoformat(case["as_of_date"]) - timedelta(days=days - 1)).isoformat()
    rows = [r for r in read_data() if r["store_id"] == case["store_id"] and r["product_id"] == case["product_id"] and start <= r["dt"] <= case["as_of_date"]]
    return sorted(rows, key=lambda r: r["dt"])


def review_case(case_id, action, note):
    if action not in {"PENDING", "REVIEWED", "NEEDS_FOLLOWUP", "CLOSED"}:
        raise ValueError("无效的状态")
    if len(note) > 2000:
        raise ValueError("备注过长")
    with connect() as c:
        if c.execute("SELECT 1 FROM cases WHERE id=?", (case_id,)).fetchone() is None:
            return None
        c.execute("UPDATE cases SET status=? WHERE id=?", (action,case_id))
        c.execute("INSERT INTO reviews (case_id,action,note) VALUES (?,?,?)", (case_id,action,note))
    return {"case_id": case_id, "status": action}
