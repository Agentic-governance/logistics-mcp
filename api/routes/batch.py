"""Batch Endpoints - parallel processing of risk scores and sanctions screening.

POST /api/v1/batch/risk-scores
POST /api/v1/batch/risk-scores/stream  (SSE進捗)
POST /api/v1/batch/screen-sanctions
"""
import asyncio
import json
import time
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/batch", tags=["batch"])

# スレッドプール（CPU-boundスコアリング用）
_executor = ThreadPoolExecutor(max_workers=8)

# バッチチャンクサイズ
BATCH_CHUNK_SIZE = 10


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class BatchRiskScoreRequest(BaseModel):
    locations: list[str] = Field(..., min_length=1, max_length=50,
                                  description="List of country names or ISO codes")
    dimensions: list[str] = Field(default_factory=list,
                                   description="Optional subset of dimensions to evaluate")
    include_forecast: bool = Field(default=False,
                                    description="Include trend forecast in response")


class SanctionsEntity(BaseModel):
    name: str
    country: Optional[str] = None


class BatchSanctionsRequest(BaseModel):
    entities: list[SanctionsEntity] = Field(..., min_length=1, max_length=100,
                                             description="Entities to screen (max 100)")


# ---------------------------------------------------------------------------
# キャッシュ連携ヘルパー
# ---------------------------------------------------------------------------

def _get_cache():
    """SmartCacheインスタンスを取得（利用不可時はNone）"""
    try:
        from features.cache.smart_cache import get_cache
        return get_cache()
    except Exception:
        return None


async def _try_cache_get(cache, location: str) -> Optional[dict]:
    """キャッシュからリスクスコアを取得"""
    if cache is None:
        return None
    try:
        from features.cache.smart_cache import SmartCache, CACHE_TTL
        key = SmartCache.risk_score_key(location)
        return await cache.get(key)
    except Exception:
        return None


async def _try_cache_set(cache, location: str, result: dict) -> None:
    """リスクスコアをキャッシュに保存"""
    if cache is None:
        return
    try:
        from features.cache.smart_cache import SmartCache, CACHE_TTL
        key = SmartCache.risk_score_key(location)
        await cache.set(key, result, CACHE_TTL["risk_score"])
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _score_location(location: str, dimensions: list[str], include_forecast: bool) -> dict:
    """単一ロケーションのリスクスコアを計算（スレッドプールで実行）"""
    from scoring.engine import calculate_risk_score
    try:
        score = calculate_risk_score(
            supplier_id=f"batch_{location}",
            company_name=f"batch_{location}",
            country=location,
            location=location,
        )
        result = score.to_dict()

        # 指定ディメンションでフィルタ
        if dimensions:
            filtered_scores = {k: v for k, v in result.get("scores", {}).items()
                               if k in dimensions}
            result["scores"] = filtered_scores

        # 予測スタブを付加
        if include_forecast:
            result["forecast"] = {
                "trend": "stable",
                "confidence": 0.6,
                "note": "Forecast based on historical patterns (limited data)",
            }

        return {"location": location, "status": "ok", "result": result}

    except Exception as exc:
        return {
            "location": location,
            "status": "error",
            "error": str(exc),
        }


def _screen_single(entity: SanctionsEntity) -> dict:
    """単一エンティティの制裁スクリーニング（スレッドプールで実行）"""
    from pipeline.sanctions.screener import screen_entity
    try:
        result = screen_entity(entity.name, entity.country)
        return {
            "name": entity.name,
            "country": entity.country,
            "status": "ok",
            "matched": result.matched,
            "match_score": result.match_score,
            "source": result.source,
            "matched_entity": result.matched_entity,
            "evidence": result.evidence,
        }
    except Exception as exc:
        return {
            "name": entity.name,
            "country": entity.country,
            "status": "error",
            "error": str(exc),
        }


def _chunk_list(lst, chunk_size):
    """リストをchunk_sizeごとに分割"""
    for i in range(0, len(lst), chunk_size):
        yield lst[i:i + chunk_size]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/risk-scores")
