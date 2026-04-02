#!/usr/bin/env python3
"""制裁データ品質レポート (C-3)

pipeline/sanctions/ の全クライアントを読み込み、
各ソースの件数・最終更新・品質スコアをサマリーとして出力する。
重複エンティティ率・未正規化エンティティ率を計算。

実行: .venv311/bin/python scripts/sanctions_quality_report.py
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from sqlalchemy.orm import Session
    from pipeline.db import SanctionedEntity, SanctionsMetadata, engine
    from rapidfuzz import fuzz
except ImportError as exc:
    print(f"依存パッケージが不足しています: {exc}")
    print("pip install sqlalchemy rapidfuzz")
    sys.exit(1)


# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------
# 制裁ソース一覧（pipeline/sanctions/ に対応するパーサー）
ALL_SOURCES = [
    "ofac", "un", "eu", "bis", "meti",
    "ofsi", "seco", "canada", "dfat", "mofa_japan",
    "opensanctions_default", "opensanctions_sanctions",
]

# 品質チェック対象の法人格接尾辞パターン
_SUFFIXES_PATTERN = re.compile(
    r"\b(co\.?\s*,?\s*ltd\.?|corp\.?|inc\.?|llc\.?|ltd\.?|limited|gmbh|"
    r"s\.?a\.?|pte\.?|pvt\.?|b\.?v\.?|n\.?v\.?|ag|plc|l\.?p\.?|jsc|ojsc)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# 品質チェック関数
# ---------------------------------------------------------------------------
def check_name_quality(name: str) -> dict:
    """エンティティ名の品質をチェックする。

    Returns:
        {"is_normalized": bool, "issues": list[str], "score": float}
    """
    issues = []
    score = 1.0

    if not name or not name.strip():
        return {"is_normalized": False, "issues": ["空の名前"], "score": 0.0}

    name = name.strip()

    # 全角文字の混在チェック（日本語ソースを除く）
    if re.search(r"[\uff01-\uff5e]", name):
        issues.append("全角英数字が混在")
        score -= 0.1

    # 過度な空白
    if "  " in name:
        issues.append("連続空白あり")
        score -= 0.05

    # 全大文字チェック（正規化されていない可能性）
    if name == name.upper() and len(name) > 5:
        # 全大文字は制裁リストでは一般的なので軽微
        pass
    elif name == name.lower():
        issues.append("全小文字（未正規化の可能性）")
        score -= 0.1

    # 名前が短すぎる
    if len(name) < 3:
        issues.append("名前が短すぎる（3文字未満）")
        score -= 0.3

    # 名前が長すぎる
    if len(name) > 300:
        issues.append("名前が長すぎる（300文字超）")
        score -= 0.2

    # 数字のみ
    if name.replace(" ", "").isdigit():
        issues.append("数字のみの名前")
        score -= 0.5

    is_normalized = len(issues) == 0
    return {
        "is_normalized": is_normalized,
        "issues": issues,
        "score": max(0.0, round(score, 2)),
    }


def find_duplicates(entities: list, threshold: int = 90) -> list:
    """重複エンティティのペアを検出する。

    同一ソース内で名前が非常に類似したエンティティを検出。
    計算コスト削減のためサンプリングを使用。

    Args:
        entities: (name, source_id) のタプルリスト
        threshold: 重複判定のファジーマッチ閾値

    Returns:
        重複ペアのリスト [(name_a, name_b, score), ...]
    """
    duplicates = []
    # パフォーマンスのため最大500件でサンプリング
    sample = entities[:500]

    for i in range(len(sample)):
        for j in range(i + 1, len(sample)):
            name_a = sample[i][0]
            name_b = sample[j][0]
            # 同一ソースIDなら完全重複
            if sample[i][1] and sample[i][1] == sample[j][1]:
                duplicates.append((name_a, name_b, 100))
                continue
            # ファジーマッチ
            score = fuzz.token_sort_ratio(name_a.lower(), name_b.lower())
            if score >= threshold:
                duplicates.append((name_a, name_b, score))

    return duplicates


# ---------------------------------------------------------------------------
# レポート生成
# ---------------------------------------------------------------------------
def generate_report() -> dict:
    """全制裁ソースの品質レポートを生成する。"""

    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "sources": {},
        "summary": {},
    }

    total_entities = 0
    total_duplicates = 0
    total_unnormalized = 0
    source_stats = []

    with Session(engine) as session:
        # メタデータ取得
        metadata_rows = session.query(SanctionsMetadata).all()
        metadata_map = {m.source: m for m in metadata_rows}

        # ソース別分析
        for source in ALL_SOURCES:
            print(f"\n[{source.upper()}] 分析中...", flush=True)

            entities = session.query(SanctionedEntity).filter_by(
                source=source, is_active=True
            ).all()

            count = len(entities)
            if count == 0:
                # メタデータから件数を確認
                meta = metadata_map.get(source)
                if meta and meta.record_count:
                    report["sources"][source] = {
                        "record_count": meta.record_count,
                        "active_count": 0,
                        "last_fetched": meta.last_fetched.isoformat() if meta.last_fetched else None,
                        "status": "データあり（非アクティブ）",
                        "quality_score": 0.0,
                    }
                else:
                    report["sources"][source] = {
                        "record_count": 0,
                        "active_count": 0,
                        "last_fetched": None,
                        "status": "データなし",
                        "quality_score": 0.0,
                    }
                print(f"  データなしまたは非アクティブ")
                continue

            total_entities += count

            # 名前品質チェック
            name_qualities = []
            unnormalized_count = 0
            for ent in entities:
                q = check_name_quality(ent.name_primary)
                name_qualities.append(q)
                if not q["is_normalized"]:
                    unnormalized_count += 1

            total_unnormalized += unnormalized_count

            avg_quality = sum(q["score"] for q in name_qualities) / len(name_qualities) if name_qualities else 0.0

            # エンティティタイプ分布
            type_dist = Counter(ent.entity_type or "unknown" for ent in entities)

            # 国分布（上位10）
            country_dist = Counter(ent.country or "unknown" for ent in entities)
            top_countries = country_dist.most_common(10)

            # エイリアス保有率
            alias_count = sum(
                1 for ent in entities
                if ent.names_aliases and json.loads(ent.names_aliases or "[]")
            )

            # 重複検出（サンプル）
            entity_pairs = [(ent.name_primary, ent.source_id) for ent in entities]
            dupes = find_duplicates(entity_pairs)
            total_duplicates += len(dupes)

            # メタデータ
            meta = metadata_map.get(source)
            last_fetched = None
            if meta and meta.last_fetched:
                last_fetched = meta.last_fetched.isoformat()

            source_report = {
                "record_count": count,
                "active_count": count,
                "last_fetched": last_fetched,
                "entity_types": dict(type_dist),
                "top_countries": top_countries,
                "alias_coverage": round(alias_count / count * 100, 1) if count else 0,
                "unnormalized_count": unnormalized_count,
                "unnormalized_rate": round(unnormalized_count / count * 100, 1) if count else 0,
                "duplicate_pairs_detected": len(dupes),
                "duplicate_rate": round(len(dupes) / count * 100, 2) if count else 0,
                "avg_name_quality": round(avg_quality, 3),
                "quality_score": round(avg_quality * 100, 1),
                "status": "OK" if avg_quality > 0.7 else ("警告" if avg_quality > 0.4 else "要改善"),
            }

            # 重複サンプル（上位5件）
            if dupes:
                source_report["duplicate_samples"] = [
                    {"name_a": d[0], "name_b": d[1], "similarity": d[2]}
                    for d in dupes[:5]
                ]

            report["sources"][source] = source_report
            source_stats.append((source, count, round(avg_quality, 3)))

            print(f"  件数: {count}, 品質: {avg_quality:.3f}, "
                  f"未正規化: {unnormalized_count} ({unnormalized_count / count * 100:.1f}%), "
                  f"重複候補: {len(dupes)}")

    # サマリー
    report["summary"] = {
        "total_active_entities": total_entities,
        "total_sources_with_data": sum(1 for s in report["sources"].values() if s.get("active_count", 0) > 0),
        "total_sources_checked": len(ALL_SOURCES),
        "total_duplicate_pairs": total_duplicates,
        "overall_duplicate_rate": round(total_duplicates / total_entities * 100, 2) if total_entities else 0,
        "total_unnormalized": total_unnormalized,
        "overall_unnormalized_rate": round(total_unnormalized / total_entities * 100, 2) if total_entities else 0,
        "source_ranking": sorted(source_stats, key=lambda x: x[1], reverse=True),
    }

    return report


def print_report(report: dict):
    """レポートをコンソール出力する。"""
    print("\n" + "=" * 70)
    print("制裁データ品質レポート")
    print(f"生成日時: {report['generated_at']}")
    print("=" * 70)

    summary = report["summary"]
    print(f"\n総アクティブエンティティ数: {summary['total_active_entities']:,}")
    print(f"データ保有ソース数: {summary['total_sources_with_data']}/{summary['total_sources_checked']}")
    print(f"全体重複率: {summary['overall_duplicate_rate']}%")
    print(f"全体未正規化率: {summary['overall_unnormalized_rate']}%")

    print(f"\n{'ソース':<25} {'件数':>10} {'品質':>8} {'未正規化':>10} {'重複':>8} {'状態':<10}")
    print("-" * 75)

    for source, info in report["sources"].items():
        count = info.get("active_count", info.get("record_count", 0))
        quality = info.get("quality_score", 0)
        unnorm_rate = info.get("unnormalized_rate", 0)
        dup_count = info.get("duplicate_pairs_detected", 0)
        status = info.get("status", "N/A")

        print(f"  {source:<23} {count:>10,} {quality:>7.1f}% {unnorm_rate:>9.1f}% {dup_count:>7} {status:<10}")

    print("-" * 75)


def main():
    """メイン処理: レポート生成・出力・保存"""
    report = generate_report()
    print_report(report)

    # JSON保存
    output_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
    )
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "sanctions_quality_report.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    print(f"\nJSON保存先: {output_path}")
    return report


if __name__ == "__main__":
    main()
