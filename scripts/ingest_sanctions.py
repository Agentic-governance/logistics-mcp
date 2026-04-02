"""制裁リスト一括取り込みスクリプト
全パーサーからデータを取得し、sanctioned_entities テーブルに格納する。
"""
import sys
import os
import json
import traceback
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.db import Session, engine, SanctionedEntity, SanctionsMetadata, Base


PARSERS = [
    ("ofac", "pipeline.sanctions.ofac", "OFACParser"),
    ("eu", "pipeline.sanctions.eu", "EUParser"),
    ("bis", "pipeline.sanctions.bis", "BISParser"),
    ("meti", "pipeline.sanctions.meti", "METIParser"),
    ("ofsi", "pipeline.sanctions.ofsi", "OFSIParser"),
    ("seco", "pipeline.sanctions.seco", "SECOParser"),
    ("canada", "pipeline.sanctions.canada", "CanadaParser"),
    ("dfat", "pipeline.sanctions.dfat", "DFATParser"),
    ("mofa_japan", "pipeline.sanctions.mofa_japan", "MOFAJapanParser"),
]


def ingest_source(source_name: str, module_path: str, class_name: str) -> dict:
    """単一ソースの取り込み"""
    try:
        import importlib
        mod = importlib.import_module(module_path)
        parser_cls = getattr(mod, class_name)
        parser = parser_cls()

        entries = list(parser.fetch_and_parse())
        count = 0

        with Session() as session:
            # 既存データを非アクティブに
            session.query(SanctionedEntity).filter_by(
                source=source_name
            ).update({"is_active": False})

            for entry in entries:
                entity = SanctionedEntity(
                    source=entry.source,
                    source_id=entry.source_id,
                    entity_type=entry.entity_type,
                    name_primary=entry.name_primary,
                    names_aliases=json.dumps(entry.names_aliases),
                    country=entry.country,
                    address=entry.address,
                    programs=json.dumps(entry.programs),
                    reason=entry.reason,
                    is_active=True,
                    fetched_at=datetime.utcnow(),
                )
                session.add(entity)
                count += 1

            # メタデータ更新
            meta = session.query(SanctionsMetadata).filter_by(
                source=source_name
            ).first()
            if meta:
                meta.last_fetched = datetime.utcnow()
                meta.record_count = count
            else:
                meta = SanctionsMetadata(
                    source=source_name,
                    last_fetched=datetime.utcnow(),
                    record_count=count,
                )
                session.add(meta)

            session.commit()

        return {"source": source_name, "status": "ok", "count": count}

    except Exception as e:
        traceback.print_exc()
        return {"source": source_name, "status": "error", "error": str(e)[:200]}


def main():
    # DB初期化
    os.makedirs("data", exist_ok=True)
    Base.metadata.create_all(engine)

    print("=" * 70)
    print("SCRI v0.4.0 — Sanctions List Ingestion")
    print("=" * 70)

    sources = sys.argv[1:] if len(sys.argv) > 1 else None
    results = []

    for source_name, module_path, class_name in PARSERS:
        if sources and source_name not in sources:
            continue

        print(f"\n--- {source_name.upper()} ---")
        result = ingest_source(source_name, module_path, class_name)
        results.append(result)

        status = result["status"]
        if status == "ok":
            print(f"  OK: {result['count']} entities ingested")
        else:
            print(f"  ERROR: {result.get('error', 'unknown')}")

    print("\n" + "=" * 70)
    ok = sum(1 for r in results if r["status"] == "ok")
    total_entities = sum(r.get("count", 0) for r in results if r["status"] == "ok")
    print(f"  Sources: {ok}/{len(results)} succeeded")
    print(f"  Total entities: {total_entities}")
    print("=" * 70)


if __name__ == "__main__":
    main()
