"""
観光需要予測モデル群
=====================
SCRI v1.4.0

- LSTMStructural: LSTM構造成分（長期トレンド）
- TourismTransformer: Transformerサイクル成分（季節・短期変動）
- DualScaleModel: 上記2モデルの統合予測
"""

try:
    from .lstm_structural import LSTMStructural
except (ImportError, ModuleNotFoundError):
    LSTMStructural = None

try:
    from .transformer_cycle import TourismTransformer
except (ImportError, ModuleNotFoundError):
    TourismTransformer = None

try:
    from .dual_scale_model import DualScaleModel
except (ImportError, ModuleNotFoundError):
    DualScaleModel = None

__all__ = [
    "LSTMStructural",
    "TourismTransformer",
    "DualScaleModel",
]
