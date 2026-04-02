"""GDELT BigQuery クライアント"""
from google.cloud import bigquery
from datetime import datetime, timedelta
import os

_client = None


def get_client():
    global _client
    if _client is None:
        _client = bigquery.Client(project=os.getenv("BIGQUERY_PROJECT"))
    return _client


# GDELTトーン値の意味:
# 正の値 = ポジティブなトーン
# 負の値 = ネガティブなトーン
# -10以下 = 非常にネガティブ（危機的報道）
TONE_RISK_THRESHOLD = -5.0


def query_supplier_mentions(
    company_name: str,
    location: str = None,
    hours_back: int = 24,
) -> list[dict]:
    """
    GDELT GKG2でサプライヤー名の言及を検索。
    GKGはGlobal Knowledge Graphで記事ごとのエンティティ・テーマ・トーンを保持。
    """
    since = datetime.utcnow() - timedelta(hours=hours_back)
    since_str = since.strftime("%Y%m%d%H%M%S")

    location_filter = ""
    if location:
        location_filter = f"AND LOWER(V2Locations) LIKE LOWER(@location_param)"

    query = f"""
    SELECT
        DATE,
        SourceCommonName,
        DocumentIdentifier,
        V2Tone,
        V2Themes,
        V2Organizations,
        V2Locations,
        SharingImage
    FROM `gdelt-bq.gdeltv2.gkg_partitioned`
    WHERE _PARTITIONTIME >= TIMESTAMP(@since_ts)
        AND DATE >= @since_int
        AND (
            LOWER(V2Organizations) LIKE LOWER(@name_param)
            OR LOWER(Extras) LIKE LOWER(@name_param)
        )
        {location_filter}
    ORDER BY DATE DESC
    LIMIT 100
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("since_ts", "STRING", since.strftime('%Y-%m-%d %H:%M:%S')),
            bigquery.ScalarQueryParameter("since_int", "INT64", int(since_str)),
            bigquery.ScalarQueryParameter("name_param", "STRING", f"%{company_name}%"),
        ] + ([
            bigquery.ScalarQueryParameter("location_param", "STRING", f"%{location}%"),
        ] if location else []),
        maximum_bytes_billed=10 * 1024**3,  # 10GB上限
    )

    query_job = get_client().query(query, job_config=job_config)
    rows = list(query_job.result())

    results = []
    for row in rows:
        tone_parts = str(row.V2Tone or "").split(",")
        avg_tone = float(tone_parts[0]) if tone_parts[0] else 0.0

        results.append({
            "date": str(row.DATE),
            "source": row.SourceCommonName,
            "url": row.DocumentIdentifier,
            "tone": avg_tone,
            "themes": row.V2Themes or "",
            "locations": row.V2Locations or "",
            "organizations": row.V2Organizations or "",
        })

    return results


def query_location_risk(location: str, hours_back: int = 168) -> dict:
    """
    指定地域の直近1週間の地政学的リスクを集計。
    CAMEOコードで暴力・抗議・制裁イベントを分類。
    """
    since = datetime.utcnow() - timedelta(hours=hours_back)

    query = """
    SELECT
        EventCode,
        COUNT(*) as event_count,
        AVG(GoldsteinScale) as avg_goldstein,
        AVG(AvgTone) as avg_tone,
        SUM(NumMentions) as total_mentions
    FROM `gdelt-bq.gdeltv2.events`
    WHERE SQLDATE >= @since_date
        AND (
            LOWER(Actor1Geo_FullName) LIKE LOWER(@loc_param)
            OR LOWER(Actor2Geo_FullName) LIKE LOWER(@loc_param)
            OR LOWER(ActionGeo_FullName) LIKE LOWER(@loc_param)
        )
        AND EventCode IN (
            '14', '141', '142', '143',
            '17', '171', '172', '173', '174', '175', '176',
            '18', '181', '182', '183',
            '163', '164',
            '19', '191', '192', '193', '194', '195', '196'
        )
    GROUP BY EventCode
    ORDER BY total_mentions DESC
    LIMIT 50
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("since_date", "INT64", int(since.strftime('%Y%m%d'))),
            bigquery.ScalarQueryParameter("loc_param", "STRING", f"%{location}%"),
        ],
        maximum_bytes_billed=10 * 1024**3,  # 10GB上限
    )

    job = get_client().query(query, job_config=job_config)
    rows = list(job.result())

    total_events = sum(r.event_count for r in rows)
    avg_goldstein = sum(r.avg_goldstein * r.event_count for r in rows) / max(total_events, 1)

    # Goldsteinスケール: -10(最悪)〜+10(最良)
    # リスクスコアに変換: 低いほど高リスク
    geo_risk_score = max(0, min(100, int(((-avg_goldstein + 10) / 20) * 100)))

    return {
        "location": location,
        "total_conflict_events": total_events,
        "avg_goldstein": avg_goldstein,
        "geo_risk_score": geo_risk_score,
        "event_breakdown": [{"code": r.EventCode, "count": r.event_count} for r in rows],
    }
