"""Dashboard API Routes — SCRI v1.4.0
ダッシュボード用リスクサマリー・チョークポイント情報

GET  /api/v1/dashboard/global-risk
GET  /api/v1/dashboard/chokepoints
"""
import logging
import sqlite3
import os
from datetime import datetime

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])

# 国名→ISO2マッピング（timeseries.dbは国名で格納）
_COUNTRY_TO_ISO2 = {
    "Japan": "JP", "China": "CN", "United States": "US", "Russia": "RU",
    "Ukraine": "UA", "Germany": "DE", "South Korea": "KR", "India": "IN",
    "Taiwan": "TW", "Indonesia": "ID", "Thailand": "TH", "Vietnam": "VN",
    "Philippines": "PH", "Malaysia": "MY", "Singapore": "SG", "Myanmar": "MM",
    "Cambodia": "KH", "Bangladesh": "BD", "Sri Lanka": "LK", "Pakistan": "PK",
    "Iran": "IR", "Iraq": "IQ", "Saudi Arabia": "SA", "UAE": "AE",
    "Israel": "IL", "Turkey": "TR", "Egypt": "EG", "South Africa": "ZA",
    "Nigeria": "NG", "Kenya": "KE", "Ethiopia": "ET", "Brazil": "BR",
    "Mexico": "MX", "Argentina": "AR", "Chile": "CL", "Colombia": "CO",
    "Peru": "PE", "United Kingdom": "GB", "France": "FR", "Italy": "IT",
    "Spain": "ES", "Netherlands": "NL", "Poland": "PL", "Australia": "AU",
    "New Zealand": "NZ", "Canada": "CA", "North Korea": "KP", "Syria": "SY",
    "Yemen": "YE", "Lebanon": "LB", "Libya": "LY", "Sudan": "SD",
    "Somalia": "SO", "Venezuela": "VE", "Cuba": "CU", "Afghanistan": "AF",
    "Nepal": "NP", "Mongolia": "MN", "Kazakhstan": "KZ", "Uzbekistan": "UZ",
    "Turkmenistan": "TM", "Azerbaijan": "AZ", "Georgia": "GE",
    "Romania": "RO", "Hungary": "HU", "Czech Republic": "CZ",
    "Slovakia": "SK", "Bulgaria": "BG", "Serbia": "RS", "Croatia": "HR",
    "Greece": "GR", "Portugal": "PT", "Sweden": "SE", "Norway": "NO",
    "Finland": "FI", "Denmark": "DK", "Belgium": "BE", "Switzerland": "CH",
    "Austria": "AT", "Ireland": "IE",
}

# ISO2→ISO3マッピング（フロントエンド用）
_ISO2_TO_ISO3 = {
    "JP":"JPN","CN":"CHN","US":"USA","RU":"RUS","UA":"UKR","DE":"DEU","KR":"KOR",
    "IN":"IND","TW":"TWN","ID":"IDN","TH":"THA","VN":"VNM","PH":"PHL","MY":"MYS",
    "SG":"SGP","MM":"MMR","KH":"KHM","BD":"BGD","LK":"LKA","PK":"PAK",
    "IR":"IRN","IQ":"IRQ","SA":"SAU","AE":"ARE","IL":"ISR","TR":"TUR",
    "EG":"EGY","ZA":"ZAF","NG":"NGA","KE":"KEN","ET":"ETH","BR":"BRA",
    "MX":"MEX","AR":"ARG","CL":"CHL","CO":"COL","PE":"PER","GB":"GBR",
    "FR":"FRA","IT":"ITA","ES":"ESP","NL":"NLD","PL":"POL","AU":"AUS",
    "NZ":"NZL","CA":"CAN","KP":"PRK","SY":"SYR","YE":"YEM","LB":"LBN",
    "LY":"LBY","SD":"SDN","SO":"SOM","VE":"VEN","CU":"CUB","AF":"AFG",
    "NP":"NPL","MN":"MNG","KZ":"KAZ","UZ":"UZB","TM":"TKM","AZ":"AZE",
    "GE":"GEO","RO":"ROU","HU":"HUN","CZ":"CZE","SK":"SVK","BG":"BGR",
    "RS":"SRB","HR":"HRV","GR":"GRC","PT":"PRT","SE":"SWE","NO":"NOR",
    "FI":"FIN","DK":"DNK","BE":"BEL","CH":"CHE","AT":"AUT","IE":"IRL",
}

_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'data', 'timeseries.db')


def _get_db():
    """timeseries.db接続を取得"""
    return sqlite3.connect(_DB_PATH)


