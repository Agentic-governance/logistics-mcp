from sqlalchemy import create_engine, Column, String, Integer, DateTime, Text, Boolean, Float
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/risk.db")
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
Base = declarative_base()


class SanctionedEntity(Base):
    """正規化済み制裁対象エンティティ"""
    __tablename__ = "sanctioned_entities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(20), nullable=False)  # ofac/eu/un/bis/meti/ofsi/seco/canada/dfat/mofa_japan
    source_id = Column(String(100))              # 元リストのID
    entity_type = Column(String(20))             # individual/entity/vessel/aircraft
    name_primary = Column(String(500), nullable=False)
    names_aliases = Column(Text)                 # JSON array of alias names
    country = Column(String(100))
    address = Column(Text)
    programs = Column(Text)                      # JSON: 制裁プログラム名
    reason = Column(Text)                        # 制裁理由
    raw_data = Column(Text)                      # 元データJSON
    is_active = Column(Boolean, default=True)
    fetched_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ScreeningLog(Base):
    """スクリーニング実行ログ"""
    __tablename__ = "screening_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    query_name = Column(String(500), nullable=False)
    query_country = Column(String(100))
    matched = Column(Boolean, default=False)
    match_score = Column(Float)
    matched_entity_id = Column(Integer)
    matched_source = Column(String(20))
    screened_at = Column(DateTime, default=datetime.utcnow)


class SanctionsMetadata(Base):
    """各リストの最終取得情報"""
    __tablename__ = "sanctions_metadata"

    source = Column(String(20), primary_key=True)
    last_fetched = Column(DateTime)
    record_count = Column(Integer)
    checksum = Column(String(64))


def init_db():
    import os
    os.makedirs("data", exist_ok=True)
    # Import all models to register them with Base before creating tables
    from pipeline.gdelt.monitor import RiskAlert  # noqa: F401
    from pipeline.scheduler import MonitoredSupplier  # noqa: F401
    Base.metadata.create_all(engine)
    print("Database initialized")


if __name__ == "__main__":
    init_db()
