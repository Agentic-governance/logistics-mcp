"""競合デスティネーション 統合DB
data/tourism_stats.db の competitor_arrivals テーブルに
全競合国のインバウンドデータを統合格納する。
"""
from sqlalchemy import (
    create_engine, Column, String, Integer, Float, DateTime,
    UniqueConstraint, Index,
)
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
from typing import Optional
import os

# tourism_stats.db を使用（data/ ディレクトリ）
_DB_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")
_DB_PATH = os.path.join(_DB_DIR, "tourism_stats.db")
DATABASE_URL = os.getenv("TOURISM_DB_URL", f"sqlite:///{_DB_PATH}")

engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
Base = declarative_base()

# ハードコード年次データ（全競合6カ国 + 日本）
COMPETITOR_DATA = {
    "THA": {"2019": 39800000, "2020": 6700000, "2021": 428000, "2022": 11200000, "2023": 28200000, "2024": 35000000},
    "KOR": {"2019": 17500000, "2020": 2520000, "2021": 970000, "2022": 3200000, "2023": 11000000, "2024": 17000000},
    "TWN": {"2019": 11840000, "2020": 1380000, "2021": 140000, "2022": 900000, "2023": 6490000, "2024": 7860000},
    "FRA": {"2019": 90000000, "2020": 42000000, "2021": 48000000, "2022": 80000000, "2023": 100000000, "2024": 100000000},
    "ESP": {"2019": 83500000, "2020": 19000000, "2021": 31200000, "2022": 71600000, "2023": 85100000, "2024": 94000000},
    "ITA": {"2019": 64500000, "2020": 25200000, "2021": 26900000, "2022": 50400000, "2023": 57500000, "2024": 60000000},
}

# 日本のインバウンド（比較基準）
JAPAN_INBOUND = {
    "2019": 31882049, "2020": 4115900, "2021": 245900,
    "2022": 3832100, "2023": 25066100, "2024": 36869900,
}


class CompetitorArrivals(Base):
    """競合デスティネーション インバウンド到着者数"""
    __tablename__ = "competitor_arrivals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    destination = Column(String(3), nullable=False)       # ISO3 (THA, KOR, TWN, FRA, ESP, ITA)
    source_country = Column(String(3), nullable=False)    # ISO3 送客元（"ALL"で全体）
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=True)                # Noneなら年間
    arrivals = Column(Integer, nullable=True)
    revenue_usd = Column(Float, nullable=True)            # 観光収入（USD, 任意）
    share_pct = Column(Float, nullable=True)              # シェア%
    data_source = Column(String(50))                      # "world_bank", "hardcoded", "kto", etc.
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("destination", "source_country", "year", "month",
                         name="uq_competitor_arrival"),
        Index("idx_competitor_dest_year", "destination", "year"),
        Index("idx_competitor_source", "source_country", "year"),
    )


def init_db():
    """テーブル作成"""
    os.makedirs(_DB_DIR, exist_ok=True)
    Base.metadata.create_all(engine)


