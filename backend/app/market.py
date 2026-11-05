import logging
from datetime import date, datetime, time
from functools import lru_cache

from app import config

logger = logging.getLogger("stockapp.market")

MARKET_OPEN = time(9, 0)
MARKET_CLOSE = time(15, 30)


@lru_cache(maxsize=1)
def _holidays() -> frozenset[date]:
    """휴장일 파일을 읽는다. 오래 실행되는 API 서버는 파일을 바꾸면 재시작해야 반영된다."""
    days: set[date] = set()
    try:
        with open(config.MARKET_HOLIDAYS_FILE, encoding="utf-8") as f:
            for line in f:
                text = line.split("#", 1)[0].strip()
                if text:
                    days.add(date.fromisoformat(text))
    except FileNotFoundError:
        logger.warning("휴장일 파일이 없어 주말만 휴장으로 처리함: %s", config.MARKET_HOLIDAYS_FILE)
    return frozenset(days)


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in _holidays()


def is_trading_time(now: datetime) -> bool:
    """정규장 시간 여부 (거래일 09:00~15:30).
    알려진 한계: 수능일처럼 개장·마감 시간이 바뀌는 날은 반영하지 않음 → runbook 참고
    """
    return is_trading_day(now.date()) and MARKET_OPEN <= now.time() <= MARKET_CLOSE