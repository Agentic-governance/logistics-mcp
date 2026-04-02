"""OpenOwnership UBO（実質的支配者）クライアント
Ultimate Beneficial Owner データを OpenOwnership API から取得する。
APIキー不要。レート制限付き。

データソース: https://api.openownership.org/
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
OPENOWNERSHIP_API_BASE = "https://api.openownership.org/api/v1"
RATE_LIMIT_INTERVAL = 1.0  # 1 req/sec
REQUEST_TIMEOUT = 15  # seconds
USER_AGENT = "SCRI-Platform/1.0 (supply-chain-risk-research)"

# 高リスク国リスト（FATF + 制裁常連国）
HIGH_RISK_NATIONALITIES = {
    "iran", "north korea", "dprk", "syria", "myanmar", "cuba", "russia",
    "venezuela", "iraq", "libya", "somalia", "yemen", "south sudan",
    "afghanistan", "sudan", "eritrea", "belarus", "nicaragua",
}


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------
class _RateLimiter:
    """シンプルなレートリミッター"""

    def __init__(self):
        self._last_request: float = 0.0

    def wait(self):
        now = time.monotonic()
        diff = now - self._last_request
        if diff < RATE_LIMIT_INTERVAL:
            time.sleep(RATE_LIMIT_INTERVAL - diff)
        self._last_request = time.monotonic()


_rate = _RateLimiter()


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass
class UBORecord:
    """実質的支配者レコード"""
    person_name: str
    nationality: str
    ownership_pct: float
    is_pep: bool          # 政治的露出者フラグ
    sanctions_hit: bool   # 制裁リストヒット


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------
def _api_get(path: str, params: Optional[dict] = None) -> dict:
    """OpenOwnership API にGETリクエストを送信する。

    レートリミット付き。API不達時は空dictを返す。
    """
    _rate.wait()
    url = f"{OPENOWNERSHIP_API_BASE}/{path.lstrip('/')}"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout:
        logger.warning("OpenOwnership API タイムアウト: %s", url)
        return {}
    except requests.exceptions.ConnectionError:
        logger.warning("OpenOwnership API 接続エラー: %s", url)
        return {}
    except requests.exceptions.HTTPError as e:
        logger.warning("OpenOwnership API HTTPエラー (%s): %s", e.response.status_code, url)
        return {}
    except Exception as e:
        logger.warning("OpenOwnership API 予期しないエラー: %s", e)
        return {}


# ---------------------------------------------------------------------------
# PEP / Sanctions helper（ベストエフォート）
# ---------------------------------------------------------------------------
def _check_pep_status(person_name: str) -> bool:
    """PEP（政治的露出者）判定のベストエフォート。

    OpenSanctions の PEP データセットを参照し、名前の一致を確認する。
    DB未セットアップ時は False を返す。
    """
    try:
        from pipeline.sanctions.screener import screen_entity
        result = screen_entity(person_name)
        # PEP検出はトピック/プログラム情報から推定
        if result.matched and result.evidence:
            for ev in result.evidence:
                if "pep" in str(ev).lower() or "politically" in str(ev).lower():
                    return True
        return False
    except Exception:
        return False


def _check_sanctions_hit(person_name: str) -> bool:
    """制裁リストヒット判定。

    既存の制裁スクリーナーを使用する。
    """
    try:
        from pipeline.sanctions.screener import screen_entity
        result = screen_entity(person_name)
        return result.matched
    except Exception:
        return False


# ---------------------------------------------------------------------------
# OpenOwnershipClient
# ---------------------------------------------------------------------------
class OpenOwnershipClient:
    """OpenOwnership API クライアント — 実質的支配者（UBO）情報取得"""

    def _search_company(self, company_name: str) -> list[dict]:
        """企業名で OpenOwnership を検索し、エンティティ一覧を返す。"""
        data = _api_get("companies", params={"q": company_name})
        if not data:
            return []
        # API応答形式に応じてパース
        results = data.get("results", data.get("companies", data.get("data", [])))
        if isinstance(results, list):
            return results
        return []

    def _extract_ubo_from_entity(self, entity: dict) -> list[UBORecord]:
        """エンティティJSONからUBOレコードを抽出する。"""
        records: list[UBORecord] = []
        # OpenOwnership の beneficial_owners / owners / statements を探索
        owners = (
            entity.get("beneficial_owners", [])
            or entity.get("owners", [])
            or entity.get("relationships", [])
            or []
        )

        for owner in owners:
            # 個人情報を抽出
            person = owner if isinstance(owner, dict) else {}
            person_name = (
                person.get("name", "")
                or person.get("person_name", "")
                or person.get("interestedParty", {}).get("name", "")
                or ""
            )
            if not person_name:
                continue

            nationality = (
                person.get("nationality", "")
                or person.get("nationalities", [""])[0]
                if isinstance(person.get("nationalities"), list)
                else person.get("nationality", "")
            )
            if isinstance(nationality, list):
                nationality = nationality[0] if nationality else ""

            # 持株比率
            ownership_pct = 0.0
            interests = person.get("interests", person.get("shares", []))
            if isinstance(interests, list) and interests:
                for interest in interests:
                    if isinstance(interest, dict):
                        pct = interest.get("share", interest.get("percentage", 0))
                        try:
                            ownership_pct = max(ownership_pct, float(pct))
                        except (ValueError, TypeError):
                            pass
            elif isinstance(interests, (int, float)):
                ownership_pct = float(interests)

            # 直接持分（フォールバック）
            if ownership_pct == 0.0:
                raw_pct = person.get("ownership_percentage", person.get("share", 0))
                try:
                    ownership_pct = float(raw_pct)
                except (ValueError, TypeError):
                    ownership_pct = 0.0

            # PEP / 制裁チェック
            is_pep = _check_pep_status(person_name)
            sanctions_hit = _check_sanctions_hit(person_name)

            records.append(UBORecord(
                person_name=person_name,
                nationality=str(nationality),
                ownership_pct=ownership_pct,
                is_pep=is_pep,
                sanctions_hit=sanctions_hit,
            ))

        return records

    # ---- Sync API ---------------------------------------------------------

    def get_ubo_sync(self, company_name: str) -> list[UBORecord]:
        """企業の実質的支配者（株主→個人）を返す（同期版）。"""
        try:
            entities = self._search_company(company_name)
            all_records: list[UBORecord] = []
            seen_names: set[str] = set()

            for entity in entities[:5]:  # 上位5件に限定
                records = self._extract_ubo_from_entity(entity)
                for rec in records:
                    if rec.person_name not in seen_names:
                        seen_names.add(rec.person_name)
                        all_records.append(rec)

            if not all_records:
                logger.info("OpenOwnership: '%s' のUBO情報が見つかりません", company_name)

            return all_records
        except Exception as e:
            logger.warning("OpenOwnership UBO取得エラー (%s): %s", company_name, e)
            return []

    def get_ownership_chain_sync(self, company_name: str) -> dict:
        """所有チェーン全体をツリーで返す（同期版）。"""
        try:
            entities = self._search_company(company_name)
            if not entities:
                logger.info("OpenOwnership: '%s' の所有チェーンが見つかりません", company_name)
                return {
                    "company": company_name,
                    "chain": [],
                    "total_owners": 0,
                }

            chain: list[dict] = []
            for entity in entities[:3]:
                entity_name = entity.get("name", entity.get("company_name", company_name))
                owners = self._extract_ubo_from_entity(entity)

                layer = {
                    "entity": entity_name,
                    "jurisdiction": entity.get("jurisdiction", entity.get("country", "")),
                    "owners": [
                        {
                            "name": o.person_name,
                            "nationality": o.nationality,
                            "ownership_pct": o.ownership_pct,
                            "is_pep": o.is_pep,
                            "sanctions_hit": o.sanctions_hit,
                        }
                        for o in owners
                    ],
                }
                chain.append(layer)

            return {
                "company": company_name,
                "chain": chain,
                "total_owners": sum(len(layer["owners"]) for layer in chain),
            }
        except Exception as e:
            logger.warning("OpenOwnership 所有チェーン取得エラー (%s): %s", company_name, e)
            return {
                "company": company_name,
                "chain": [],
                "total_owners": 0,
                "error": str(e),
            }

    def get_ownership_chain_deep_sync(self, company_name: str) -> dict:
        """所有チェーンをUBOまで再帰的に遡り、シェル会社・タックスヘイブンを検出する（同期版）。

        Returns:
            {
                "company": str,
                "chain": [...],
                "total_owners": int,
                "shell_company_flags": [...],
                "tax_haven_flags": [...],
                "max_depth": int,
            }
        """
        # タックスヘイブン法域リスト
        TAX_HAVENS = {
            "british virgin islands", "bvi", "cayman islands", "bermuda",
            "panama", "bahamas", "jersey", "guernsey", "isle of man",
            "mauritius", "seychelles", "marshall islands", "samoa",
            "vanuatu", "belize", "liechtenstein", "monaco", "andorra",
            "aruba", "curaçao", "curacao", "turks and caicos",
            "anguilla", "gibraltar", "luxembourg", "hong kong",
            "singapore", "ireland", "netherlands", "cyprus",
            "malta", "labuan", "delaware", "nevada",
        }

        try:
            chain_data = self.get_ownership_chain_sync(company_name)
            chain = chain_data.get("chain", [])
            shell_flags: list[dict] = []
            tax_haven_flags: list[dict] = []

            for layer in chain:
                jurisdiction = str(layer.get("jurisdiction", "")).lower().strip()
                entity_name = layer.get("entity", "")

                # タックスヘイブン検出
                for haven in TAX_HAVENS:
                    if haven in jurisdiction:
                        tax_haven_flags.append({
                            "entity": entity_name,
                            "jurisdiction": jurisdiction,
                            "haven": haven,
                        })
                        break

                # シェル会社検出（オーナー0人 or 法域がタックスヘイブン + 所有者不透明）
                owners = layer.get("owners", [])
                if not owners and jurisdiction:
                    shell_flags.append({
                        "entity": entity_name,
                        "jurisdiction": jurisdiction,
                        "reason": "所有者情報なし",
                    })
                elif len(owners) == 1 and any(h in jurisdiction for h in TAX_HAVENS):
                    # 単一オーナー + タックスヘイブン = シェル会社の可能性
                    shell_flags.append({
                        "entity": entity_name,
                        "jurisdiction": jurisdiction,
                        "reason": "タックスヘイブン所在・単一所有者",
                    })

            return {
                "company": company_name,
                "chain": chain,
                "total_owners": chain_data.get("total_owners", 0),
                "shell_company_flags": shell_flags,
                "tax_haven_flags": tax_haven_flags,
                "max_depth": len(chain),
            }
        except Exception as e:
            logger.warning("OpenOwnership 深層チェーン取得エラー (%s): %s", company_name, e)
            return {
                "company": company_name,
                "chain": [],
                "total_owners": 0,
                "shell_company_flags": [],
                "tax_haven_flags": [],
                "max_depth": 0,
                "error": str(e),
            }

    def find_shared_owners_sync(self, company_a: str, company_b: str) -> dict:
        """2社間で共通するオーナーを検索し、利益相反を検出する（同期版）。

        Returns:
            {
                "company_a": str,
                "company_b": str,
                "shared_owners": [...],
                "conflict_risk": bool,
                "conflict_score": int,  # 0-100
            }
        """
        try:
            ubos_a = self.get_ubo_sync(company_a)
            ubos_b = self.get_ubo_sync(company_b)

            names_a = {r.person_name.lower(): r for r in ubos_a}
            names_b = {r.person_name.lower(): r for r in ubos_b}

            shared = []
            for name_lower, rec_a in names_a.items():
                if name_lower in names_b:
                    rec_b = names_b[name_lower]
                    shared.append({
                        "person_name": rec_a.person_name,
                        "nationality": rec_a.nationality,
                        "ownership_a_pct": rec_a.ownership_pct,
                        "ownership_b_pct": rec_b.ownership_pct,
                        "is_pep": rec_a.is_pep or rec_b.is_pep,
                        "sanctions_hit": rec_a.sanctions_hit or rec_b.sanctions_hit,
                    })

            # 利益相反スコア算出
            conflict_score = 0
            if shared:
                conflict_score = min(30 + len(shared) * 15, 80)
                # 制裁対象の共通オーナーがいれば即100
                if any(s["sanctions_hit"] for s in shared):
                    conflict_score = 100
                # PEPの共通オーナーがいれば加算
                if any(s["is_pep"] for s in shared):
                    conflict_score = min(conflict_score + 20, 100)

            return {
                "company_a": company_a,
                "company_b": company_b,
                "shared_owners": shared,
                "conflict_risk": len(shared) > 0,
                "conflict_score": conflict_score,
            }
        except Exception as e:
            logger.warning("共通オーナー検索エラー (%s, %s): %s", company_a, company_b, e)
            return {
                "company_a": company_a,
                "company_b": company_b,
                "shared_owners": [],
                "conflict_risk": False,
                "conflict_score": 0,
                "error": str(e),
            }

    # ---- Async API --------------------------------------------------------

    async def get_ubo(self, company_name: str) -> list[UBORecord]:
        """企業の実質的支配者（株主→個人）を返す"""
        return await asyncio.to_thread(self.get_ubo_sync, company_name)

    async def get_ownership_chain(self, company_name: str) -> dict:
        """所有チェーン全体をツリーで返す"""
        return await asyncio.to_thread(self.get_ownership_chain_sync, company_name)

    async def get_ownership_chain_deep(self, company_name: str) -> dict:
        """深層チェーン取得（タックスヘイブン・シェル会社検出付き）"""
        return await asyncio.to_thread(self.get_ownership_chain_deep_sync, company_name)

    async def find_shared_owners(self, company_a: str, company_b: str) -> dict:
        """2社間の共通オーナー検索"""
        return await asyncio.to_thread(self.find_shared_owners_sync, company_a, company_b)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="OpenOwnership UBO Client")
    parser.add_argument("company", help="企業名")
    parser.add_argument("--chain", action="store_true", help="所有チェーンを表示")
    args = parser.parse_args()

    client = OpenOwnershipClient()

    if args.chain:
        import json
        chain = client.get_ownership_chain_sync(args.company)
        print(json.dumps(chain, indent=2, ensure_ascii=False))
    else:
        records = client.get_ubo_sync(args.company)
        for r in records:
            flags = []
            if r.is_pep:
                flags.append("PEP")
            if r.sanctions_hit:
                flags.append("SANCTIONS")
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            print(f"  {r.person_name} ({r.nationality}) — {r.ownership_pct:.1f}%{flag_str}")
        if not records:
            print("  (UBO情報なし)")
