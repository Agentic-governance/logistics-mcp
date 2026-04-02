"""監視ジョブスケジューラー（APScheduler使用）
13データソースの定期更新とサプライヤー監視
"""
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from pipeline.sanctions.normalizer import run_all_parsers
from pipeline.gdelt.monitor import run_monitoring_job
from pipeline.db import Session, engine
from sqlalchemy import Column, Integer, String, Boolean
from pipeline.db import Base


class MonitoredSupplier(Base):
    """監視対象サプライヤーテーブル"""
    __tablename__ = "monitored_suppliers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    supplier_id = Column(String(100), unique=True, nullable=False)
    company_name = Column(String(500), nullable=False)
    location = Column(String(200))
    is_active = Column(Boolean, default=True)


def run_all_monitoring():
    """全監視対象サプライヤーの10次元リスク評価"""
    from scoring.engine import calculate_risk_score

    with Session() as session:
        suppliers = session.query(MonitoredSupplier).filter_by(is_active=True).all()
        for s in suppliers:
            try:
                score = calculate_risk_score(
                    s.supplier_id, s.company_name,
                    country=s.location, location=s.location,
                )
                if score.overall_score >= 50:
                    print(f"[ALERT] {s.company_name}: {score.risk_level()} "
                          f"(score={score.overall_score})")
            except Exception as e:
                print(f"Error monitoring {s.company_name}: {e}")


def run_disaster_check():
    """グローバル災害アラートチェック"""
    try:
        from pipeline.disaster.gdacs_client import fetch_gdacs_alerts
        events = fetch_gdacs_alerts()
        red = [e for e in events if e.severity == "Red"]
        if red:
            print(f"[DISASTER ALERT] {len(red)} red alerts active:")
            for e in red[:5]:
                print(f"  {e.title} ({e.country})")
    except Exception as e:
        print(f"Disaster check error: {e}")


scheduler = BlockingScheduler()

# 制裁リスト: 6時間ごと更新
scheduler.add_job(run_all_parsers, IntervalTrigger(hours=6), id="sanctions_update")

# サプライヤー監視: 15分ごと（10次元評価）
scheduler.add_job(run_all_monitoring, IntervalTrigger(minutes=15), id="supplier_monitoring")

# 災害アラート: 30分ごと
scheduler.add_job(run_disaster_check, IntervalTrigger(minutes=30), id="disaster_check")


if __name__ == "__main__":
    print("Starting scheduler (13 data sources)...")
    print("Jobs:")
    print("  - Sanctions update: every 6 hours")
    print("  - Supplier monitoring (10-dim): every 15 minutes")
    print("  - Disaster alerts: every 30 minutes")
    scheduler.start()
