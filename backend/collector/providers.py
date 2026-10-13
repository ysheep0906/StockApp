import math
import random
import zlib
from datetime import datetime
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from app import config
from app.timeutil import now_kst


class ProviderError(Exception):
    """시세 조회 실패 (외부 API 오류, 호출 한도 초과 등)"""


@dataclass(frozen=True)
class Quote:
    code: str
    price: int
    change_rate: Decimal   # 전일 대비 등락률(%)
    volume: int            # 누적 거래량


class PriceProvider(Protocol):
    name: str

    def get_quote(self, code: str) -> Quote: ...


class MockProvider:
    """장이 닫힌 시간에도 개발·테스트할 수 있도록 가짜 시세를 만든다.
    같은 종목·같은 분에는 항상 같은 값을 돌려준다 (재실행 결과를 비교할 수 있게).
    """

    name = "mock"

    def get_quote(self, code: str) -> Quote:
        if config.MOCK_FAIL_RATE > 0 and random.random() < config.MOCK_FAIL_RATE:
            raise ProviderError("mock: 의도적으로 발생시킨 조회 실패")
        return self.quote_at(code, now_kst())

    def quote_at(self, code: str, at: datetime) -> Quote:
        rnd = random.Random(f"{code}-{at:%Y%m%d%H%M}")
        base = 10_000 + zlib.crc32(code.encode()) % 190_000
        phase = zlib.crc32(code.encode()) % 360
        minute_of_day = at.hour * 60 + at.minute

        # 차트가 그럴듯하게 보이도록 완만한 곡선 + 약간의 잡음
        change_rate = round(3 * math.sin((minute_of_day + phase) / 40) + rnd.uniform(-0.3, 0.3), 2)
        price = round(base * (1 + change_rate / 100))
        volume = rnd.randint(10_000, 5_000_000)
        return Quote(code, price, Decimal(str(change_rate)), volume)


def get_provider() -> PriceProvider:
    if config.PRICE_PROVIDER == "mock":
        return MockProvider()
    if config.PRICE_PROVIDER == "kis":
        # mock 모드에서는 requests 없이도 동작하도록, 필요할 때만 불러온다
        from collector.kis import KisProvider
        return KisProvider()
    raise ValueError(f"알 수 없는 PRICE_PROVIDER: {config.PRICE_PROVIDER}")