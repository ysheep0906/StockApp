import io
import logging
import re
import xml.etree.ElementTree as ET
import zipfile

import requests

from app import config

logger = logging.getLogger("stockapp.collector.dart")

BASE_URL = "https://opendart.fss.or.kr/api"
TIMEOUT = (5, 60)   # 회사 목록 ZIP은 용량이 커서 응답 대기를 길게
CODE_RE = re.compile(r"^[0-9A-Z]{6}$")


class DartError(Exception):
    """DART API 오류. 메시지에 인증키가 절대 포함되지 않도록 만든다."""


def _require_key() -> str:
    key = config.DART_API_KEY
    if len(key) != 40:
        raise DartError("DART_API_KEY 가 설정되지 않았거나 40자리가 아닙니다")
    return key


def _get(path: str, params: dict) -> requests.Response:
    try:
        res = requests.get(
            f"{BASE_URL}/{path}",
            params={"crtfc_key": _require_key(), **params},
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        # 예외 메시지에는 인증키가 포함된 URL이 들어갈 수 있으므로 예외 종류만 남긴다.
        # 'from None' 은 원래 예외를 traceback에 연결하지 않게 해서, 로그에 URL이 새지 않게 한다.
        raise DartError(f"DART 요청 실패: {type(e).__name__}") from None

    if res.status_code != 200:
        raise DartError(f"DART HTTP 오류: {res.status_code}")
    return res


def fetch_listed_companies() -> list[dict]:
    """상장회사(종목코드가 있는 회사) 목록을 돌려준다."""
    content = _get("corpCode.xml", {}).content

    if not zipfile.is_zipfile(io.BytesIO(content)):
        # 오류일 때는 ZIP 대신 status/message 가 담긴 XML이 온다
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            raise DartError("DART 응답이 ZIP도 XML도 아닙니다") from None
        raise DartError(f"DART 오류 [{root.findtext('status')}] {root.findtext('message')}")

    companies: list[dict] = []
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        with zf.open(zf.namelist()[0]) as f:
            # iterparse: 큰 XML을 한 번에 메모리에 올리지 않고 항목 단위로 읽는다
            for _, elem in ET.iterparse(f):
                if elem.tag != "list":
                    continue
                stock_code = (elem.findtext("stock_code") or "").strip()
                if CODE_RE.match(stock_code):
                    companies.append({
                        "stock_code": stock_code,
                        "corp_code": (elem.findtext("corp_code") or "").strip(),
                        "corp_name": (elem.findtext("corp_name") or "").strip(),
                    })
                elem.clear()   # 처리한 항목은 메모리에서 해제

    return companies