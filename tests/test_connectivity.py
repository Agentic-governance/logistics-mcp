"""SCRI Platform v0.4.0 — データソース疎通テスト
全APIエンドポイントへの到達可能性を確認する。
"""
import sys
import os
import time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check_endpoint(name: str, url: str, timeout: int = 15) -> dict:
    """単一エンドポイントの疎通テスト"""
    start = time.time()
    try:
        resp = requests.get(
            url, timeout=timeout, allow_redirects=True,
            headers={"User-Agent": "SCRI-Platform/0.4.0"}
        )
        latency = (time.time() - start) * 1000
        return {
            "name": name,
            "url": url,
            "reachable": resp.status_code < 500,
            "status_code": resp.status_code,
            "latency_ms": round(latency, 1),
            "error": None,
        }
    except requests.exceptions.RequestException as e:
        latency = (time.time() - start) * 1000
        return {
            "name": name,
            "url": url,
            "reachable": False,
            "status_code": None,
            "latency_ms": round(latency, 1),
            "error": str(e)[:80],
        }


ENDPOINTS = [
    # --- 災害 ---
    ("GDACS", "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"),
    ("USGS Earthquake", "https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&limit=1"),
    ("BMKG Indonesia", "https://data.bmkg.go.id/DataMKG/TEWS/autogempa.json"),
    # --- 海上・港湾 ---
    ("IMF PortWatch", "https://portwatch.imf.org/api/v1/events"),
    # --- 紛争 ---
    ("ACLED", "https://api.acleddata.com/"),
    # --- 経済 ---
    ("World Bank", "https://api.worldbank.org/v2/country/JPN?format=json"),
    ("Frankfurter ECB", "https://api.frankfurter.dev/latest"),
    ("UN Comtrade", "https://comtradeapi.un.org/data/v1/getDA/C/A/HS?reporterCode=392&period=2023&partnerCode=0&flowCode=X"),
    ("FRED", "https://api.stlouisfed.org/fred/series?series_id=DCOILWTICO&api_key=DEMO_KEY&file_type=json"),
    # --- 感染症・人道 ---
    ("Disease.sh", "https://disease.sh/v3/covid-19/all"),
    ("ReliefWeb", "https://api.reliefweb.int/v1/disasters?limit=1"),
    ("WFP HungerMap", "https://api.hungermapdata.org/v2/info/country"),
    # --- 気象 ---
    ("Open-Meteo", "https://api.open-meteo.com/v1/forecast?latitude=35.68&longitude=139.69&current_weather=true"),
    ("NOAA NHC", "https://www.nhc.noaa.gov/CurrentSummaries.json"),
    ("NOAA SWPC", "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"),
    # --- コンプライアンス ---
    ("INFORM Risk", "https://drmkc.jrc.ec.europa.eu/inform-index/API/InformAPI/countries/Scores/?WorkflowId=503"),
    # --- インフラ ---
    ("IODA", "https://api.ioda.inetintel.cc.gatech.edu/v2/signals/raw/country/JP?from=-1h&until=now"),
    # --- 制裁 ---
    ("OFAC SDN", "https://www.treasury.gov/ofac/downloads/sdn.xml"),
    ("EU FSF", "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw"),
    ("SECO", "https://www.seco.admin.ch/dam/seco/de/dokumente/Aussenwirtschaft/Wirtschaftsbeziehungen/Exportkontrollen/Sanktionen/Verordnungen/consolidated_list.xml.download.xml/Consolidated%20list.xml"),
    ("OFSI UK", "https://assets.publishing.service.gov.uk/media/65a8ae2f7eb21e000dca135d/UK_Sanctions_List.ods"),
    ("DFAT Australia", "https://www.dfat.gov.au/sites/default/files/regulation8_consolidated.xlsx"),
    # --- v0.4.0 新規 ---
    ("OONI", "https://api.ooni.io/api/v1/measurements?limit=1"),
    ("CISA KEV", "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"),
    # --- 気象庁 ---
    ("JMA", "https://www.jma.go.jp/bosai/warning/data/warning/130000.json"),
]


def run_all_tests():
    """全エンドポイントの疎通テストを実行"""
    print("=" * 80)
    print("SCRI Platform v0.4.0 — Data Source Connectivity Test")
    print("=" * 80)
    print()

    results = []
    ok_count = 0
    fail_count = 0

    for name, url in ENDPOINTS:
        result = check_endpoint(name, url)
        results.append(result)

        status = "OK" if result["reachable"] else "FAIL"
        if result["reachable"]:
            ok_count += 1
        else:
            fail_count += 1

        status_code = result["status_code"] or "---"
        latency = f"{result['latency_ms']:>7.1f}ms"

        print(f"  [{status:>4}] {name:<25} {status_code:<5} {latency}")
        if result["error"]:
            print(f"         Error: {result['error']}")

    print()
    print("-" * 80)
    print(f"  Total: {len(results)} | OK: {ok_count} | FAIL: {fail_count}")
    print(f"  Success Rate: {ok_count/len(results)*100:.1f}%")
    print("=" * 80)

    return results


if __name__ == "__main__":
    run_all_tests()
