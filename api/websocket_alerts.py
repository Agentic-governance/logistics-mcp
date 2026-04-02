"""WebSocket リアルタイムアラート配信
FastAPI WebSocket を使用して、リスクアラートをリアルタイムで接続中クライアントへ配信。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import WebSocket, WebSocketDisconnect
from typing import Set
import json
import asyncio
from datetime import datetime


class AlertBroadcaster:
    """WebSocket アラートブロードキャスター

    接続中の全クライアントにリスクアラートを配信する。
    クライアントはサブスクリプションメッセージで監視対象を絞り込める。
    """

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._subscriptions: dict[WebSocket, dict] = {}

    async def connect(self, websocket: WebSocket):
        """新規クライアント接続を受け付ける"""
        await websocket.accept()
        self.active_connections.add(websocket)
        self._subscriptions[websocket] = {"all": True}

    def disconnect(self, websocket: WebSocket):
        """クライアント切断処理"""
        self.active_connections.discard(websocket)
        self._subscriptions.pop(websocket, None)

    def subscribe(self, websocket: WebSocket, filters: dict):
        """クライアントのサブスクリプションフィルタを更新

        filters:
            {"countries": ["Japan", "China"], "min_score": 60, "dimensions": ["conflict"]}
        """
        self._subscriptions[websocket] = filters

    def _matches_subscription(self, alert: dict, filters: dict) -> bool:
        """アラートがサブスクリプションフィルタに合致するか判定"""
        if filters.get("all", False):
            return True

        # Country filter
        countries = filters.get("countries", [])
        if countries and alert.get("country", "") not in countries:
            if alert.get("location", "") not in countries:
                return False

        # Min score filter
        min_score = filters.get("min_score", 0)
        if alert.get("score", 0) < min_score:
            return False

        # Dimension filter
        dimensions = filters.get("dimensions", [])
        if dimensions and alert.get("dimension", "") not in dimensions:
            if alert.get("alert_type", "") not in dimensions:
                return False

        return True

    async def broadcast(self, alert: dict):
        """全接続クライアントにアラートを配信（フィルタ適用）"""
        alert.setdefault("timestamp", datetime.utcnow().isoformat())
        disconnected = set()

        for connection in list(self.active_connections):
            try:
                filters = self._subscriptions.get(connection, {"all": True})
                if self._matches_subscription(alert, filters):
                    await connection.send_json(alert)
            except Exception:
                disconnected.add(connection)

        # Clean up disconnected clients
        for conn in disconnected:
            self.active_connections.discard(conn)
            self._subscriptions.pop(conn, None)

    async def send_to(self, websocket: WebSocket, message: dict):
        """特定クライアントにメッセージを送信"""
        try:
            await websocket.send_json(message)
        except Exception:
            self.active_connections.discard(websocket)
            self._subscriptions.pop(websocket, None)

    @property
    def connection_count(self) -> int:
        """現在のアクティブ接続数"""
        return len(self.active_connections)


# グローバルインスタンス
broadcaster = AlertBroadcaster()


async def handle_client_message(websocket: WebSocket, raw_data: str):
    """クライアントからのメッセージを処理

    サポートするメッセージ:
        {"action": "subscribe", "countries": ["Japan"], "min_score": 60}
        {"action": "ping"}
        {"action": "status"}
    """
    try:
        data = json.loads(raw_data)
    except json.JSONDecodeError:
        await broadcaster.send_to(websocket, {
            "error": "Invalid JSON",
            "timestamp": datetime.utcnow().isoformat(),
        })
        return

    action = data.get("action", "")

    if action == "subscribe":
        filters = {k: v for k, v in data.items() if k != "action"}
        broadcaster.subscribe(websocket, filters)
        await broadcaster.send_to(websocket, {
            "status": "subscribed",
            "filters": filters,
            "timestamp": datetime.utcnow().isoformat(),
        })

    elif action == "ping":
        await broadcaster.send_to(websocket, {
            "status": "pong",
            "timestamp": datetime.utcnow().isoformat(),
        })

    elif action == "status":
        await broadcaster.send_to(websocket, {
            "status": "connected",
            "active_connections": broadcaster.connection_count,
            "timestamp": datetime.utcnow().isoformat(),
        })

    else:
        await broadcaster.send_to(websocket, {
            "error": f"Unknown action: {action}",
            "supported_actions": ["subscribe", "ping", "status"],
            "timestamp": datetime.utcnow().isoformat(),
        })
