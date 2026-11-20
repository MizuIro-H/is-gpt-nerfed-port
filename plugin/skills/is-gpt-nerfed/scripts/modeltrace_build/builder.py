"""Pure-Python port of ModelTrace's bank builder (bank_builder.fit_robust_artifacts / calibration_records / fit_beta /
build_bank at commit 6cd4a8ff0f3f4e49d6d6969dd2fbadfa1569fde2; MIT, see plugin/assets/modeltrace/LICENSE-ModelTrace.txt).

The frozen core stays numpy-free (it is a one-file executable that every Codex hook unpacks). The only linear
algebra the builder needs is the top-2 right singular vectors of a (#environments x features) matrix, obtained here
from the eigenvectors of its small Gram matrix. tests/test_bank_builder.py checks parity against the numpy original.
"""
from __future__ import annotations

import itertools
import math
from collections import Counter
from datetime import datetime, timezone

import modeltrace_core as core

ORDERED_BLOCK_WEIGHT = core.ORDERED_BLOCK_WEIGHT


def _mean_rows(rows: list[list[float]]) -> list[float]:
    n = len(rows)
    return [sum(col) / n for col in zip(*rows)]


def _std_rows(rows: list[list[float]], mean: list[float]) -> list[float]:
    n = len(rows)
    return [math.sqrt(sum((v - m) ** 2 for v in col) / n) for col, m in zip(zip(*rows), mean)]