@router.get("/global-risk")
async def get_global_risk():
    """ダッシュボード用の全国リスクサマリー（timeseries.dbから最新スコア取得）"""
    countries = {}
    try:
        conn = _get_db()
        # 各国×次元の最新スコアを取得
        rows = conn.execute('''
            SELECT rs.location, rs.dimension, rs.score
            FROM risk_scores rs
            INNER JOIN (
                SELECT location, dimension, MAX(timestamp) as max_ts
                FROM risk_scores
                GROUP BY location, dimension
            ) latest ON rs.location = latest.location
                    AND rs.dimension = latest.dimension
                    AND rs.timestamp = latest.max_ts
            ORDER BY rs.location, rs.dimension
        ''').fetchall()
        conn.close()

        for loc, dim, score in rows:
            iso2 = _COUNTRY_TO_ISO2.get(loc)
            if not iso2:
                continue
            iso3 = _ISO2_TO_ISO3.get(iso2, iso2)
            if iso3 not in countries:
                countries[iso3] = {'iso3': iso3, 'iso2': iso2, 'name': loc, 'dimensions': {}}
            if dim == 'overall':
                countries[iso3]['overall_score'] = round(score, 1) if score else 0
            else:
                countries[iso3]['dimensions'][dim] = round(score, 1) if score else 0

        # リスクレベル判定
        for c in countries.values():
            s = c.get('overall_score', 0)
            c['risk_level'] = (
                'CRITICAL' if s >= 80 else
                'HIGH' if s >= 60 else
                'MEDIUM' if s >= 40 else
                'LOW' if s >= 20 else
                'MINIMAL'
            )
    except Exception as e:
        logger.warning("timeseries.db読み取り失敗: %s", e)

    return {
        'countries': list(countries.values()),
        'count': len(countries),
        'generated_at': datetime.utcnow().isoformat(),
    }


@router.get("/chokepoints")
async def get_chokepoints():
    """チョークポイントリスク（静的データ + 近隣国リスクで動的調整）"""
    chokepoints = [
        {'id': 'bab', 'name': 'バベルマンデブ', 'lat': 12.58, 'lon': 43.47, 'base_risk': 82, 'status': 'フーシ派攻撃'},
        {'id': 'suez', 'name': 'スエズ運河', 'lat': 30.42, 'lon': 32.35, 'base_risk': 67, 'status': '通航制限'},
        {'id': 'hormuz', 'name': 'ホルムズ海峡', 'lat': 26.57, 'lon': 56.25, 'base_risk': 74, 'status': 'イラン緊張'},
        {'id': 'malacca', 'name': 'マラッカ海峡', 'lat': 1.25, 'lon': 103.82, 'base_risk': 36, 'status': '通常運航'},
        {'id': 'panama', 'name': 'パナマ運河', 'lat': 9.08, 'lon': -79.68, 'base_risk': 49, 'status': '水位低下'},
        {'id': 'taiwan', 'name': '台湾海峡', 'lat': 24.5, 'lon': 119.5, 'base_risk': 55, 'status': '監視強化'},
        {'id': 'cape', 'name': '喜望峰', 'lat': -34.35, 'lon': 18.47, 'base_risk': 28, 'status': '迂回航路増'},
    ]

    # 近隣国overallリスクで調整（70%静的 + 30%近隣国平均）
    adjustments = {
        'hormuz': ['Iran'],
        'bab': ['Yemen'],
        'suez': ['Egypt'],
        'taiwan': ['Taiwan', 'China'],
        'malacca': ['Singapore', 'Malaysia', 'Indonesia'],
    }

    try:
        conn = _get_db()
        for cp in chokepoints:
            adj_countries = adjustments.get(cp['id'], [])
            if adj_countries:
                scores = []
                for c in adj_countries:
                    row = conn.execute(
                        'SELECT score FROM risk_scores WHERE location=? AND dimension=? ORDER BY timestamp DESC LIMIT 1',
                        (c, 'overall')
                    ).fetchone()
                    if row:
                        scores.append(row[0])
                if scores:
                    avg_nearby = sum(scores) / len(scores)
                    cp['risk'] = round(cp['base_risk'] * 0.7 + avg_nearby * 0.3)
                else:
                    cp['risk'] = cp['base_risk']
            else:
                cp['risk'] = cp['base_risk']

            cp['color'] = '#ff4d4d' if cp['risk'] >= 70 else '#ffa94d' if cp['risk'] >= 50 else '#51cf66'
        conn.close()
    except Exception as e:
        logger.warning("チョークポイント動的調整失敗: %s", e)
        for cp in chokepoints:
            cp['risk'] = cp['base_risk']
            cp['color'] = '#ff4d4d' if cp['risk'] >= 70 else '#ffa94d' if cp['risk'] >= 50 else '#51cf66'

    return {'chokepoints': chokepoints, 'generated_at': datetime.utcnow().isoformat()}
