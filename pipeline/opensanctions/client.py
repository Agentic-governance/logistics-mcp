"""OpenSanctions バルクデータ統合クライアント
320+データソースの制裁・PEP・犯罪者データを一括取得。
自前パーサー5本(OFAC/EU/UN/BIS/METI)より圧倒的に高品質・高カバレッジ。
https://www.opensanctions.org/
"""
import requests
import json
import csv
import io
import os
from datetime import datetime
from typing import Iterator
from pipeline.db import SanctionedEntity, SanctionsMetadata, Session, engine
from rich.console import Console

console = Console()

# OpenSanctions bulk data URLs (non-commercial use free)
DATASETS = {
    "default": "https://data.opensanctions.org/datasets/latest/default/targets.simple.csv",
    "sanctions": "https://data.opensanctions.org/datasets/latest/sanctions/targets.simple.csv",
    "peps": "https://data.opensanctions.org/datasets/latest/peps/targets.simple.csv",
}

HEADERS = {
    "User-Agent": "SupplyChainRiskIntelligence/1.0 (non-commercial research)",
}


def fetch_opensanctions(dataset: str = "default") -> Iterator[dict]:
    """OpenSanctionsのCSVデータをストリーム取得"""
    url = DATASETS.get(dataset, DATASETS["default"])
    console.print(f"[bold blue]Fetching OpenSanctions '{dataset}' dataset...[/]")

    resp = requests.get(url, timeout=300, headers=HEADERS, stream=True)
    resp.raise_for_status()

    reader = csv.DictReader(io.StringIO(resp.text))
    for row in reader:
        yield row


def import_opensanctions(dataset: str = "default"):
    """OpenSanctionsデータをDBに格納"""
    source_name = f"opensanctions_{dataset}"

    with Session() as session:
        # 既存データをアーカイブ
        session.query(SanctionedEntity).filter(
            SanctionedEntity.source.like("opensanctions%"),
            SanctionedEntity.is_active == True,
        ).update({"is_active": False}, synchronize_session=False)
        session.commit()

    count = 0
    with Session() as session:
        for row in fetch_opensanctions(dataset):
            entity_id = row.get("id", "")
            name = row.get("caption", "").strip()
            if not name:
                continue

            schema = row.get("schema", "").lower()
            entity_type = "entity"
            if "person" in schema:
                entity_type = "individual"
            elif "vessel" in schema:
                entity_type = "vessel"
            elif "aircraft" in schema:
                entity_type = "aircraft"

            # Datasets that flagged this entity
            datasets = row.get("datasets", "")
            countries = row.get("countries", "")
            addresses = row.get("addresses", "")

            # Determine original source from datasets
            original_sources = []
            if "ofac" in datasets.lower():
                original_sources.append("OFAC")
            if "eu_" in datasets.lower():
                original_sources.append("EU")
            if "un_" in datasets.lower():
                original_sources.append("UN")
            if "jp_" in datasets.lower() or "meti" in datasets.lower():
                original_sources.append("METI")

            entity = SanctionedEntity(
                source=source_name,
                source_id=entity_id,
                entity_type=entity_type,
                name_primary=name,
                names_aliases=json.dumps([], ensure_ascii=False),
                country=countries.split(";")[0] if countries else None,
                address=addresses,
                programs=json.dumps(original_sources or [dataset], ensure_ascii=False),
                reason=row.get("topics", ""),
                raw_data=json.dumps(row, ensure_ascii=False),
                is_active=True,
            )
            session.add(entity)
            count += 1

            if count % 5000 == 0:
                session.flush()
                console.print(f"  {count} records...")

        session.commit()

        # メタデータ更新
        meta = session.get(SanctionsMetadata, source_name) or SanctionsMetadata(source=source_name)
        meta.last_fetched = datetime.utcnow()
        meta.record_count = count
        session.merge(meta)
        session.commit()

    console.print(f"[green]OpenSanctions '{dataset}': {count} entities saved[/]")
    return count


if __name__ == "__main__":
    from pipeline.db import init_db
    init_db()
    import_opensanctions("default")
