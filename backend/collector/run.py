import argparse
import logging
import sys
import time

from app import config
from app.db import db_cursor
from app.timeutil import now_kst
from collector.jobs import job_run
from app.market import is_trading_time
from collector.providers import ProviderError, get_provider

from datetime import date, datetime, time as dtime, timedelta
from collector.providers import MockProvider

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("stockapp.collector")

INSERT_PRICE = """
    INSERT INTO price_minute
        (stock_code, ts, price, change_rate, volume, source, collected_at)
    VALUES (%s, %s, %s, %s, %s, 'poll', %s)
    ON DUPLICATE KEY UPDATE stock_code = stock_code
"""


def collect(force: bool) -> int:
    now = now_kst()
    if not force and not is_trading_time(now):
        logger.info("장 운영 시간이 아니므로 수집을 건너뜀 (now=%s)", now)
        return 0

    ts = now.replace(second=0)   # 수집을 시작한 '분'으로 기록
    provider = get_provider()

    with job_run("collect_price") as job:
        with db_cursor() as cur:
            cur.execute("SELECT DISTINCT stock_code FROM watchlist ORDER BY stock_code")
            codes = [r["stock_code"] for r in cur.fetchall()]

        failed: list[str] = []
        for i, code in enumerate(codes):
            if i > 0:
                time.sleep(config.REQUEST_INTERVAL_SEC)   # 외부 API 호출 한도 준수
            try:
                q = provider.get_quote(code)
            except ProviderError as e:
                logger.warning("QUOTE_FAILED code=%s error=%s", code, e)
                failed.append(code)
                continue   # 한 종목 실패가 전체를 멈추지 않게

            with db_cursor() as cur:
                cur.execute(INSERT_PRICE, (code, ts, q.price, q.change_rate, q.volume, now_kst()))
                job.rows += cur.rowcount   # 새로 들어가면 1, 이미 있으면 0

        if failed:
            job.ok = False
            job.message = f"{len(failed)}/{len(codes)}건 실패: {','.join(failed)}"

        logger.info(
            "COLLECT_DONE provider=%s ts=%s total=%d inserted=%d failed=%d",
            provider.name, ts, len(codes), job.rows, len(failed),
        )

    return 1 if failed else 0

def parse_gap(text: str) -> tuple[dtime, dtime]:
    start, end = text.split("-")
    return dtime.fromisoformat(start), dtime.fromisoformat(end)


def seed_mock(day: date, gap: tuple[dtime, dtime] | None) -> int:
    """개발용: 하루치(09:00~15:30) mock 시세를 관심종목 전체에 채운다.
    gap 을 주면 그 구간은 일부러 비워서 누락 상황을 만든다.
    """
    if config.PRICE_PROVIDER != "mock":
        # 실제 시세 DB에 가짜 데이터가 섞이는 사고 방지
        logger.error("seed-mock 은 PRICE_PROVIDER=mock 일 때만 실행할 수 있습니다")
        return 1

    provider = MockProvider()
    with db_cursor() as cur:
        cur.execute("SELECT DISTINCT stock_code FROM watchlist ORDER BY stock_code")
        codes = [r["stock_code"] for r in cur.fetchall()]

    rows = []
    t = datetime.combine(day, dtime(9, 0))
    end = datetime.combine(day, dtime(15, 30))
    while t <= end:
        in_gap = gap is not None and gap[0] <= t.time() <= gap[1]
        if not in_gap:
            for code in codes:
                q = provider.quote_at(code, t)
                rows.append((code, t, q.price, q.change_rate, q.volume, t + timedelta(seconds=3)))
        t += timedelta(minutes=1)

    with db_cursor() as cur:
        cur.executemany(INSERT_PRICE, rows)
        inserted = cur.rowcount

    logger.info("SEED_MOCK_DONE date=%s stocks=%d rows=%d inserted=%d gap=%s",
                day, len(codes), len(rows), inserted, gap)
    return 0

def kis_check(code: str) -> int:
    """KIS 연동 확인용: 실제 응답의 핵심 필드를 그대로 출력한다 (PRICE_PROVIDER 설정과 무관)"""
    from collector.kis import KisProvider

    data = KisProvider().raw_price(code)
    out = data.get("output") or {}
    print(f"rt_cd={data.get('rt_cd')} msg_cd={data.get('msg_cd')} msg1={data.get('msg1')}")
    for key in ("stck_prpr", "prdy_vrss", "prdy_ctrt", "acml_vol"):
        print(f"  {key} = {out.get(key)}")
    return 0 if data.get("rt_cd") == "0" else 1

def sync_stocks() -> int:
    """DART 회사 목록으로 stocks 테이블을 추가·갱신한다 (삭제는 하지 않음)."""
    from collector.dart import fetch_listed_companies

    with job_run("sync_stocks") as job:
        companies = fetch_listed_companies()

        # 같은 종목코드가 여러 번 나오면 마지막 것을 쓰고, 몇 건인지 기록
        by_code: dict[str, dict] = {}
        duplicated = 0
        for c in companies:
            if c["stock_code"] in by_code:
                duplicated += 1
            by_code[c["stock_code"]] = c

        now = now_kst()
        rows = [(c["stock_code"], c["corp_name"], c["corp_code"], now) for c in by_code.values()]
        with db_cursor() as cur:
            cur.executemany(
                """
                INSERT INTO stocks (code, name, dart_corp_code, updated_at)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    name = VALUES(name),
                    dart_corp_code = VALUES(dart_corp_code),
                    updated_at = VALUES(updated_at)
                """,
                rows,
            )

        job.rows = len(rows)
        job.message = f"상장회사 {len(companies)}건, 종목코드 중복 {duplicated}건"
        logger.info(
            "SYNC_STOCKS_DONE listed=%d upserted=%d duplicated_codes=%d",
            len(companies), len(rows), duplicated,
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m collector.run")
    sub = parser.add_subparsers(dest="command", required=True)

    p_collect = sub.add_parser("collect", help="관심종목 현재가를 1회 수집")
    p_collect.add_argument("--force", action="store_true", help="장 운영 시간이 아니어도 실행 (개발용)")

    p_seed = sub.add_parser("seed-mock", help="(개발용) 하루치 mock 시세 생성")
    p_seed.add_argument("--date", type=date.fromisoformat, required=True, help="예: 2026-10-12")
    p_seed.add_argument("--gap", type=parse_gap, help="비워둘 구간. 예: 10:00-10:14")

    p_kis = sub.add_parser("kis-check", help="KIS 연동 확인 (응답 필드 출력)")
    p_kis.add_argument("code", help="종목코드. 예: 005930")

    sub.add_parser("sync-stocks", help="DART 회사 목록으로 종목 데이터 동기화")

    args = parser.parse_args()
    try:
        if args.command == "collect":
            return collect(args.force)
        if args.command == "seed-mock":
            return seed_mock(args.date, args.gap)
        if args.command == "kis-check":
            return kis_check(args.code)
        if args.command == "sync-stocks":
            return sync_stocks()
    except Exception:
        logger.exception("작업 중 예상하지 못한 오류")
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())