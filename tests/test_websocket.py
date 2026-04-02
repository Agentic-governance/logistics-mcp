"""WebSocket アラート配信テスト

AlertBroadcaster の接続管理、サブスクリプションフィルタ、
メッセージハンドリングを検証する。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime


class TestAlertBroadcasterInit:
    """AlertBroadcaster 初期化テスト"""

    def test_broadcaster_instantiation(self):
        """AlertBroadcaster のインスタンス化"""
        from api.websocket_alerts import AlertBroadcaster
        b = AlertBroadcaster()
        assert b is not None
        assert b.connection_count == 0
        assert len(b.active_connections) == 0

    def test_global_broadcaster_exists(self):
        """グローバル broadcaster インスタンスの存在確認"""
        from api.websocket_alerts import broadcaster
        assert broadcaster is not None


class TestAlertBroadcasterConnect:
    """接続・切断テスト"""

    @pytest.mark.asyncio
    async def test_connect_adds_to_active(self):
        """connect() がアクティブ接続に追加する"""
        from api.websocket_alerts import AlertBroadcaster
        b = AlertBroadcaster()
        ws = AsyncMock()
        await b.connect(ws)
        assert ws in b.active_connections
        assert b.connection_count == 1
        ws.accept.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_removes_from_active(self):
        """disconnect() がアクティブ接続から除去する"""
        from api.websocket_alerts import AlertBroadcaster
        b = AlertBroadcaster()
        ws = AsyncMock()
        await b.connect(ws)
        b.disconnect(ws)
        assert ws not in b.active_connections
        assert b.connection_count == 0

    @pytest.mark.asyncio
    async def test_multiple_connections(self):
        """複数クライアントの接続管理"""
        from api.websocket_alerts import AlertBroadcaster
        b = AlertBroadcaster()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        ws3 = AsyncMock()
        await b.connect(ws1)
        await b.connect(ws2)
        await b.connect(ws3)
        assert b.connection_count == 3
        b.disconnect(ws2)
        assert b.connection_count == 2
        assert ws1 in b.active_connections
        assert ws2 not in b.active_connections
        assert ws3 in b.active_connections


class TestAlertBroadcasterSubscription:
    """サブスクリプションフィルタテスト"""

    def test_default_subscription_all(self):
        """デフォルトサブスクリプションは all=True"""
        from api.websocket_alerts import AlertBroadcaster
        b = AlertBroadcaster()
        # _subscriptions は connect 時に設定される
        ws = MagicMock()
        b._subscriptions[ws] = {"all": True}
        assert b._matches_subscription({"country": "Japan"}, {"all": True})

    def test_country_filter(self):
        """国フィルタの動作テスト"""
        from api.websocket_alerts import AlertBroadcaster
        b = AlertBroadcaster()
        filters = {"countries": ["Japan", "China"]}

        assert b._matches_subscription({"country": "Japan"}, filters) is True
        assert b._matches_subscription({"country": "China"}, filters) is True
        assert b._matches_subscription({"country": "Germany"}, filters) is False

    def test_location_fallback_filter(self):
        """location フィールドでのフォールバックフィルタ"""
        from api.websocket_alerts import AlertBroadcaster
        b = AlertBroadcaster()
        filters = {"countries": ["Tokyo"]}
        assert b._matches_subscription({"location": "Tokyo"}, filters) is True

    def test_min_score_filter(self):
        """最小スコアフィルタテスト"""
        from api.websocket_alerts import AlertBroadcaster
        b = AlertBroadcaster()
        filters = {"min_score": 60}

        assert b._matches_subscription({"score": 70}, filters) is True
        assert b._matches_subscription({"score": 50}, filters) is False
        assert b._matches_subscription({"score": 60}, filters) is True

    def test_dimension_filter(self):
        """ディメンションフィルタテスト"""
        from api.websocket_alerts import AlertBroadcaster
        b = AlertBroadcaster()
        filters = {"dimensions": ["conflict", "sanctions"]}

        assert b._matches_subscription({"dimension": "conflict"}, filters) is True
        assert b._matches_subscription({"dimension": "weather"}, filters) is False
        assert b._matches_subscription({"alert_type": "sanctions"}, filters) is True

    def test_combined_filters(self):
        """複合フィルタテスト"""
        from api.websocket_alerts import AlertBroadcaster
        b = AlertBroadcaster()
        filters = {"countries": ["Japan"], "min_score": 50}

        # 両方合致: True
        assert b._matches_subscription(
            {"country": "Japan", "score": 60}, filters
        ) is True
        # 国合致、スコア不足: False
        assert b._matches_subscription(
            {"country": "Japan", "score": 40}, filters
        ) is False
        # スコア合致、国不合致: False
        assert b._matches_subscription(
            {"country": "China", "score": 70}, filters
        ) is False


class TestAlertBroadcasterBroadcast:
    """ブロードキャストテスト"""

    @pytest.mark.asyncio
    async def test_broadcast_to_all(self):
        """全クライアントへのブロードキャスト"""
        from api.websocket_alerts import AlertBroadcaster
        b = AlertBroadcaster()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await b.connect(ws1)
        await b.connect(ws2)

        alert = {"country": "Japan", "score": 75, "alert_type": "risk_spike"}
        await b.broadcast(alert)

        ws1.send_json.assert_awaited_once()
        ws2.send_json.assert_awaited_once()
        # タイムスタンプが追加される
        sent_data = ws1.send_json.call_args[0][0]
        assert "timestamp" in sent_data

    @pytest.mark.asyncio
    async def test_broadcast_with_filter(self):
        """フィルタ付きブロードキャスト"""
        from api.websocket_alerts import AlertBroadcaster
        b = AlertBroadcaster()
        ws_japan = AsyncMock()
        ws_china = AsyncMock()
        await b.connect(ws_japan)
        await b.connect(ws_china)

        # ws_japan は日本のみ受信
        b.subscribe(ws_japan, {"countries": ["Japan"]})
        # ws_china は全て受信（all=True がデフォルト）

        alert = {"country": "Japan", "score": 80}
        await b.broadcast(alert)

        ws_japan.send_json.assert_awaited_once()
        ws_china.send_json.assert_awaited_once()

        # 中国のアラート: ws_japan は受信しない
        ws_japan.send_json.reset_mock()
        ws_china.send_json.reset_mock()

        alert2 = {"country": "China", "score": 60}
        await b.broadcast(alert2)

        ws_japan.send_json.assert_not_awaited()
        ws_china.send_json.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_broadcast_disconnected_cleanup(self):
        """送信失敗時の自動クリーンアップ"""
        from api.websocket_alerts import AlertBroadcaster
        b = AlertBroadcaster()
        ws_ok = AsyncMock()
        ws_bad = AsyncMock()
        ws_bad.send_json.side_effect = Exception("Connection closed")

        await b.connect(ws_ok)
        await b.connect(ws_bad)
        assert b.connection_count == 2

        await b.broadcast({"test": True})
        # ws_bad は自動削除される
        assert ws_bad not in b.active_connections
        assert b.connection_count == 1


class TestHandleClientMessage:
    """クライアントメッセージハンドリングテスト"""

    @pytest.mark.asyncio
    async def test_handle_ping(self):
        """ping メッセージのハンドリング"""
        from api.websocket_alerts import AlertBroadcaster, handle_client_message

        # 新しい broadcaster インスタンスを使用
        b = AlertBroadcaster()
        ws = AsyncMock()
        await b.connect(ws)

        with patch("api.websocket_alerts.broadcaster", b):
            await handle_client_message(ws, json.dumps({"action": "ping"}))

        # pong レスポンスを確認
        calls = ws.send_json.call_args_list
        # connect 時ではなく handle_client_message からの呼び出しを検証
        found_pong = False
        for call in calls:
            data = call[0][0]
            if isinstance(data, dict) and data.get("status") == "pong":
                found_pong = True
                break
        assert found_pong, f"Expected pong response, got calls: {calls}"

    @pytest.mark.asyncio
    async def test_handle_subscribe(self):
        """subscribe メッセージのハンドリング"""
        from api.websocket_alerts import AlertBroadcaster, handle_client_message

        b = AlertBroadcaster()
        ws = AsyncMock()
        await b.connect(ws)

        with patch("api.websocket_alerts.broadcaster", b):
            msg = json.dumps({
                "action": "subscribe",
                "countries": ["Japan"],
                "min_score": 50,
            })
            await handle_client_message(ws, msg)

        # サブスクリプションが更新される
        assert b._subscriptions[ws].get("countries") == ["Japan"]
        assert b._subscriptions[ws].get("min_score") == 50

    @pytest.mark.asyncio
    async def test_handle_invalid_json(self):
        """不正な JSON のハンドリング"""
        from api.websocket_alerts import AlertBroadcaster, handle_client_message

        b = AlertBroadcaster()
        ws = AsyncMock()
        await b.connect(ws)

        with patch("api.websocket_alerts.broadcaster", b):
            await handle_client_message(ws, "not-valid-json{{{")

        # エラーレスポンスが送信される
        calls = ws.send_json.call_args_list
        found_error = any(
            isinstance(c[0][0], dict) and "error" in c[0][0]
            for c in calls
        )
        assert found_error, "Expected error response for invalid JSON"

    @pytest.mark.asyncio
    async def test_handle_unknown_action(self):
        """未知のアクションのハンドリング"""
        from api.websocket_alerts import AlertBroadcaster, handle_client_message

        b = AlertBroadcaster()
        ws = AsyncMock()
        await b.connect(ws)

        with patch("api.websocket_alerts.broadcaster", b):
            await handle_client_message(ws, json.dumps({"action": "unknown_cmd"}))

        calls = ws.send_json.call_args_list
        found_error = any(
            isinstance(c[0][0], dict) and "error" in c[0][0]
            for c in calls
        )
        assert found_error, "Expected error for unknown action"

    @pytest.mark.asyncio
    async def test_handle_status(self):
        """status メッセージのハンドリング"""
        from api.websocket_alerts import AlertBroadcaster, handle_client_message

        b = AlertBroadcaster()
        ws = AsyncMock()
        await b.connect(ws)

        with patch("api.websocket_alerts.broadcaster", b):
            await handle_client_message(ws, json.dumps({"action": "status"}))

        calls = ws.send_json.call_args_list
        found_status = any(
            isinstance(c[0][0], dict) and c[0][0].get("status") == "connected"
            for c in calls
        )
        assert found_status, "Expected status response with 'connected'"
