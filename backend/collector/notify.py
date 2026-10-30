import logging

import requests

logger = logging.getLogger("stockapp.notify")

TIMEOUT = (3, 5)
MAX_CONTENT_LEN = 2000   # Discord 메시지 길이 상한


class NotifyError(Exception):
    """알림 전송 실패. 메시지에 웹훅 URL(토큰 포함)이 절대 들어가지 않게 만든다."""


def send_discord(webhook_url: str, content: str) -> None:
    if not webhook_url:
        raise NotifyError("Discord 웹훅 URL이 설정되지 않았습니다")
    try:
        res = requests.post(
            webhook_url,
            json={
                "content": content[:MAX_CONTENT_LEN],
                "allowed_mentions": {"parse": []},   # @everyone 등 호출 기능 끄기
            },
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        # 예외 메시지에 토큰이 포함된 URL이 들어갈 수 있으므로 종류만 남긴다
        raise NotifyError(f"Discord 전송 실패: {type(e).__name__}") from None

    if res.status_code == 429:
        raise NotifyError("Discord 전송 제한(429)")
    if not 200 <= res.status_code < 300:
        raise NotifyError(f"Discord 응답 오류: HTTP {res.status_code}")