def _norm(v: list[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def _unit(v: list[float]) -> list[float]:
    s = max(_norm(v), 1e-12)
    return [x / s for x in v]


def _jacobi_eigen(a: list[list[float]], sweeps: int = 100) -> tuple[list[float], list[list[float]]]:
    """Eigenvalues and eigenvectors (columns of the returned matrix) of a small symmetric matrix."""
    n = len(a)
    a = [row[:] for row in a]
    v = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for _ in range(sweeps):
        off = sum(a[i][j] ** 2 for i in range(n) for j in range(n) if i != j)
        if off < 1e-30:
            break
        for p in range(n - 1):
            for q in range(p + 1, n):
                if abs(a[p][q]) < 1e-300:
                    continue
                theta = (a[q][q] - a[p][p]) / (2 * a[p][q])
                t = (1.0 if theta >= 0 else -1.0) / (abs(theta) + math.sqrt(theta * theta + 1))
                c = 1 / math.sqrt(t * t + 1)
                s = t * c
                for k in range(n):
                    akp, akq = a[k][p], a[k][q]
                    a[k][p], a[k][q] = c * akp - s * akq, s * akp + c * akq
                for k in range(n):
                    apk, aqk = a[p][k], a[q][k]
                    a[p][k], a[q][k] = c * apk - s * aqk, s * apk + c * aqk
                for k in range(n):
                    vkp, vkq = v[k][p], v[k][q]
                    v[k][p], v[k][q] = c * vkp - s * vkq, s * vkp + c * vkq
    return [a[i][i] for i in range(n)], v


def _nuisance_basis(offsets: list[list[float]]) -> list[list[float]]:
    """Top (≤2) right singular vectors of `offsets`, as numpy.linalg.svd + the builder's rank rule would pick."""
    if len(offsets) <= 1:
        return []
    gram = [[sum(x * y for x, y in zip(r1, r2)) for r2 in offsets] for r1 in offsets]
    values, vectors = _jacobi_eigen(gram)
    order = sorted(range(len(values)), key=lambda i: values[i], reverse=True)
    singular = [math.sqrt(max(values[i], 0.0)) for i in order]
    if not singular[0]:
        return []
    rank = min(2, sum(1 for s in singular if s > singular[0] * 1e-8))
    basis = []
    for i, s in zip(order[:rank], singular[:rank]):
        u = [vectors[r][i] for r in range(len(offsets))]
        basis.append([sum(u[r] * offsets[r][c] for r in range(len(offsets))) / s for c in range(len(offsets[0]))])
    return basis


def _project_out(rows: list[list[float]], basis: list[list[float]]) -> list[list[float]]:
    out = []
    for row in rows:
        r = row
        coeffs = [sum(x * b for x, b in zip(row, vec)) for vec in basis]
        if basis:
            r = [x - sum(c * vec[i] for c, vec in zip(coeffs, basis)) for i, x in enumerate(row)]
        out.append(r)
    return out


def _standardized(features: list[list[float]]) -> tuple[list[list[float]], list[float], list[float]]:
    mean = _mean_rows(features)
    scale = [s if s >= 1e-12 else 1.0 for s in _std_rows(features, mean)]
    return [[(x - m) / s for x, m, s in zip(f, mean, scale)] for f in features], mean, scale


def _offsets(standardized: list[list[float]], envs: list[str], nuisance_environments: list[str]) -> list[list[float]]:
    means = [_mean_rows([r for r, e in zip(standardized, envs) if e == env]) for env in nuisance_environments]
    center = _mean_rows(means)
    return [[x - c for x, c in zip(m, center)] for m in means]


def fit_robust_artifacts(rows: list[dict], model_ids: list[str]) -> dict:
    environments = sorted({row["condition_id"] for row in rows})
    complete = [e for e in environments if {r["source"] for r in rows if r["condition_id"] == e} == set(model_ids)]
    robust_rows = [r for r in rows if r["condition_id"] in complete] if complete else rows
    labels = [r["source"] for r in robust_rows]
    envs = [r.get("nuisance_condition_id", r["condition_id"]) for r in robust_rows]
    nuisance_environments = sorted(set(envs))

    standardized, feature_mean, feature_scale = _standardized([r["_hellinger"] for r in robust_rows])
    basis = _nuisance_basis(_offsets(standardized, envs, nuisance_environments))
    standardized = _project_out(standardized, basis)
    centroids = [_unit(_mean_rows([s for s, l in zip(standardized, labels) if l == m])) for m in model_ids]

    ordered_raw, ordered_mean, ordered_scale = _standardized([r["_ordered"] for r in robust_rows])
    ordered_basis = _nuisance_basis(_offsets(ordered_raw, envs, nuisance_environments))
    ordered_projected = _project_out(ordered_raw, ordered_basis)
    ordered_centroids = [_unit(_mean_rows([s for s, l in zip(ordered_projected, labels) if l == m])) for m in model_ids]
    environment_centroids = []
    for env in complete or [None]:
        environment_centroids.append([
            _unit(_mean_rows([s for s, r in zip(ordered_raw, robust_rows)
                              if (env is None or r["condition_id"] == env) and r["source"] == m]))
            for m in model_ids])

    return {
        "model_order": model_ids,
        "robust_ready": bool(complete),
        "training_rows": len(robust_rows),
        "complete_environments": complete,
        "hellinger": {
            "feature_mean": feature_mean,
            "feature_scale": feature_scale,
            "nuisance_rank": len(basis),
            "nuisance_environments": nuisance_environments,
            "nuisance_basis": basis,
            "centroids": centroids,
        },
        "ordered_blocks": {
            "weight": ORDERED_BLOCK_WEIGHT,
            "feature": "four position blocks x 16 value bins plus final-digit distribution",
            "feature_mean": ordered_mean,
            "feature_scale": ordered_scale,
            "nuisance_rank": len(ordered_basis),
            "nuisance_basis": ordered_basis,
            "centroids": ordered_centroids,
            "environment_centroids": environment_centroids,
        },
    }


def calibration_records(rows: list[dict], model_ids: list[str], query_count: int) -> list[tuple[list[float], int]]:
    records = []
    for condition in sorted({r["condition_id"] for r in rows}):
        challenge_ids = sorted({r["challenge_id"] for r in rows if r["condition_id"] == condition})
        challenge_ids = [c for c in challenge_ids
                         if all(any(r["source"] == m and r["challenge_id"] == c for r in rows) for m in model_ids)]
        if len(challenge_ids) < query_count:
            continue
        for held_ids in itertools.combinations(challenge_ids, query_count):
            held_set = set(held_ids)
            bank = {"robust": fit_robust_artifacts([r for r in rows if r["challenge_id"] not in held_set], model_ids)}
            for truth, model_id in enumerate(model_ids):
                held = [r for r in rows if r["source"] == model_id and r["challenge_id"] in held_set]
                if len(held) != query_count:
                    continue
                scores = [core.robust_score_numbers(r["numbers"], bank) for r in held]
                records.append(([sum(s[i] for s in scores) / query_count for i in range(len(model_ids))], truth))
    return records


def fit_beta(records: list[tuple[list[float], int]]) -> tuple[float, float]:
    best_beta, best_loss = 1.0, float("inf")
    for step in range(801):
        beta = math.exp(math.log(0.05) + step * (math.log(12.0) - math.log(0.05)) / 800)
        loss = 0.0
        for scores, truth in records:
            scaled = [beta * v for v in scores]
            top = max(scaled)
            loss += top + math.log(sum(math.exp(v - top) for v in scaled)) - scaled[truth]
        loss /= len(records)
        if loss < best_loss:
            best_beta, best_loss = beta, loss
    return best_beta, best_loss


def prepare_rows(rows: list[dict]) -> list[dict]:
    """Strictly valid rows with parsed numbers, counts and the two cached feature vectors."""
    out = []
    for row in rows:
        if not row.get("strict_valid") or str(row.get("strict_valid")) == "False":
            continue
        numbers = core.parse_numbers(row["text"])
        counts = core.count_numbers(numbers)
        out.append({**row, "source": row.get("source") or row["model_id"], "numbers": numbers, "counts": counts,
                    "_hellinger": core.hellinger_feature(counts), "_ordered": core.ordered_block_feature(numbers)})
    return out


def build_bank(rows: list[dict], fallback_calibration: dict | None = None, progress=None) -> dict:
    model_ids = list(dict.fromkeys(r["source"] for r in rows))
    models = []
    for model_id in model_ids:
        selected = [r for r in rows if r["source"] == model_id]
        models.append({
            "id": model_id, "display_name": model_id, "family": selected[0].get("family_id"),
            "family_name": selected[0].get("family_name"), "response_count": len(selected),
            "valid_number_count": sum(len(r["numbers"]) for r in selected),
            "conditions": dict(Counter(r["condition_id"] for r in selected)),
            "counts": [sum(r["counts"][i] for r in selected) for i in range(core.DIMENSION)],
        })
    robust = fit_robust_artifacts(rows, model_ids)
    calibration = {}
    for query_count in (1, 2, 3):
        if progress:
            progress(query_count)
        records = calibration_records(rows, model_ids, query_count)
        key = str(query_count)
        if records:
            beta, nll = fit_beta(records)
            picks = [(t, max(range(len(s)), key=lambda i: s[i])) for s, t in records]
            correct = sum(t == p for t, p in picks)
            # Not in ModelTrace's schema: which held-out model was taken for which, so an enrollment can say when
            # a new model is indistinguishable from one already known instead of only lowering the accuracy.
            confusions = Counter(f"{model_ids[t]}->{model_ids[p]}" for t, p in picks if t != p)
            per_model = Counter(model_ids[t] for t, _ in picks)
            calibration[key] = {"beta": beta, "cv_accuracy": correct / len(records), "cv_correct": correct,
                                "cv_samples": len(records), "cv_nll": nll, "fallback": False,
                                "confusions": dict(confusions), "samples_per_model": dict(per_model)}
        else:
            previous = (fallback_calibration or {}).get(key)
            calibration[key] = {**(previous or {"beta": 1.0, "cv_accuracy": None, "cv_correct": 0, "cv_samples": 0,
                                                "cv_nll": None}), "fallback": True}
    return {
        "schema": "robust-number-fingerprint-bank",
        "built_at": datetime.now(timezone.utc).isoformat(),
        "method": {
            "name": "Ordered-block + nuisance-Hellinger",
            "range": [1, 355],
            "alpha": core.ALPHA,
            "ordered_block_weight": ORDERED_BLOCK_WEIGHT,
            "parser": "longest digit run; alphabetic separators split runs; retain values 1..355",
            "response_score": "shared nuisance-Hellinger and ordered-block environment/nuisance fusion",
            "aggregation": "mean of response-wise fused class z-scores",
            "probability": "uniform-prior softmax with fusion-specific grouped cross-validation temperature scaling",
        },
        "recommended_queries": 3,
        "minimum_valid_numbers": 80,
        "source_scope": "Reference outputs enrolled for the listed model labels.",
        "providers": sorted({r.get("provider") for r in rows if r.get("provider")}),
        "models": models,
        "robust": robust,
        "calibration": calibration,
    }
