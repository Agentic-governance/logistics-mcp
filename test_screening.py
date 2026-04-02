"""スクリーニング動作確認スクリプト"""
import sys
sys.path.insert(0, ".")

from pipeline.db import Session, engine, SanctionedEntity, SanctionsMetadata
from pipeline.sanctions.screener import screen_entity

def show_db_stats():
    with Session() as session:
        total = session.query(SanctionedEntity).filter_by(is_active=True).count()
        print(f"\n=== DB Stats ===")
        print(f"Total active entities: {total}")

        metadata = session.query(SanctionsMetadata).all()
        for m in metadata:
            print(f"  {m.source.upper():6s}: {m.record_count or 0:>6d} records (fetched: {m.last_fetched})")
        print()


def test_screening():
    test_cases = [
        ("Rosneft", "Russia"),
        ("Huawei", "China"),
        ("SAMSUNG ELECTRONICS", None),
        ("Toyota Motor", "Japan"),
        ("Islamic Revolutionary Guard Corps", "Iran"),
        ("Al-Qaeda", None),
        ("Totally Innocent Company", None),
    ]

    print("=== Screening Tests ===\n")
    for name, country in test_cases:
        result = screen_entity(name, country)
        status = "MATCH" if result.matched else "CLEAR"
        print(f"[{status:5s}] {name:40s} | Score: {result.match_score:5.1f}%", end="")
        if result.matched:
            print(f" | Source: {result.source} | Entity: {result.matched_entity['name']}")
        else:
            print()

        for e in result.evidence:
            print(f"         {e}")
        print()


if __name__ == "__main__":
    show_db_stats()
    test_screening()