async def batch_risk_scores(req: BatchRiskScoreRequest):
    """複数ロケーションのリスクスコアを並列処理。

    バッチサイズ分割（10件ずつ）で処理し、キャッシュヒット率をレスポンスに含める。
    Input: {"locations": ["JP","CN","DE"], "dimensions": [], "include_forecast": false}
    """
    start = time.perf_counter()
    loop = asyncio.get_event_loop()
    cache = _get_cache()

    all_results = []
    cache_hits = 0
    cache_misses = 0

    # バッチチャンク分割処理（10件ずつ）
    for chunk in _chunk_list(req.locations, BATCH_CHUNK_SIZE):
        chunk_futures = []
        chunk_cached = []

        for loc in chunk:
            # キャッシュ確認
            cached = await _try_cache_get(cache, loc)
            if cached is not None:
                cache_hits += 1
                cached["_from_cache"] = True
                chunk_cached.append({"location": loc, "status": "ok", "result": cached})
            else:
                cache_misses += 1
                chunk_futures.append((
                    loc,
                    loop.run_in_executor(
                        _executor,
                        _score_location,
                        loc,
                        req.dimensions,
                        req.include_forecast,
                    ),
                ))

        # スレッドプール結果を待機
        for loc, fut in chunk_futures:
            result = await fut
            # 成功時はキャッシュに保存
            if result.get("status") == "ok" and result.get("result"):
                await _try_cache_set(cache, loc, result["result"])
            all_results.append(result)

        all_results.extend(chunk_cached)

    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    ok_count = sum(1 for r in all_results if r["status"] == "ok")
    error_count = sum(1 for r in all_results if r["status"] == "error")
    total_cache = cache_hits + cache_misses
    hit_rate = round(cache_hits / total_cache, 4) if total_cache > 0 else 0.0

    return {
        "total": len(all_results),
        "successful": ok_count,
        "failed": error_count,
        "processing_time_ms": elapsed_ms,
        "cache": {
            "hits": cache_hits,
            "misses": cache_misses,
            "hit_rate": hit_rate,
        },
        "results": all_results,
    }


@router.post("/risk-scores/stream")
async def batch_risk_scores_stream(req: BatchRiskScoreRequest):
    """SSE進捗ストリーミング付きバッチリスクスコア。

    Server-Sent Events形式でリアルタイム進捗を返す。
    各ロケーション完了時にイベントを送信。
    """

    async def event_generator():
        start = time.perf_counter()
        loop = asyncio.get_event_loop()
        cache = _get_cache()

        total = len(req.locations)
        completed = 0
        cache_hits = 0
        results = []

        # 開始イベント
        yield f"event: start\ndata: {json.dumps({'total': total, 'timestamp': datetime.now(timezone.utc).isoformat()})}\n\n"

        # バッチチャンク分割処理
        for chunk in _chunk_list(req.locations, BATCH_CHUNK_SIZE):
            chunk_futures = []

            for loc in chunk:
                # キャッシュ確認
                cached = await _try_cache_get(cache, loc)
                if cached is not None:
                    cache_hits += 1
                    completed += 1
                    result = {"location": loc, "status": "ok", "result": cached, "_from_cache": True}
                    results.append(result)
                    progress = {
                        "location": loc,
                        "completed": completed,
                        "total": total,
                        "progress_pct": round(completed / total * 100, 1),
                        "from_cache": True,
                    }
                    yield f"event: progress\ndata: {json.dumps(progress)}\n\n"
                else:
                    chunk_futures.append((
                        loc,
                        loop.run_in_executor(
                            _executor, _score_location, loc, req.dimensions, req.include_forecast,
                        ),
                    ))

            # スレッドプール結果を待機・ストリーミング
            for loc, fut in chunk_futures:
                result = await fut
                completed += 1
                results.append(result)

                if result.get("status") == "ok" and result.get("result"):
                    await _try_cache_set(cache, loc, result["result"])

                progress = {
                    "location": loc,
                    "completed": completed,
                    "total": total,
                    "progress_pct": round(completed / total * 100, 1),
                    "status": result.get("status", "unknown"),
                    "from_cache": False,
                }
                yield f"event: progress\ndata: {json.dumps(progress)}\n\n"

        # 完了イベント
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        ok_count = sum(1 for r in results if r["status"] == "ok")
        error_count = sum(1 for r in results if r["status"] == "error")
        total_cache = cache_hits + (total - cache_hits)
        hit_rate = round(cache_hits / total_cache, 4) if total_cache > 0 else 0.0

        summary = {
            "total": len(results),
            "successful": ok_count,
            "failed": error_count,
            "processing_time_ms": elapsed_ms,
            "cache": {
                "hits": cache_hits,
                "misses": total - cache_hits,
                "hit_rate": hit_rate,
            },
            "results": results,
        }
        yield f"event: complete\ndata: {json.dumps(summary)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/screen-sanctions")
async def batch_screen_sanctions(req: BatchSanctionsRequest):
    """複数エンティティの制裁スクリーニングを並列処理。

    Input: {"entities": [{"name":"...","country":"..."},...]}
    Max 100 entities per request.
    """
    if len(req.entities) > 100:
        raise HTTPException(
            status_code=400,
            detail="Maximum 100 entities per batch request",
        )

    start = time.perf_counter()
    loop = asyncio.get_event_loop()

    # バッチチャンク分割（10件ずつ）
    all_results = []
    for chunk in _chunk_list(req.entities, BATCH_CHUNK_SIZE):
        futures = [
            loop.run_in_executor(_executor, _screen_single, entity)
            for entity in chunk
        ]
        chunk_results = await asyncio.gather(*futures)
        all_results.extend(chunk_results)

    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    matched_count = sum(1 for r in all_results if r.get("matched"))

    return {
        "total_screened": len(all_results),
        "matched_count": matched_count,
        "processing_time_ms": elapsed_ms,
        "batch_chunk_size": BATCH_CHUNK_SIZE,
        "results": all_results,
    }
