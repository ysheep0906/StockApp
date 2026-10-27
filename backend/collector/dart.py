import io
import logging
import re
import xml.etree.ElementTree as ET
import zipfile
import html
import json

import requests

from datetime import date
from app import config

logger = logging.getLogger("stockapp.collector.dart")

BASE_URL = "https://opendart.fss.or.kr/api"
TIMEOUT = (5, 60)   # 회사 목록 ZIP은 용량이 커서 응답 대기를 길게
CODE_RE = re.compile(r"^[0-9A-Z]{6}$")


class DartError(Exception):
    """DART API 오류. 메시지에 인증키가 절대 포함되지 않도록 만든다."""


def require_key() -> str:
    key = config.DART_API_KEY
    if len(key) != 40:
        raise DartError("DART_API_KEY 가 설정되지 않았거나 40자리가 아닙니다")
    return key


def _get(path: str, params: dict) -> requests.Response:
    try:
        res = requests.get(
            f"{BASE_URL}/{path}",
            params={"crtfc_key": require_key(), **params},
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        # 예외 메시지에는 인증키가 포함된 URL이 들어갈 수 있으므로 예외 종류만 남긴다.
        # 'from None' 은 원래 예외를 traceback에 연결하지 않게 해서, 로그에 URL이 새지 않게 한다.
        raise DartError(f"DART 요청 실패: {type(e).__name__}") from None

    if res.status_code != 200:
        raise DartError(f"DART HTTP 오류: {res.status_code}")
    return res

MAX_UNZIPPED_BYTES = 30 * 1024 * 1024   # 압축 해제 후 30MB 초과 파일은 처리하지 않음


def _open_zip(content: bytes) -> zipfile.ZipFile:
    """정상이면 ZIP을 열어서 돌려주고, 오류 응답이면 DART 오류 코드로 예외를 낸다."""
    if zipfile.is_zipfile(io.BytesIO(content)):
        return zipfile.ZipFile(io.BytesIO(content))

    # 오류일 때는 ZIP 대신 status/message 가 담긴 XML(또는 JSON)이 온다
    status, message = None, None
    try:
        root = ET.fromstring(content)
        status, message = root.findtext("status"), root.findtext("message")
    except ET.ParseError:
        try:
            data = json.loads(content)
            status, message = data.get("status"), data.get("message")
        except ValueError:
            pass
    if status is None:
        raise DartError("DART 응답이 ZIP이 아니고 오류 형식도 해석할 수 없습니다")
    raise DartError(f"DART 오류 [{status}] {message}")


def fetch_listed_companies() -> list[dict]:
    """상장회사(종목코드가 있는 회사) 목록을 돌려준다."""
    content = _get("corpCode.xml", {}).content

    companies: list[dict] = []
    with _open_zip(content) as zf:
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

def fetch_disclosures(corp_code: str, bgn: date, end: date, max_pages: int = 5) -> list[dict]:
    """한 회사의 기간 내 공시 목록. 결과가 없으면 빈 리스트(오류 아님)."""
    items: list[dict] = []
    page = 1
    while True:
        res = _get("list.json", {
            "corp_code": corp_code,
            "bgn_de": bgn.strftime("%Y%m%d"),
            "end_de": end.strftime("%Y%m%d"),
            "last_reprt_at": "Y",      # 정정공시가 있으면 최종본만
            "page_no": page,
            "page_count": 100,         # 페이지당 최대 건수
        })
        try:
            data = res.json()
        except ValueError:
            raise DartError("DART 응답이 JSON이 아닙니다") from None

        status = data.get("status")
        if status == "013":
            return items               # 조회된 데이터 없음: 정상적인 0건
        if status != "000":
            raise DartError(f"DART 오류 [{status}] {data.get('message')}")

        items.extend(data.get("list", []))

        total_page = int(data.get("total_page") or 1)
        if page >= total_page:
            return items
        if page >= max_pages:
            # 비정상적으로 많은 결과가 끝없이 이어지는 것을 방지
            logger.warning("DART_PAGE_LIMIT corp_code=%s total_page=%d", corp_code, total_page)
            return items
        page += 1

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def _decode(raw: bytes) -> str:
    # 대부분 UTF-8이지만, 아닐 경우를 대비해 한국어 윈도우 인코딩(cp949)도 시도
    for encoding in ("utf-8", "cp949"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def fetch_document_text(rcept_no: str, max_chars: int) -> str:
    """공시 원문 ZIP에서 본문 텍스트를 뽑아 앞부분 max_chars 글자만 돌려준다."""
    content = _get("document.xml", {"rcept_no": rcept_no}).content

    with _open_zip(content) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
        if not names:
            raise DartError("원문 ZIP 안에 XML 파일이 없습니다")
        # 본문은 보통 '<접수번호>.xml', 나머지는 첨부 문서
        name = f"{rcept_no}.xml" if f"{rcept_no}.xml" in names else names[0]
        if zf.getinfo(name).file_size > MAX_UNZIPPED_BYTES:
            raise DartError(f"원문이 너무 큽니다 ({zf.getinfo(name).file_size} bytes)")
        raw = zf.read(name)

    # XML 파서 대신 태그 제거: 형식이 깨진 문서에도 동작하게
    text = html.unescape(TAG_RE.sub(" ", _decode(raw)))
    return SPACE_RE.sub(" ", text).strip()[:max_chars]