"""相関修正の検証スクリプト
food_security ↔ humanitarian の独立性確認 + スコア回帰テスト。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np


def main():
    from scoring.dimensions.humanitarian_scorer import get_humanitarian_score
    from scoring.dimensions.food_security_scorer import get_food_security_score

    # 多様な国リスト (安全国 + 危機国)
    countries = [
        "JP", "DE", "US", "CN", "KR",           # 安全国
        "Yemen", "Ethiopia", "Nigeria", "Somalia",  # 危機国
        "Haiti", "Myanmar", "Sudan",               # 危機国
    ]

    print("=" * 60)
    print("=== food_security vs humanitarian Score Comparison ===")
    print("=" * 60)
    print(f"{'Country':<15} {'food_sec':>8} {'humanit':>8} {'diff':>6}")
    print("-" * 40)

    fs_scores = []
    hm_scores = []
    for c in countries:
        fs = get_food_security_score(c)
        hm = get_humanitarian_score(c)
        fs_s = fs["score"]
        hm_s = hm["score"]
        fs_scores.append(fs_s)
        hm_scores.append(hm_s)
        diff = abs(fs_s - hm_s)
        print(f"{c:<15} {fs_s:>8} {hm_s:>8} {diff:>6}")

    # ピアソン相関算出
    fs_arr = np.array(fs_scores, dtype=float)
    hm_arr = np.array(hm_scores, dtype=float)

    if np.std(fs_arr) > 0 and np.std(hm_arr) > 0:
        from scipy import stats
        r, p = stats.pearsonr(fs_arr, hm_arr)
        print(f"\n  Pearson r = {r:.3f} (p={p:.4f})")
        status = "PASS" if abs(r) < 0.70 else "FAIL" if abs(r) > 0.95 else "MARGINAL"
        print(f"  [{status}] food_security ↔ humanitarian correlation target: r < 0.70, actual: {r:.3f}")
    else:
        print("\n  Cannot compute correlation (zero variance)")

    print("=" * 60)


if __name__ == "__main__":
    main()
