import numpy as np
from collections import defaultdict
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

item_records = defaultdict(lambda: {
    "count":          0,
    "confidences":    [],
    "result_counts":  [],
    "prices":         [],
})

scaler = StandardScaler()
kmeans = None
LABELS = ["Cold", "Rising", "Trending", "Viral"]


def _parse_price(price_str: str) -> float:
    try:
        return float("".join(c for c in price_str if c.isdigit() or c == "."))
    except Exception:
        return 0.0


def _build_feature_vector(record: dict) -> list:
    count      = record["count"]
    avg_conf   = float(np.mean(record["confidences"])) if record["confidences"] else 0.0
    avg_demand = float(np.mean(record["result_counts"])) if record["result_counts"] else 0.0
    avg_price  = float(np.mean(record["prices"])) if record["prices"] else 0.0
    return [count, avg_conf, avg_demand, avg_price]


def update_trend_score(item_type: str, confidence: str, products: list) -> dict:
    global kmeans

    conf_map = {"high": 1.0, "medium": 0.5, "low": 0.2}
    conf_val = conf_map.get(confidence, 0.5)

    rec = item_records[item_type]
    rec["count"] += 1
    rec["confidences"].append(conf_val)
    rec["result_counts"].append(len(products))

    prices = [_parse_price(p.get("price", "0")) for p in products if p.get("price")]
    if prices:
        rec["prices"].append(np.mean(prices))

    if len(item_records) < 2:
        return {"trend_label": "Cold", "trend_score": 0, "item_count": rec["count"]}

    items    = list(item_records.keys())
    X        = np.array([_build_feature_vector(item_records[i]) for i in items])
    X_scaled = scaler.fit_transform(X)

    n_clusters = min(4, len(items))
    kmeans     = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    kmeans.fit(X_scaled)

    cluster_scores = {}
    for cluster_id in range(n_clusters):
        mask = kmeans.labels_ == cluster_id
        if not mask.any():
            continue
        cluster_scores[cluster_id] = float(X[mask, 0].mean() + X[mask, 2].mean())

    ranked           = sorted(cluster_scores, key=cluster_scores.get)
    label_list       = LABELS[:n_clusters]
    cluster_to_label = {}
    for rank, cluster_id in enumerate(ranked):
        cluster_to_label[cluster_id] = label_list[rank]

    item_idx     = items.index(item_type)
    item_cluster = int(kmeans.labels_[item_idx])
    trend_label  = cluster_to_label.get(item_cluster, "Cold")

    label_to_score = {"Cold": 10, "Rising": 35, "Trending": 70, "Viral": 95}
    trend_score    = label_to_score.get(trend_label, 0)

    return {"trend_label": trend_label, "trend_score": trend_score, "item_count": rec["count"]}


def reset():
    global kmeans
    item_records.clear()
    kmeans = None
