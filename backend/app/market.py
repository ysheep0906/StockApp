from datetime import datetime, time

MARKET_OPEN = time(9, 0)
MARKET_CLOSE = time(15, 30)


def is_trading_time(now: datetime) -> bool:
    """정규장 시간 여부 (평일 09:00~15:30).
    공휴일 등 휴장일과 개장 시간이 바뀌는 날은 아직 반영하지 않음 → D6에서 추가.
    """
    return now.weekday() < 5 and MARKET_OPEN <= now.time() <= MARKET_CLOSE