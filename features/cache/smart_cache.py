"""SmartCache - Redis/SQLiteデュアルバックエンドキャッシュ

Redis利用可能時はRedisを使用し、なければSQLiteにフォールバック。
キャッシュキー設計:
  risk_score:{location}:{version}    TTL=3600   (1時間)
  sanctions:{entity_md5}             TTL=86400  (24時間)
  bom_analysis:{bom_hash}            TTL=7200   (2時間)
  tier_inference:{country}:{hs}      TTL=2592000 (30日)
"""
import json
import hashlib
import logging
import os
import sqlite3
import time
from typing import Optional

logger = logging.getLogger(__name__)

# --- キャッシュキーTTLプリセット ---
CACHE_TTL = {
    "risk_score": 3600,        # 1時間
    "sanctions": 86400,        # 24時間
    "bom_analysis": 7200,      # 2時間
    "tier_inference": 2592000,  # 30日
}


def _make_key(prefix: str, *parts: str) -> str:
    """キャッシュキーを生成"""
    return ":".join([prefix] + list(parts))


def _md5(value: str) -> str:
    """MD5ハッシュを生成（キャッシュキー用）"""
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def redis_available() -> bool:
    """Redisが利用可能か確認"""
    try:
        import redis
        host = os.environ.get("REDIS_HOST", "localhost")
        port = int(os.environ.get("REDIS_PORT", "6379"))
        r = redis.Redis(host=host, port=port, socket_connect_timeout=2)
        r.ping()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Redis バックエンド
# ---------------------------------------------------------------------------
class RedisCache:
    """Redisキャッシュバックエンド"""

    def __init__(self):
        import redis
        host = os.environ.get("REDIS_HOST", "localhost")
        port = int(os.environ.get("REDIS_PORT", "6379"))
        db = int(os.environ.get("REDIS_DB", "0"))
        self.client = redis.Redis(
            host=host, port=port, db=db,
            decode_responses=True,
            socket_connect_timeout=5,
        )
        logger.info("RedisCache初期化完了: %s:%d db=%d", host, port, db)

    async def get(self, key: str) -> Optional[dict]:
        """キャッシュ値を取得"""
        try:
            raw = self.client.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as e:
            logger.warning("Redisキャッシュ読取エラー [%s]: %s", key, e)
            return None

    async def set(self, key: str, value: dict, ttl: int) -> None:
        """キャッシュ値を設定（TTL秒で失効）"""
        try:
            self.client.setex(key, ttl, json.dumps(value, ensure_ascii=False))
        except Exception as e:
            logger.warning("Redisキャッシュ書込エラー [%s]: %s", key, e)

    async def invalidate_pattern(self, pattern: str) -> int:
        """パターンに一致するキーを無効化"""
        try:
            keys = self.client.keys(pattern)
            if keys:
                self.client.delete(*keys)
                logger.info("Redis: %d件のキーを無効化 (pattern=%s)", len(keys), pattern)
                return len(keys)
            return 0
        except Exception as e:
            logger.warning("Redisパターン無効化エラー: %s", e)
            return 0

    async def stats(self) -> dict:
        """キャッシュ統計情報を取得"""
        try:
            info = self.client.info("keyspace")
            db_info = info.get("db0", {})
            return {
                "backend": "redis",
                "keys": db_info.get("keys", 0),
                "expires": db_info.get("expires", 0),
            }
        except Exception:
            return {"backend": "redis", "keys": 0, "error": "接続不可"}