class CompetitorDatabase:
    """競合デスティネーション統合DB"""

    def __init__(self):
        init_db()

    def upsert_arrivals(self, destination, source_country, year,
                        month=None, arrivals=None, revenue_usd=None,
                        share_pct=None, data_source="manual"):
        """到着者数をUPSERT

        Args:
            destination: デスティネーションISO3
            source_country: 送客元ISO3（全体なら "ALL"）
            year: 対象年
            month: 対象月（Noneなら年間）
            arrivals: 到着者数
            revenue_usd: 観光収入USD
            share_pct: シェア%
            data_source: データソース名
        """
        session = Session()
        try:
            existing = session.query(CompetitorArrivals).filter_by(
                destination=destination,
                source_country=source_country,
                year=year,
                month=month,
            ).first()

            if existing:
                if arrivals is not None:
                    existing.arrivals = arrivals
                if revenue_usd is not None:
                    existing.revenue_usd = revenue_usd
                if share_pct is not None:
                    existing.share_pct = share_pct
                existing.data_source = data_source
                existing.updated_at = datetime.utcnow()
            else:
                record = CompetitorArrivals(
                    destination=destination,
                    source_country=source_country,
                    year=year,
                    month=month,
                    arrivals=arrivals,
                    revenue_usd=revenue_usd,
                    share_pct=share_pct,
                    data_source=data_source,
                )
                session.add(record)

            session.commit()
        except Exception as e:
            session.rollback()
            print(f"[CompetitorDB] upsert error: {e}")
            raise
        finally:
            session.close()

    def bulk_load_hardcoded(self):
        """ハードコードデータを一括投入"""
        for dest, yearly in COMPETITOR_DATA.items():
            for y_str, arrivals in yearly.items():
                self.upsert_arrivals(
                    destination=dest,
                    source_country="ALL",
                    year=int(y_str),
                    arrivals=arrivals,
                    data_source="hardcoded",
                )
        # 日本のデータも投入
        for y_str, arrivals in JAPAN_INBOUND.items():
            self.upsert_arrivals(
                destination="JPN",
                source_country="ALL",
                year=int(y_str),
                arrivals=arrivals,
                data_source="hardcoded",
            )
        print("[CompetitorDB] ハードコードデータ投入完了")

    def get_market_share_comparison(self, source_country, month=None, year=None):
        """送客元国の各デスティネーション別シェア比較

        Args:
            source_country: 送客元ISO3
            month: 対象月（Noneなら年間）
            year: 対象年（Noneなら最新）

        Returns:
            dict: {destination: {arrivals, share_pct, ...}}
        """
        session = Session()
        try:
            query = session.query(CompetitorArrivals).filter_by(
                source_country=source_country,
            )
            if month is not None:
                query = query.filter_by(month=month)
            else:
                query = query.filter(CompetitorArrivals.month.is_(None))

            if year:
                query = query.filter_by(year=year)
            else:
                # 最新年を取得
                latest = session.query(
                    CompetitorArrivals.year
                ).filter_by(source_country=source_country).order_by(
                    CompetitorArrivals.year.desc()
                ).first()
                if latest:
                    query = query.filter_by(year=latest[0])
                    year = latest[0]

            records = query.all()
            if not records:
                return {"source_country": source_country, "year": year, "destinations": {}}

            total = sum(r.arrivals for r in records if r.arrivals)
            result = {
                "source_country": source_country,
                "year": year,
                "month": month,
                "total_from_source": total,
                "destinations": {},
            }

            for r in records:
                share = round(r.arrivals / total * 100, 1) if total and r.arrivals else None
                result["destinations"][r.destination] = {
                    "arrivals": r.arrivals,
                    "share_pct": share,
                    "data_source": r.data_source,
                }

            return result
        finally:
            session.close()

    def get_relative_growth(self, period_months=12):
        """全競合国の直近成長率比較

        ハードコードデータベースの年次成長率を算出。

        Args:
            period_months: 分析期間（月数、年次データの場合は年数に変換）

        Returns:
            dict: {destination: {growth_pct, recovery_pct, ...}}
        """
        session = Session()
        try:
            result = {}
            all_dests = list(COMPETITOR_DATA.keys()) + ["JPN"]

            for dest in all_dests:
                records = session.query(CompetitorArrivals).filter_by(
                    destination=dest,
                    source_country="ALL",
                    month=None,
                ).order_by(CompetitorArrivals.year.desc()).limit(3).all()

                if len(records) < 2:
                    # DBに無い場合はハードコードから直接計算
                    data = COMPETITOR_DATA.get(dest, JAPAN_INBOUND if dest == "JPN" else {})
                    years_sorted = sorted(data.keys(), reverse=True)
                    if len(years_sorted) >= 2:
                        latest = data[years_sorted[0]]
                        prev = data[years_sorted[1]]
                        pre_covid = data.get("2019")
                        yoy = round((latest / prev - 1) * 100, 1) if prev > 0 else None
                        recovery = round(latest / pre_covid * 100, 1) if pre_covid and pre_covid > 0 else None
                        result[dest] = {
                            "latest_year": int(years_sorted[0]),
                            "latest_arrivals": latest,
                            "yoy_growth_pct": yoy,
                            "recovery_vs_2019_pct": recovery,
                            "source": "hardcoded",
                        }
                    continue

                latest = records[0]
                prev = records[1]
                yoy = None
                if prev.arrivals and prev.arrivals > 0:
                    yoy = round((latest.arrivals / prev.arrivals - 1) * 100, 1)

                # 2019年比
                rec_2019 = session.query(CompetitorArrivals).filter_by(
                    destination=dest, source_country="ALL", year=2019, month=None,
                ).first()
                recovery = None
                if rec_2019 and rec_2019.arrivals and rec_2019.arrivals > 0:
                    recovery = round(latest.arrivals / rec_2019.arrivals * 100, 1)

                result[dest] = {
                    "latest_year": latest.year,
                    "latest_arrivals": latest.arrivals,
                    "yoy_growth_pct": yoy,
                    "recovery_vs_2019_pct": recovery,
                    "source": latest.data_source,
                }

            # ランキング（成長率順）
            ranked = sorted(
                result.items(),
                key=lambda x: x[1].get("yoy_growth_pct") or -999,
                reverse=True,
            )
            for rank, (dest, data) in enumerate(ranked, 1):
                result[dest]["growth_rank"] = rank

            return result
        finally:
            session.close()

    def get_diversion_signal(self, source_country):
        """転換シグナル — 送客元からの観光客が日本から競合に流出している度合い

        日本のシェア減少 × 競合のシェア増加 = 高い転換シグナル

        Args:
            source_country: 送客元ISO3

        Returns:
            float: 転換シグナル (0.0-1.0, 高いほど転換が進行)
        """
        session = Session()
        try:
            # source_country → JPN の直近2年分を取得
            jpn_records = session.query(CompetitorArrivals).filter_by(
                destination="JPN",
                source_country=source_country,
            ).filter(
                CompetitorArrivals.month.is_(None)
            ).order_by(CompetitorArrivals.year.desc()).limit(2).all()

            # source_country → 各競合 の直近データ
            comp_records = session.query(CompetitorArrivals).filter(
                CompetitorArrivals.destination != "JPN",
                CompetitorArrivals.source_country == source_country,
                CompetitorArrivals.month.is_(None),
            ).order_by(CompetitorArrivals.year.desc()).all()

            # DBデータ不足の場合は推定値で計算
            if len(jpn_records) < 2:
                # JNTOハードコードデータからの推定
                return self._estimate_diversion_from_hardcoded(source_country)

            jpn_latest = jpn_records[0].arrivals
            jpn_prev = jpn_records[1].arrivals

            if not jpn_prev or jpn_prev == 0:
                return 0.0

            jpn_growth = (jpn_latest - jpn_prev) / jpn_prev

            # 競合の平均成長率
            comp_by_dest = {}
            for r in comp_records:
                if r.destination not in comp_by_dest:
                    comp_by_dest[r.destination] = []
                comp_by_dest[r.destination].append(r)

            comp_growths = []
            for dest, recs in comp_by_dest.items():
                if len(recs) >= 2:
                    latest = recs[0].arrivals
                    prev = recs[1].arrivals
                    if prev and prev > 0:
                        comp_growths.append((latest - prev) / prev)

            if not comp_growths:
                return 0.0

            avg_comp_growth = sum(comp_growths) / len(comp_growths)

            # 転換シグナル: 競合が日本より伸びていれば高い
            # (comp_growth - jpn_growth) を [0, 1] にクリップ
            signal = (avg_comp_growth - jpn_growth)
            signal = max(0.0, min(1.0, signal))
            return round(signal, 3)

        except Exception as e:
            print(f"[CompetitorDB] diversion signal error: {e}")
            return 0.0
        finally:
            session.close()

    def _estimate_diversion_from_hardcoded(self, source_country):
        """ハードコードデータのみで転換シグナルを推定

        全体のインバウンド成長率を使って概算する
        """
        # 日本の成長率 (2023→2024)
        jpn_2024 = JAPAN_INBOUND.get("2024", 36869900)
        jpn_2023 = JAPAN_INBOUND.get("2023", 25066100)
        jpn_growth = (jpn_2024 - jpn_2023) / jpn_2023 if jpn_2023 > 0 else 0

        # 競合平均成長率
        comp_growths = []
        for dest, data in COMPETITOR_DATA.items():
            a_2024 = data.get("2024")
            a_2023 = data.get("2023")
            if a_2024 and a_2023 and a_2023 > 0:
                comp_growths.append((a_2024 - a_2023) / a_2023)

        if not comp_growths:
            return 0.0

        avg_comp = sum(comp_growths) / len(comp_growths)
        signal = max(0.0, min(1.0, avg_comp - jpn_growth))
        return round(signal, 3)

    def get_all_destinations_summary(self, year=None):
        """全デスティネーション(競合+日本)のサマリー

        Args:
            year: 対象年（Noneなら最新）

        Returns:
            dict: 統合サマリー
        """
        if year is None:
            year = 2024

        all_data = dict(COMPETITOR_DATA)
        all_data["JPN"] = JAPAN_INBOUND

        summary = {}
        for dest, yearly in all_data.items():
            y_str = str(year)
            arrivals = yearly.get(y_str)
            prev = yearly.get(str(year - 1))
            pre_covid = yearly.get("2019")

            summary[dest] = {
                "arrivals": arrivals,
                "yoy_pct": round((arrivals / prev - 1) * 100, 1) if arrivals and prev and prev > 0 else None,
                "recovery_vs_2019_pct": round(arrivals / pre_covid * 100, 1) if arrivals and pre_covid else None,
            }

        # 日本との比率
        jpn_arr = summary.get("JPN", {}).get("arrivals")
        if jpn_arr:
            for dest, data in summary.items():
                if dest != "JPN" and data["arrivals"]:
                    data["ratio_to_japan"] = round(data["arrivals"] / jpn_arr, 2)

        return {
            "year": year,
            "destinations": summary,
            "note": "日本は2024年に過去最高の3,687万人を記録",
        }
