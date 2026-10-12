from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def now_kst() -> datetime:
    """DB 저장용 KST 현재 시각. 시간대 정보와 마이크로초를 제거"""
    return datetime.now(KST).replace(tzinfo=None, microsecond=0)