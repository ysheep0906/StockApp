import json
import logging
import os
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests

from app import config
from app.timeutil import now_kst
from collector.providers import Bar, ProviderError, Quote



logger = logging.getLogger("stockapp.collector.kis")

TIMEOUT = (3, 5)
TOKEN_MARGIN = timedelta(minutes=10)
TOKEN_EXPIRED = "EGW00123"

PATH_PRICE = "/uapi/domestic-stock/v1/quotations/inquire-price"
TR_INQUIRE_PRICE = "FHKST01010100"        # 국내주식 현재가
PATH_MINUTE = "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
TR_MINUTE_CHART = "FHKST03010200"         # 국내주식 당일 분봉 (1회 최대 30건, 당일만)
MARKET_DIV = "J"                          # KRX 기준 (현재가와 분봉 모두 같은 시장 기준)


class KisProvider:
    name = "kis"

    def __init__(self):
        if not config.KIS_APP_KEY or not config.KIS_APP_SECRET:
            raise ValueError("PRICE_PROVIDER=kis 이면 KIS_APP_KEY, KIS_APP_SECRET 설정이 필요합니다")
        self.base_url = config.KIS_BASE_URL.rstrip("/")
        self.token_file = Path(config.KIS_TOKEN_FILE)
        self.session = requests.Session()
        self._token: str | None = None

    # ---------- 토큰 ----------

    def _load_cached_token(self) -> str | None:
        try:
            data = json.loads(self.token_file.read_text(encoding="utf-8"))
            expires_at = datetime.fromisoformat(data["expires_at"])
        except (FileNotFoundError, KeyError, ValueError):
            return None
        if expires_at - TOKEN_MARGIN <= now_kst():
            return None
        return data["access_token"]

    def _save_token(self, token: str, expires_at: datetime) -> None:
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.token_file.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"access_token": token, "expires_at": expires_at.isoformat()}),
            encoding="utf-8",
        )
        if os.name == "posix":
            os.chmod(tmp, 0o600)          # 리눅스: 소유자만 읽기/쓰기
        os.replace(tmp, self.token_file)  # 원자적 교체: 반쯤 쓰인 파일이 남지 않음

    def _issue_token(self) -> str:
        try:
            res = self.session.post(
                f"{self.base_url}/oauth2/tokenP",
                json={
                    "grant_type": "client_credentials",
                    "appkey": config.KIS_APP_KEY,
                    "appsecret": config.KIS_APP_SECRET,
                },
                timeout=TIMEOUT,
            )
            data = res.json()
        except (requests.RequestException, ValueError) as e:
            raise ProviderError(f"토큰 발급 요청 실패: {e}") from e

        if res.status_code != 200 or "access_token" not in data:
            code = data.get("error_code") or data.get("msg_cd")
            desc = data.get("error_description") or data.get("msg1")
            raise ProviderError(f"토큰 발급 거부: HTTP {res.status_code} [{code}] {desc}")

        token = data["access_token"]
        expires_at = datetime.strptime(data["access_token_token_expired"], "%Y-%m-%d %H:%M:%S")
        self._save_token(token, expires_at)
        logger.info("KIS_TOKEN_ISSUED expires_at=%s", expires_at)   # 토큰 값은 남기지 않음
        return token

    def _get_token(self) -> str:
        if self._token is None:
            self._token = self._load_cached_token() or self._issue_token()
        return self._token

    def _invalidate_token(self) -> None:
        self._token = None
        self.token_file.unlink(missing_ok=True)

        # ---------- 공통 요청 ----------

    def _call(self, path: str, tr_id: str, params: dict) -> dict:
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self._get_token()}",
            "appkey": config.KIS_APP_KEY,
            "appsecret": config.KIS_APP_SECRET,
            "tr_id": tr_id,
            "custtype": "P",
        }
        try:
            res = self.session.get(
                f"{self.base_url}{path}", headers=headers, params=params, timeout=TIMEOUT
            )
            # KIS는 오류도 JSON 본문으로 알려주므로 상태 코드와 관계없이 본문을 읽는다
            return res.json()
        except (requests.RequestException, ValueError) as e:
            raise ProviderError(f"KIS 요청 실패: {e}") from e

    def _request(self, path: str, tr_id: str, params: dict) -> dict:
        data = self._call(path, tr_id, params)
        if data.get("msg_cd") == TOKEN_EXPIRED:
            # 만료된 토큰이면 새로 받아서 딱 1번만 재시도
            logger.warning("KIS_TOKEN_EXPIRED 토큰 재발급 후 재시도")
            self._invalidate_token()
            data = self._call(path, tr_id, params)
        if data.get("rt_cd") != "0":
            raise ProviderError(f"KIS 오류 [{data.get('msg_cd')}] {data.get('msg1')}")
        return data

    # ---------- 현재가 ----------

    def _price_params(self, code: str) -> dict:
        return {"FID_COND_MRKT_DIV_CODE": MARKET_DIV, "FID_INPUT_ISCD": code}

    def get_quote(self, code: str) -> Quote:
        data = self._request(PATH_PRICE, TR_INQUIRE_PRICE, self._price_params(code))
        out = data.get("output") or {}
        try:
            return Quote(
                code=code,
                price=int(out["stck_prpr"]),
                change_rate=Decimal(out["prdy_ctrt"]),
                volume=int(out["acml_vol"]),
            )
        except (KeyError, ValueError, InvalidOperation) as e:
            raise ProviderError(f"응답 형식 오류: {e!r}") from e

    def raw_price(self, code: str) -> dict:
        """확인용: 가공하지 않은 현재가 응답"""
        return self._call(PATH_PRICE, TR_INQUIRE_PRICE, self._price_params(code))

    # ---------- 당일 분봉 ----------

    def _minute_params(self, code: str, end: time) -> dict:
        return {
            "FID_ETC_CLS_CODE": "",
            "FID_COND_MRKT_DIV_CODE": MARKET_DIV,
            "FID_INPUT_ISCD": code,
            "FID_INPUT_HOUR_1": end.strftime("%H%M%S"),   # 이 시각부터 과거 방향으로 조회
            "FID_PW_DATA_INCU_YN": "Y",
        }

    def get_minute_bars(self, code: str, day: date, end: time) -> list[Bar]:
        if day != now_kst().date():
            raise ProviderError("KIS 당일 분봉 API는 당일 데이터만 제공합니다")

        data = self._request(PATH_MINUTE, TR_MINUTE_CHART, self._minute_params(code, end))
        bars: list[Bar] = []
        for row in data.get("output2") or []:
            try:
                ts = datetime.strptime(row["stck_bsop_date"] + row["stck_cntg_hour"], "%Y%m%d%H%M%S")
                price = int(row["stck_prpr"])   # 분봉의 종가 자리
            except (KeyError, ValueError):
                continue                        # 형식이 이상한 행은 버림
            if ts.date() == day:                # 다른 날짜의 봉이 섞이지 않게
                bars.append(Bar(ts.replace(second=0), price))
        return bars

    def raw_minute_bars(self, code: str, end: time) -> dict:
        """확인용: 가공하지 않은 분봉 응답"""
        return self._call(PATH_MINUTE, TR_MINUTE_CHART, self._minute_params(code, end))