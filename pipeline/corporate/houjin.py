"""法人番号公表サイトAPI
登録: https://www.houjin-bangou.nta.go.jp/webapi/
無料、全法人網羅
"""
import requests
import os

HOUJIN_API_BASE = "https://api.houjin-bangou.nta.go.jp/4"
API_KEY = os.getenv("HOUJIN_API_KEY")


def search_by_name(company_name: str, prefecture: str = None) -> list[dict]:
    """企業名で法人番号検索"""
    params = {
        "id": API_KEY,
        "name": company_name,
        "type": "02",  # JSON形式
        "mode": "1",   # 前方一致
    }
    if prefecture:
        params["prefecture"] = prefecture

    resp = requests.get(f"{HOUJIN_API_BASE}/name", params=params, timeout=10)
    data = resp.json()

    return [
        {
            "corporate_number": c.get("corporateNumber"),
            "name": c.get("name"),
            "address": f"{c.get('prefectureName', '')}{c.get('cityName', '')}{c.get('streetNumber', '')}",
            "status": c.get("kind"),  # 01=国内普通法人
            "close_date": c.get("closeDate"),  # 廃業日（あれば要注意）
            "close_cause": c.get("closeCause"),
        }
        for c in data.get("corporations", [])
    ]


def get_by_number(corporate_number: str) -> dict:
    """法人番号から詳細取得"""
    params = {"id": API_KEY, "number": corporate_number, "type": "02", "history": "1"}
    resp = requests.get(f"{HOUJIN_API_BASE}/num", params=params, timeout=10)
    return resp.json()


def check_corporate_status(company_name: str) -> dict:
    """
    企業の実在・営業状態を確認。
    廃業・解散していた場合は高リスク。
    """
    results = search_by_name(company_name)
    if not results:
        return {"found": False, "risk": "unknown", "evidence": ["法人番号公表サイトに登録なし"]}

    corp = results[0]
    evidence = [f"法人番号: {corp['corporate_number']}"]
    risk = "low"

    if corp.get("close_date"):
        risk = "critical"
        evidence.append(f"廃業済み: {corp['close_date']} ({corp.get('close_cause', '理由不明')})")

    return {"found": True, "risk": risk, "corporate": corp, "evidence": evidence}
