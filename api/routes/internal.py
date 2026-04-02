"""内部データ取込API
POST /api/v1/internal/upload/{data_type} — CSV/Excelファイルアップロード
GET  /api/v1/internal/data-status — 各データの状態確認
DELETE /api/v1/internal/reset — 内部データ全削除
"""
import io
import os
import json
import logging
import tempfile
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/internal", tags=["internal-data"])

# --- ROLE-A 依存モジュール（未完成時は graceful degradation） ---
try:
    from pipeline.internal.logistics_importer import LogisticsImporter, STANDARD_SCHEMA
    _importer = LogisticsImporter()
    _IMPORTER_AVAILABLE = True
except ImportError as e:
    logger.warning(f"LogisticsImporter 読み込み失敗: {e}")
    _IMPORTER_AVAILABLE = False
    _importer = None
    STANDARD_SCHEMA = {}

try:
    from pipeline.internal.internal_data_store import InternalDataStore
    _store = InternalDataStore()
    _STORE_AVAILABLE = True
except (ImportError, Exception) as e:
    logger.warning(f"InternalDataStore 読み込み失敗: {e}")
    _STORE_AVAILABLE = False
    _store = None

# --- インメモリデータ管理（DataStore未実装時のフォールバック） ---
_uploaded_data: dict = {}  # {data_type: {"df": DataFrame, "uploaded_at": str, "rows": int, ...}}

# データ種別マッピング
_UPLOAD_TYPE_MAP = {
    "inventory": "inventory",
    "purchase-orders": "purchase_orders",
    "production-plan": "production_plan",
    "locations": "locations",
    "transport-routes": "transport_routes",
    "costs": "procurement_costs",
}


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def _save_upload(file: UploadFile) -> str:
    """アップロードファイルを一時ファイルに保存し、パスを返す"""
    suffix = os.path.splitext(file.filename or "upload.csv")[1] or ".csv"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = file.file.read()
        tmp.write(content)
        return tmp.name


def _process_upload(tmp_path: str, data_type: str, file_filename: str) -> dict:
    """ファイルをインポート・バリデーションして結果を返す"""
    if not _IMPORTER_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="LogisticsImporter が利用できません。pipeline.internal モジュールを確認してください。",
        )

    try:
        # auto_import でCSV/Excel/JSON自動判定＋列名マッピング
        df = _importer.auto_import(tmp_path, data_type)
        validation = _importer.validate(df, data_type)

        # データ保存
        if _STORE_AVAILABLE:
            try:
                _store.save(data_type, df)
            except Exception as e:
                logger.warning(f"DataStore保存失敗（インメモリにフォールバック）: {e}")
                _uploaded_data[data_type] = {
                    "uploaded_at": datetime.now(timezone.utc).isoformat(),
                    "rows": len(df),
                    "columns": list(df.columns),
                    "filename": file_filename,
                }
        else:
            _uploaded_data[data_type] = {
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
                "rows": len(df),
                "columns": list(df.columns),
                "filename": file_filename,
            }

        return {
            "success": True,
            "data_type": data_type,
            "filename": file_filename,
            "rows_imported": len(df),
            "columns": list(df.columns),
            "validation": {
                "ok": validation.ok,
                "errors": validation.errors,
                "warnings": validation.warnings,
                "row_count": validation.row_count,
                "col_count": validation.col_count,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.error(f"インポートエラー [{data_type}]: {e}")
        raise HTTPException(status_code=400, detail=f"データインポート失敗: {str(e)}")
    finally:
        # 一時ファイル削除
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# エンドポイント: アップロード
# ---------------------------------------------------------------------------

@router.post("/upload/inventory")
async def upload_inventory(file: UploadFile = File(...)):
    """在庫データCSV/Excelアップロード"""
    tmp_path = _save_upload(file)
    return _process_upload(tmp_path, "inventory", file.filename or "unknown")


@router.post("/upload/purchase-orders")
async def upload_purchase_orders(file: UploadFile = File(...)):
    """発注データCSV/Excelアップロード"""
    tmp_path = _save_upload(file)
    return _process_upload(tmp_path, "purchase_orders", file.filename or "unknown")


@router.post("/upload/production-plan")
async def upload_production_plan(file: UploadFile = File(...)):
    """生産計画データCSV/Excelアップロード"""
    tmp_path = _save_upload(file)
    return _process_upload(tmp_path, "production_plan", file.filename or "unknown")


@router.post("/upload/locations")
async def upload_locations(file: UploadFile = File(...)):
    """拠点マスタCSV/Excelアップロード"""
    tmp_path = _save_upload(file)
    return _process_upload(tmp_path, "locations", file.filename or "unknown")


@router.post("/upload/transport-routes")
async def upload_transport_routes(file: UploadFile = File(...)):
    """輸送ルートCSV/Excelアップロード"""
    tmp_path = _save_upload(file)
    return _process_upload(tmp_path, "transport_routes", file.filename or "unknown")


@router.post("/upload/costs")
async def upload_costs(file: UploadFile = File(...)):
    """調達コストCSV/Excelアップロード"""
    tmp_path = _save_upload(file)
    return _process_upload(tmp_path, "procurement_costs", file.filename or "unknown")


# ---------------------------------------------------------------------------
# エンドポイント: データ状態確認
# ---------------------------------------------------------------------------

@router.get("/data-status")
async def get_data_status():
    """各データの最終更新日・件数・品質スコアを返す"""
    status = {}

    all_types = ["inventory", "purchase_orders", "production_plan",
                 "locations", "transport_routes", "procurement_costs"]

    for dt in all_types:
        # DataStore から取得を試みる
        if _STORE_AVAILABLE:
            try:
                info = _store.get_status(dt)
                if info:
                    status[dt] = info
                    continue
            except Exception:
                pass

        # インメモリフォールバック
        if dt in _uploaded_data:
            data = _uploaded_data[dt]
            status[dt] = {
                "exists": True,
                "last_updated": data.get("uploaded_at"),
                "row_count": data.get("rows", 0),
                "columns": data.get("columns", []),
                "filename": data.get("filename", ""),
                "quality_score": 1.0 if data.get("rows", 0) > 0 else 0.0,
            }
        else:
            status[dt] = {
                "exists": False,
                "last_updated": None,
                "row_count": 0,
                "columns": [],
                "filename": "",
                "quality_score": 0.0,
            }

    return {
        "success": True,
        "data_status": status,
        "importer_available": _IMPORTER_AVAILABLE,
        "store_available": _STORE_AVAILABLE,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# エンドポイント: データリセット
# ---------------------------------------------------------------------------

@router.delete("/reset")
async def reset_internal_data():
    """内部データ全削除"""
    global _uploaded_data
    deleted_types = []

    # DataStore リセット
    if _STORE_AVAILABLE:
        try:
            _store.reset_all()
            deleted_types.append("data_store")
        except Exception as e:
            logger.warning(f"DataStoreリセット失敗: {e}")

    # インメモリデータクリア
    cleared = list(_uploaded_data.keys())
    _uploaded_data = {}
    deleted_types.extend(cleared)

    return {
        "success": True,
        "message": "内部データを全削除しました",
        "deleted_types": deleted_types,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
