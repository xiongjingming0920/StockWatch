"""Auditable fixed-feature logistic risk model; no runtime ML dependency."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "risk_model.json"
FEATURE_NAMES = ["stockout_days_7d", "stockout_hours_7d", "stockout_on_t", "sales_mean_7d"]


def features(hist):
    hist = sorted(hist, key=lambda x: x["dt"])
    if len(hist) != 7 or any(r["stock_hour6_22_cnt"] is None or r["sale_amount"] is None for r in hist):
        return None
    if any(not math.isfinite(r["stock_hour6_22_cnt"]) or not math.isfinite(r["sale_amount"]) for r in hist):
        return None
    return [sum(r["stock_hour6_22_cnt"] > 0 for r in hist), sum(r["stock_hour6_22_cnt"] for r in hist), float(hist[-1]["stock_hour6_22_cnt"] > 0), sum(r["sale_amount"] for r in hist) / 7]


def sigmoid(x):
    return 1 / (1 + math.exp(-max(-30.0, min(30.0, x))))


def score(model, values):
    z = model["bias"] + sum(w * ((x - m) / s) for x, m, s, w in zip(values, model["means"], model["scales"], model["weights"]))
    return sigmoid(z)


def load_model(dataset_sha=None, as_of_date=None):
    if not MODEL_PATH.exists():
        raise ValueError("尚未训练风险模型；请先运行 python -m app.train_risk")
    model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    if dataset_sha and model["dataset_sha"] != dataset_sha:
        raise ValueError("模型训练数据版本与当前数据不一致；请重新训练或切回规则")
    if as_of_date and as_of_date < model["available_from_as_of"]:
        raise ValueError(f"模型验证结束于 {model['available_from_as_of']}；此日期之前不能使用模型回放，以防未来信息泄漏")
    return model


def model_metadata():
    model = load_model()
    return {k: model[k] for k in ("model_version", "dataset_sha", "training_target_end", "validation_target_start", "validation_target_end", "test_target_start", "test_target_end", "available_from_as_of", "features", "report")}
