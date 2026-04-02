"""制裁リスト正規化・DB格納エンジン"""
import json
from datetime import datetime
from sqlalchemy.orm import Session
from pipeline.db import SanctionedEntity, SanctionsMetadata, engine
from .ofac import OFACParser
from .eu import EUParser
from .un import UNParser
from .bis import BISParser
from .meti import METIParser
from rich.console import Console

console = Console()


def run_all_parsers():
    """全制裁リストを取得・正規化・DB保存"""
    parsers = [OFACParser(), EUParser(), UNParser(), BISParser(), METIParser()]

    with Session(engine) as session:
        for parser in parsers:
            console.print(f"\n[bold blue]Processing {parser.source.upper()}...[/]")
            count = 0

            # 既存データをアーカイブ
            session.query(SanctionedEntity).filter_by(
                source=parser.source, is_active=True
            ).update({"is_active": False})

            try:
                for entry in parser.fetch_and_parse():
                    entity = SanctionedEntity(
                        source=entry.source,
                        source_id=entry.source_id,
                        entity_type=entry.entity_type,
                        name_primary=entry.name_primary,
                        names_aliases=json.dumps(entry.names_aliases, ensure_ascii=False),
                        country=entry.country,
                        address=entry.address,
                        programs=json.dumps(entry.programs, ensure_ascii=False),
                        reason=entry.reason,
                        raw_data=json.dumps(entry.__dict__, ensure_ascii=False, default=str),
                        is_active=True,
                    )
                    session.add(entity)
                    count += 1

                    if count % 1000 == 0:
                        session.flush()
                        console.print(f"  {count} records...")

                session.commit()
            except Exception as e:
                session.rollback()
                console.print(f"[red]Error processing {parser.source.upper()}: {e}[/]")
                continue

            # メタデータ更新
            meta = session.get(SanctionsMetadata, parser.source) or SanctionsMetadata(source=parser.source)
            meta.last_fetched = datetime.utcnow()
            meta.record_count = count
            session.merge(meta)
            session.commit()

            console.print(f"[green]{parser.source.upper()}: {count} entities saved[/]")


if __name__ == "__main__":
    from pipeline.db import init_db
    init_db()
    run_all_parsers()
