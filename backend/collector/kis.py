import json
import logging
import os
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests

from app import config
from app.timeutil import now_kst
from collector.providers import ProviderError, Quote

logger = logging.getLogger("stockapp.collector.kis")

TIMEOUT = (3, 5)                       # (연결 대기, 응답 대기) 초
TOKEN_MARGIN = timedelta(minutes=10)   # 만료 10분 전이면 새로 발급
TR_INQUIRE_PRICE = "FHKST01010100"     # 국내주식 현재가 조회
TOKEN_EXPIRED = "EGW00123"             # 기간이 만료된 토큰


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

    # ---------- 시세 ----------

    def _request_price(self, code: str) -> dict:
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self._get_token()}",
            "appkey": config.KIS_APP_KEY,
            "appsecret": config.KIS_APP_SECRET,
            "tr_id": TR_INQUIRE_PRICE,
            "custtype": "P",
        }
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code}
        try:
            res = self.session.get(
                f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price",
                headers=headers,
                params=params,
                timeout=TIMEOUT,
            )
            # KIS는 오류도 JSON 본문으로 알려주므로 상태 코드와 관계없이 본문을 읽는다
            return res.json()
        except (requests.RequestException, ValueError) as e:
            raise ProviderError(f"시세 요청 실패: {e}") from e

    def get_quote(self, code: str) -> Quote:
        data = self._request_price(code)

        if data.get("msg_cd") == TOKEN_EXPIRED:
            # 만료된 토큰이면 새로 받아서 딱 1번만 재시도 (무한 재시도 방지)
            logger.warning("KIS_TOKEN_EXPIRED 토큰 재발급 후 재시도")
            self._invalidate_token()
            data = self._request_price(code)

        if data.get("rt_cd") != "0":
            raise ProviderError(f"KIS 오류 [{data.get('msg_cd')}] {data.get('msg1')}")

        out = data.get("output") or {}
        try:
            return Quote(
                code=code,
                price=int(out["stck_prpr"]),              # 현재가
                change_rate=Decimal(out["prdy_ctrt"]),    # 전일 대비율(%)
                volume=int(out["acml_vol"]),              # 누적 거래량
            )
        except (KeyError, ValueError, InvalidOperation) as e:
            raise ProviderError(f"응답 형식 오류: {e!r}") from e

    def raw_price(self, code: str) -> dict:
        """확인용: 가공하지 않은 응답을 그대로 돌려준다"""
        return self._request_price(code)