# features/tourism/calendar_events.py
# カレンダーイベント駆動の需要・不確実性倍率 (SCRI v1.5.0)
# 祝日・季節イベントが訪日旅行需要に与える影響をモデル化

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CalendarEvent:
    """カレンダーイベント定義"""
    name: str                          # イベント名
    countries: List[str]               # 影響を受ける市場 (ISO2)
    months: List[int]                  # 該当月 (1-12)
    demand_multiplier: float = 1.0     # 需要倍率 (>1=増, <1=減)
    uncertainty_multiplier: float = 1.0  # 不確実性倍率 (>1=不確実性増)
    description: str = ""              # 説明


# 全15+1イベント定義
CALENDAR_EVENTS: List[CalendarEvent] = [
    # --- 東アジア: 中国 ---
    CalendarEvent(
        name="春節",
        countries=["CN", "TW", "HK", "SG", "MY"],
        months=[1, 2],
        demand_multiplier=0.7,       # 国内消費優先・帰省で訪日減
        uncertainty_multiplier=1.3,  # 日程変動(旧暦)
        description="旧正月: 帰省シーズンで訪日需要減、日程は旧暦で毎年変動",
    ),
    CalendarEvent(
        name="国慶節",
        countries=["CN"],
        months=[10],
        demand_multiplier=1.6,       # ゴールデンウィーク級の訪日ピーク
        uncertainty_multiplier=1.1,
        description="中国建国記念日: 大型連休で訪日需要急増",
    ),
    CalendarEvent(
        name="労働節",
        countries=["CN"],
        months=[5],
        demand_multiplier=1.3,
        uncertainty_multiplier=1.05,
        description="メーデー連休: 中規模の訪日ピーク",
    ),
    # --- 東アジア: 韓国 ---
    CalendarEvent(
        name="秋夕",
        countries=["KR"],
        months=[9],
        demand_multiplier=0.75,      # 帰省優先
        uncertainty_multiplier=1.2,  # 旧暦変動
        description="韓国版お盆: 帰省シーズンで訪日減",
    ),
    CalendarEvent(
        name="ソルラル",
        countries=["KR"],
        months=[1, 2],
        demand_multiplier=0.8,
        uncertainty_multiplier=1.2,
        description="韓国旧正月: 帰省シーズン",
    ),
    CalendarEvent(
        name="韓国夏休み",
        countries=["KR"],
        months=[7, 8],
        demand_multiplier=1.35,
        uncertainty_multiplier=1.05,
        description="韓国の夏季休暇: 訪日需要増",
    ),
    # --- 東アジア: 台湾 ---
    CalendarEvent(
        name="台湾春節",
        countries=["TW"],
        months=[1, 2],
        demand_multiplier=0.65,      # 春節と重複するが台湾独自の強い帰省
        uncertainty_multiplier=1.25,
        description="台湾の旧正月休暇",
    ),
    CalendarEvent(
        name="台湾国慶日",
        countries=["TW"],
        months=[10],
        demand_multiplier=1.25,
        uncertainty_multiplier=1.05,
        description="双十節: 台湾の建国記念日連休",
    ),
    # --- 北米・欧州 ---
    CalendarEvent(
        name="Thanksgiving",
        countries=["US", "CA"],
        months=[11],
        demand_multiplier=0.85,      # 国内消費優先
        uncertainty_multiplier=1.1,
        description="感謝祭: 国内旅行優先で訪日やや減",
    ),
    CalendarEvent(
        name="米国夏休み",
        countries=["US", "CA", "GB"],
        months=[6, 7, 8],
        demand_multiplier=1.4,
        uncertainty_multiplier=1.05,
        description="欧米の夏季休暇: 訪日需要の年間ピーク",
    ),
    CalendarEvent(
        name="クリスマス",
        countries=["US", "CA", "GB", "AU", "DE", "FR"],
        months=[12],
        demand_multiplier=0.9,       # 帰省・国内消費
        uncertainty_multiplier=1.15,
        description="クリスマスシーズン: 訪日やや減だが不確実性増",
    ),
    # --- オセアニア ---
    CalendarEvent(
        name="豪州スキー",
        countries=["AU", "NZ"],
        months=[1, 2, 3],
        demand_multiplier=1.5,       # 南半球夏→日本冬スキー需要
        uncertainty_multiplier=1.1,
        description="豪州・NZからのスキーシーズン訪日",
    ),
    CalendarEvent(
        name="豪州夏休み",
        countries=["AU", "NZ"],
        months=[12, 1],
        demand_multiplier=1.3,
        uncertainty_multiplier=1.05,
        description="南半球の夏季休暇(12-1月)",
    ),
    # --- 自然・季節イベント(全市場/地域) ---
    CalendarEvent(
        name="桜",
        countries=["KR", "CN", "TW", "HK", "US", "CA", "GB", "AU", "DE", "FR",
                   "SG", "MY", "TH", "NZ"],
        months=[3, 4],
        demand_multiplier=1.45,
        uncertainty_multiplier=1.2,  # 開花時期の不確実性
        description="桜シーズン: 全市場から訪日需要急増、開花時期変動あり",
    ),
    CalendarEvent(
        name="紅葉",
        countries=["KR", "CN", "TW", "HK", "US"],
        months=[10, 11],
        demand_multiplier=1.3,
        uncertainty_multiplier=1.15,
        description="紅葉シーズン: 東アジア+米国からの秋の訪日需要増",
    ),
    CalendarEvent(
        name="台風",
        countries=["KR", "CN", "TW", "HK", "SG", "MY", "TH"],
        months=[8, 9, 10],
        demand_multiplier=0.85,
        uncertainty_multiplier=1.5,  # 台風による高い不確実性
        description="台風シーズン: 東アジア・東南アジアの渡航リスク増大",
    ),
]


def get_events_for_country_month(country: str, month: int) -> List[CalendarEvent]:
    """指定国・月に該当するイベント一覧を返す"""
    return [
        ev for ev in CALENDAR_EVENTS
        if country in ev.countries and month in ev.months
    ]


def get_demand_multiplier(country: str, month: int) -> float:
    """指定国・月の需要倍率(複数イベントの積)"""
    events = get_events_for_country_month(country, month)
    if not events:
        return 1.0
    result = 1.0
    for ev in events:
        result *= ev.demand_multiplier
    return result


def get_uncertainty_multiplier(country: str, month: int) -> float:
    """指定国・月の不確実性倍率(複数イベントの最大値)"""
    events = get_events_for_country_month(country, month)
    if not events:
        return 1.0
    return max(ev.uncertainty_multiplier for ev in events)
