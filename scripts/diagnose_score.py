"""SCRI v0.4.1 スコア診断スクリプト
Japan スコアの内訳分析と重み検証を行う。

実行: cd /path/to/supply-chain-risk && python scripts/diagnose_score.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scoring.engine import SupplierRiskScore, calculate_risk_score


def diagnose_japan():
    """Japan の全24次元スコアを詳細診断"""
    print("=" * 70)
    print("=== Japan Risk Score Breakdown ===")
    print("=" * 70)

    score = calculate_risk_score("diag_japan", "Diagnosis Japan", country="Japan", location="Japan")
    d = score.to_dict()

    # 重み取得
    weights = SupplierRiskScore.WEIGHTS

    # 全次元表示
    print(f"\n{'Dimension':<20} {'Raw':>6} {'Weight':>8} {'Contribution':>14} {'In Formula':>12}")
    print("-" * 70)

    total_weight = 0.0
    weighted_sum = 0.0

    for dim, val in d["scores"].items():
        w = weights.get(dim, 0)
        contrib = val * w
        total_weight += w
        weighted_sum += contrib
        in_formula = "YES" if dim in weights else "INFO ONLY"
        marker = ""
        if dim == "climate_risk":
            marker = " <- NEW dim23"
        elif dim == "cyber_risk":
            marker = " <- NEW dim24"
        elif dim == "sanctions":
            marker = " <- separate logic"
        elif dim == "japan_economy":
            marker = " <- info only"
        print(f"{dim:<20} {val:>6} {w:>8.3f} {contrib:>14.3f} {in_formula:>12}{marker}")

    print("-" * 70)
    print(f"{'Total weight':<20} {'':>6} {total_weight:>8.3f}")
    print(f"{'Weighted sum':<20} {'':>6} {'':>8} {weighted_sum:>14.3f}")

    # 重み合計チェック
    print(f"\n{'=' * 70}")
    print(f"WEIGHT SUM CHECK: {total_weight:.4f}", end="")
    if abs(total_weight - 1.0) < 0.001:
        print("  [OK - sums to 1.0]")
    else:
        print(f"  [PROBLEM - expected 1.0, delta = {total_weight - 1.0:+.4f}]")

    # composite score 再計算
    scores_for_calc = {
        dim: val for dim, val in d["scores"].items()
        if dim in weights
    }
    sorted_vals = sorted(scores_for_calc.values(), reverse=True)
    peak = sorted_vals[0] if sorted_vals else 0
    second_peak = sorted_vals[1] if len(sorted_vals) > 1 else 0

    composite = int(weighted_sum * 0.6 + peak * 0.30 + second_peak * 0.10)
    sanction_bonus = d["scores"].get("sanctions", 0) // 2 if d["scores"].get("sanctions", 0) > 0 else 0
    final = min(100, composite + sanction_bonus)

    print(f"\n=== Composite Score Calculation ===")
    print(f"  weighted_sum * 0.6 = {weighted_sum:.3f} * 0.6 = {weighted_sum * 0.6:.3f}")
    print(f"  peak * 0.30        = {peak} * 0.30 = {peak * 0.30:.3f}  (dim: {max(scores_for_calc, key=scores_for_calc.get) if scores_for_calc else 'N/A'})")
    print(f"  second_peak * 0.10 = {second_peak} * 0.10 = {second_peak * 0.10:.3f}")
    print(f"  composite (pre-sanctions) = int({weighted_sum * 0.6:.3f} + {peak * 0.30:.3f} + {second_peak * 0.10:.3f}) = {composite}")
    print(f"  sanction_score = {d['scores'].get('sanctions', 0)} -> bonus = {sanction_bonus}")
    print(f"  final = min(100, {composite} + {sanction_bonus}) = {final}")
    print(f"  actual overall_score = {d['overall_score']}")

    # v0.3 equivalent (without climate_risk and cyber_risk)
    old_weights = {k: v for k, v in weights.items() if k not in ("climate_risk", "cyber_risk")}
    old_weight_sum = sum(old_weights.values())
    old_weighted_sum = sum(d["scores"].get(dim, 0) * w for dim, w in old_weights.items())
    old_sorted = sorted([d["scores"].get(dim, 0) for dim in old_weights], reverse=True)
    old_peak = old_sorted[0] if old_sorted else 0
    old_second = old_sorted[1] if len(old_sorted) > 1 else 0
    old_composite = int(old_weighted_sum * 0.6 + old_peak * 0.30 + old_second * 0.10)
    old_final = min(100, old_composite + sanction_bonus)

    print(f"\n=== Score Change Analysis ===")
    print(f"  v0.3 equivalent (22dim, w/o climate+cyber):")
    print(f"    old weight sum = {old_weight_sum:.3f}")
    print(f"    old weighted_sum = {old_weighted_sum:.3f}")
    print(f"    old composite = {old_composite}, final = {old_final}")
    print(f"  v0.4 actual (24dim): {d['overall_score']}")
    print(f"  Delta: {d['overall_score'] - old_final:+d} points")

    if d["overall_score"] != old_final:
        # Find contributing dimensions
        print(f"  Root cause:")
        if d["scores"].get("climate_risk", 0) > 0:
            print(f"    climate_risk = {d['scores']['climate_risk']} (new dimension contributing)")
        if d["scores"].get("cyber_risk", 0) > 0:
            print(f"    cyber_risk = {d['scores']['cyber_risk']} (new dimension contributing)")
        if abs(total_weight - 1.0) > 0.001:
            print(f"    Weight sum = {total_weight:.4f} (not 1.0, affects weighted average)")

    # List all non-zero dimensions
    non_zero = [(dim, val) for dim, val in d["scores"].items() if val > 0]
    if non_zero:
        print(f"\n  Non-zero dimensions:")
        for dim, val in sorted(non_zero, key=lambda x: -x[1]):
            print(f"    {dim}: {val}")

    return d


def show_all_weights():
    """全重み構成を表示"""
    print(f"\n{'=' * 70}")
    print("=== Weight Configuration ===")
    print(f"{'=' * 70}")

    weights = SupplierRiskScore.WEIGHTS
    total = sum(weights.values())

    categories = {
        "A: Sanctions/Conflict/Political": ["geo_risk", "conflict", "political", "compliance"],
        "B: Disaster/Infrastructure/Climate": ["disaster", "weather", "typhoon", "maritime", "internet", "climate_risk"],
        "C: Economic/Trade": ["economic", "currency", "trade", "energy", "port_congestion"],
        "D: Cyber/Other": ["cyber_risk", "legal", "health", "humanitarian", "food_security", "labor", "aviation"],
    }

    for cat_name, dims in categories.items():
        cat_sum = sum(weights.get(d, 0) for d in dims)
        print(f"\n  {cat_name} ({cat_sum:.0%})")
        for d in dims:
            w = weights.get(d, 0)
            print(f"    {d:<20} {w:.3f}")

    print(f"\n  TOTAL: {total:.4f}")
    print(f"  Not in WEIGHTS: sanctions (handled separately), japan_economy (info only)")


if __name__ == "__main__":
    diagnose_japan()
    show_all_weights()
    print()
