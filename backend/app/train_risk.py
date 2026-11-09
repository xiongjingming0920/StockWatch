"""Train and evaluate a frozen logistic regression on chronological targets.

Run from backend: python -m app.train_risk
The validation period establishes model availability; testing never updates weights.
"""
from __future__ import annotations
import hashlib
import json
import math
from collections import defaultdict
from datetime import date, timedelta
from . import risk_model as rm, services

TRAIN_END = "2024-06-10"
VAL_START, VAL_END = "2024-06-11", "2024-06-20"
TEST_START, TEST_END = "2024-06-21", "2024-07-02"
K = 50


def samples(rows):
    by_item = defaultdict(dict)
    for row in rows:
        by_item[(row["store_id"], row["product_id"])][row["dt"]] = row
    out = []
    for key, days in sorted(by_item.items()):
        for target, target_row in sorted(days.items()):
            if target_row["stock_hour6_22_cnt"] is None:
                continue
            target_dt = date.fromisoformat(target)
            hist = [days.get((target_dt - timedelta(days=i)).isoformat()) for i in range(7, 0, -1)]
            if any(row is None for row in hist):
                continue
            x = rm.features(hist)
            if x is None:
                continue
            out.append({"key": key, "target": target, "x": x, "y": int(target_row["stock_hour6_22_cnt"] > 0), "rule": x[0] / 7})
    return out


def fit(train):
    if not train or len({r["y"] for r in train}) != 2:
        raise ValueError("训练集需要同时包含缺货和未缺货样本")
    n, width = len(train), len(rm.FEATURE_NAMES)
    means = [sum(r["x"][j] for r in train) / n for j in range(width)]
    scales = [math.sqrt(sum((r["x"][j]-means[j])**2 for r in train)/n) or 1.0 for j in range(width)]
    normalized = [([(v-means[j])/scales[j] for j,v in enumerate(r["x"])], r["y"]) for r in train]
    weights, bias = [0.0]*width, 0.0
    learning_rate, l2, epochs = 0.15, 0.01, 160
    for _ in range(epochs):
        grad, grad_b = [0.0]*width, 0.0
        for x, y in normalized:
            err = rm.sigmoid(bias + sum(w*v for w,v in zip(weights,x))) - y
            grad_b += err
            for j in range(width):
                grad[j] += err*x[j]
        bias -= learning_rate*grad_b/n
        weights = [w-learning_rate*(g/n+l2*w) for w,g in zip(weights,grad)]
    return {"means":means, "scales":scales, "weights":weights, "bias":bias, "training_config":{"optimizer":"batch gradient descent", "epochs":epochs, "learning_rate":learning_rate, "l2":l2}}


def evaluate(subset, model):
    grouped = defaultdict(list)
    for row in subset:
        grouped[row["target"]].append(row)
    results = {}
    for method in ("rule", "model"):
        daily = []
        for target, rows in sorted(grouped.items()):
            ranked = sorted(rows, key=lambda r: (-(r["rule"] if method == "rule" else rm.score(model,r["x"])),r["key"]))
            chosen = ranked[:K]
            hits = sum(r["y"] for r in chosen)
            positives = sum(r["y"] for r in rows)
            daily.append({"target_date":target, "candidates":len(rows), "selected":len(chosen), "hits":hits, "positives":positives, "precision_at_k":hits/len(chosen) if chosen else None, "recall_at_k":hits/positives if positives else None})
        p = [r["precision_at_k"] for r in daily if r["precision_at_k"] is not None]
        rec = [r["recall_at_k"] for r in daily if r["recall_at_k"] is not None]
        results[method] = {"mean_precision_at_k":sum(p)/len(p) if p else None, "mean_recall_at_k":sum(rec)/len(rec) if rec else None, "days":len(daily), "daily":daily}
    return results


def main():
    rows = services.read_data()
    all_samples = samples(rows)
    train = [r for r in all_samples if r["target"] <= TRAIN_END]
    val = [r for r in all_samples if VAL_START <= r["target"] <= VAL_END]
    test = [r for r in all_samples if TEST_START <= r["target"] <= TEST_END]
    if not val or not test:
        raise ValueError("数据不覆盖指定验证/测试日期；不能生成此模型")
    model = fit(train)
    model.update({"model_version":"logreg-7d-v1", "dataset_sha":hashlib.sha256(services.data_path().read_bytes()).hexdigest(), "training_target_end":TRAIN_END, "validation_target_start":VAL_START, "validation_target_end":VAL_END, "test_target_start":TEST_START, "test_target_end":TEST_END, "available_from_as_of":VAL_END, "features":rm.FEATURE_NAMES, "train_samples":len(train), "validation_samples":len(val), "test_samples":len(test), "score_note":"逻辑回归输出的未校准风险分数；非已校准概率", "report":{"k":K, "validation":evaluate(val,model), "test":evaluate(test,model), "caveat":"真实历史数据上的离线回放；非真实干预收益。"}})
    rm.MODEL_PATH.parent.mkdir(parents=True,exist_ok=True)
    rm.MODEL_PATH.write_text(json.dumps(model,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"model":str(rm.MODEL_PATH),"train":len(train),"validation":len(val),"test":len(test),"test_summary":{m:{k:v for k,v in report.items() if k != 'daily'} for m,report in model['report']['test'].items()}},ensure_ascii=False,indent=2))

if __name__ == "__main__":
    main()