# ---------------------------------------------------------------------------
# SQLite バックエンド
# ---------------------------------------------------------------------------
class SQLiteCache:
    """SQLiteキャッシュバックエンド（Redisフォールバック）"""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            db_path = os.path.join(base_dir, "data", "cache.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._init_db()
        logger.info("SQLiteCache初期化完了: %s", db_path)

    def _init_db(self):
        """キャッシュテーブルを作成"""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    created_at REAL NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache(expires_at)")
            conn.commit()
        finally:
            conn.close()

    def _cleanup_expired(self):
        """期限切れエントリを削除（バックグラウンド）"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("DELETE FROM cache WHERE expires_at < ?", (time.time(),))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug("キャッシュクリーンアップエラー: %s", e)

    async def get(self, key: str) -> Optional[dict]:
        """キャッシュ値を取得"""
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.execute(
                "SELECT value FROM cache WHERE key = ? AND expires_at > ?",
                (key, time.time()),
            )
            row = cur.fetchone()
            conn.close()
            if row is None:
                return None
            return json.loads(row[0])
        except Exception as e:
            logger.warning("SQLiteキャッシュ読取エラー [%s]: %s", key, e)
            return None

    async def set(self, key: str, value: dict, ttl: int) -> None:
        """キャッシュ値を設定（TTL秒で失効）"""
        try:
            now = time.time()
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT OR REPLACE INTO cache (key, value, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (key, json.dumps(value, ensure_ascii=False), now + ttl, now),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("SQLiteキャッシュ書込エラー [%s]: %s", key, e)

    async def invalidate_pattern(self, pattern: str) -> int:
        """パターンに一致するキーを無効化（SQLite LIKE構文に変換）"""
        try:
            # Redis glob → SQLite LIKE: * → %, ? → _
            like_pattern = pattern.replace("*", "%").replace("?", "_")
            conn = sqlite3.connect(self.db_path)
            cur = conn.execute("SELECT COUNT(*) FROM cache WHERE key LIKE ?", (like_pattern,))
            count = cur.fetchone()[0]
            conn.execute("DELETE FROM cache WHERE key LIKE ?", (like_pattern,))
            conn.commit()
            conn.close()
            if count:
                logger.info("SQLite: %d件のキーを無効化 (pattern=%s)", count, pattern)
            return count
        except Exception as e:
            logger.warning("SQLiteパターン無効化エラー: %s", e)
            return 0

    async def stats(self) -> dict:
        """キャッシュ統計情報を取得"""
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.execute("SELECT COUNT(*) FROM cache WHERE expires_at > ?", (time.time(),))
            active = cur.fetchone()[0]
            cur = conn.execute("SELECT COUNT(*) FROM cache")
            total = cur.fetchone()[0]
            conn.close()
            return {
                "backend": "sqlite",
                "active_keys": active,
                "total_keys": total,
                "db_path": self.db_path,
            }
        except Exception:
            return {"backend": "sqlite", "active_keys": 0, "error": "読取不可"}


# ---------------------------------------------------------------------------
# SmartCache - 統合キャッシュインターフェース
# ---------------------------------------------------------------------------
class SmartCache:
    """Redis/SQLite自動選択キャッシュ

    使用例:
        cache = SmartCache()

        # リスクスコアのキャッシュ
        key = SmartCache.risk_score_key("Japan", "v1.0")
        cached = await cache.get(key)
        if cached is None:
            result = compute_risk_score(...)
            await cache.set(key, result, CACHE_TTL["risk_score"])

        # パターン無効化
        await cache.invalidate_pattern("risk_score:*")
    """

    def __init__(self):
        if redis_available():
            self.backend = RedisCache()
            self._backend_name = "redis"
        else:
            self.backend = SQLiteCache()
            self._backend_name = "sqlite"
        # 統計カウンター
        self._hits = 0
        self._misses = 0
        logger.info("SmartCache初期化: backend=%s", self._backend_name)

    async def get(self, key: str) -> Optional[dict]:
        """キャッシュ値を取得（ヒット率カウント付き）"""
        result = await self.backend.get(key)
        if result is not None:
            self._hits += 1
        else:
            self._misses += 1
        return result

    async def set(self, key: str, value: dict, ttl: int) -> None:
        """キャッシュ値を設定"""
        await self.backend.set(key, value, ttl)

    async def invalidate_pattern(self, pattern: str) -> int:
        """パターンに一致するキーを無効化"""
        return await self.backend.invalidate_pattern(pattern)

    async def stats(self) -> dict:
        """キャッシュ統計情報（ヒット率含む）"""
        backend_stats = await self.backend.stats()
        total = self._hits + self._misses
        return {
            **backend_stats,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 4) if total > 0 else 0.0,
        }

    @property
    def hit_rate(self) -> float:
        """現在のキャッシュヒット率"""
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    # --- キャッシュキー生成ヘルパー ---

    @staticmethod
    def risk_score_key(location: str, version: str = "v1") -> str:
        """リスクスコア用キャッシュキー"""
        return _make_key("risk_score", location.lower(), version)

    @staticmethod
    def sanctions_key(entity_name: str) -> str:
        """制裁スクリーニング用キャッシュキー"""
        return _make_key("sanctions", _md5(entity_name.lower()))

    @staticmethod
    def bom_analysis_key(bom_json: str) -> str:
        """BOM分析用キャッシュキー"""
        return _make_key("bom_analysis", _md5(bom_json))

    @staticmethod
    def tier_inference_key(country: str, hs_code: str) -> str:
        """Tier推定用キャッシュキー"""
        return _make_key("tier_inference", country.lower(), hs_code)


# --- シングルトンインスタンス ---
_cache_instance: Optional[SmartCache] = None


def get_cache() -> SmartCache:
    """SmartCacheのシングルトンインスタンスを取得"""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = SmartCache()
    return _cache_instance
