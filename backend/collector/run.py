import argparse
import logging
import sys
import time

from app import config
from app.db import db_cursor
from app.timeutil import now_kst
from collector.jobs import job_run
from app.market import MARKET_CLOSE, MARKET_OPEN, is_trading_time

from datetime import date, datetime, time as dtime, timedelta
from collector.providers import Bar, MockProvider, ProviderError, Quote, get_provider

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

INSERT_ALERT = """
    INSERT INTO alert_log
        (user_id, stock_code, alert_type, trade_date, price, change_rate, sent_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE id = id
"""


def run_alerts(ts: datetime, quotes: dict[str, Quote], provider_name: str) -> int:
    """방금 수집한 시세로 알림 조건을 검사하고 Discord로 보낸다."""
    if not quotes:
        return 0
    from collector.notify import NotifyError, send_discord

    prefix = "[MOCK] " if provider_name == "mock" else ""   # 가짜 시세 알림은 구분 표시

    with job_run("price_alert") as job:
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT w.user_id, w.stock_code, s.name, w.alert_up_pct, w.alert_down_pct
                FROM watchlist w
                JOIN stocks s ON s.code = w.stock_code
                WHERE w.alert_up_pct IS NOT NULL OR w.alert_down_pct IS NOT NULL
                """
            )
            rows = cur.fetchall()

        sent = failed = skipped = 0
        for row in rows:
            q = quotes.get(row["stock_code"])
            if q is None:
                continue

            if row["alert_up_pct"] is not None and q.change_rate >= row["alert_up_pct"]:
                kind, label, arrow, threshold = "up", "상승", "▲", row["alert_up_pct"]
            elif row["alert_down_pct"] is not None and q.change_rate <= -row["alert_down_pct"]:
                kind, label, arrow, threshold = "down", "하락", "▼", row["alert_down_pct"]
            else:
                continue

            # 1) 먼저 기록(선점): 오늘 이미 보낸 알림이면 여기서 걸러진다
            with db_cursor() as cur:
                cur.execute(
                    INSERT_ALERT,
                    (row["user_id"], row["stock_code"], kind, ts.date(),
                     q.price, q.change_rate, now_kst()),
                )
                if cur.rowcount != 1:
                    skipped += 1
                    continue
                alert_id = cur.lastrowid

            # 2) 전송
            message = (
                f"{prefix}{arrow} [{label} 알림] {row['name']}({row['stock_code']}) "
                f"{q.change_rate:+.2f}% · 현재가 {q.price:,}원 "
                f"(기준 {label} {threshold}% · {ts:%H:%M})"
            )
            try:
                send_discord(config.DISCORD_ALERT_WEBHOOK_URL, message)
            except NotifyError as e:
                # 3) 실패하면 선점 기록을 지워서 다음 수집 때 다시 시도하게 한다
                failed += 1
                logger.warning("ALERT_FAILED code=%s kind=%s error=%s", row["stock_code"], kind, e)
                with db_cursor() as cur:
                    cur.execute("DELETE FROM alert_log WHERE id = %s", (alert_id,))
                continue

            sent += 1
            logger.info("ALERT_SENT code=%s kind=%s rate=%s", row["stock_code"], kind, q.change_rate)

        job.rows = sent
        job.ok = failed == 0
        job.message = f"전송 {sent}, 실패 {failed}, 오늘 이미 보냄 {skipped}"

    return 1 if failed else 0


def collect(force: bool) -> int:
    now = now_kst()
    if not force and not is_trading_time(now):
        logger.info("장 운영 시간이 아니므로 수집을 건너뜀 (now=%s)", now)
        return 0

    ts = now.replace(second=0)   # 수집을 시작한 '분'으로 기록
    provider = get_provider()
    quotes: dict[str, Quote] = {}
    failed: list[str] = []

    with job_run("collect_price") as job:
        with db_cursor() as cur:
            cur.execute("SELECT DISTINCT stock_code FROM watchlist ORDER BY stock_code")
            codes = [r["stock_code"] for r in cur.fetchall()]

        for i, code in enumerate(codes):
            if i > 0:
                time.sleep(config.REQUEST_INTERVAL_SEC)   # 외부 API 호출 한도 준수
            try:
                q = provider.get_quote(code)
            except ProviderError as e:
                logger.warning("QUOTE_FAILED code=%s error=%s", code, e)
                failed.append(code)
                continue   # 한 종목 실패가 전체를 멈추지 않게

            quotes[code] = q
            with db_cursor() as cur:
                cur.execute(INSERT_PRICE, (code, ts, q.price, q.change_rate, q.volume, now_kst()))
                job.rows += cur.rowcount

        if failed:
            job.ok = False
            job.message = f"{len(failed)}/{len(codes)}건 실패: {','.join(failed)}"

        logger.info(
            "COLLECT_DONE provider=%s ts=%s total=%d inserted=%d failed=%d",
            provider.name, ts, len(codes), job.rows, len(failed),
        )

    # 수집과 알림은 실행 기록을 따로 남긴다 (시세는 저장됐는데 알림만 실패한 경우를 구분)
    alert_rc = run_alerts(ts, quotes, provider.name)
    return 1 if failed or alert_rc else 0

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

INSERT_DISCLOSURE = """
    INSERT INTO disclosures
        (rcept_no, stock_code, corp_name, report_nm, rcept_dt, collected_at)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE rcept_no = rcept_no
"""

DART_INTERVAL_SEC = 0.3   # 연속 호출 사이 대기 (공용 API에 대한 예의)


def collect_disclosures(days: int) -> int:
    """관심종목의 최근 N일 공시를 수집한다. 기간을 겹쳐 조회하고 접수번호로 중복을 막는다."""
    from collector.dart import DartError, fetch_disclosures, require_key

    require_key()   # 키 문제면 종목별로 실패하기 전에 바로 중단
    today = now_kst().date()
    bgn = today - timedelta(days=days)

    with job_run("collect_disclosures") as job:
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT s.code, s.dart_corp_code
                FROM watchlist w
                JOIN stocks s ON s.code = w.stock_code
                ORDER BY s.code
                """
            )
            targets = cur.fetchall()

        failed: list[str] = []
        no_corp_code: list[str] = []
        for i, t in enumerate(targets):
            if not t["dart_corp_code"]:
                no_corp_code.append(t["code"])   # DART 고유번호가 없는 종목
                continue
            if i > 0:
                time.sleep(DART_INTERVAL_SEC)

            try:
                items = fetch_disclosures(t["dart_corp_code"], bgn, today)
            except DartError as e:
                logger.warning("DART_FAILED code=%s error=%s", t["code"], e)
                failed.append(t["code"])
                continue

            now = now_kst()
            rows = [
                (
                    it["rcept_no"],
                    t["code"],
                    it["corp_name"],
                    it["report_nm"].strip(),
                    datetime.strptime(it["rcept_dt"], "%Y%m%d").date(),
                    now,
                )
                for it in items
                if len(it.get("rcept_no", "")) == 14   # 접수번호 형식이 아니면 버림
            ]
            if rows:
                with db_cursor() as cur:
                    cur.executemany(INSERT_DISCLOSURE, rows)
                    job.rows += cur.rowcount     # 새로 저장된 건수만 더해짐

            logger.info("DART_FETCHED code=%s found=%d", t["code"], len(items))

        job.ok = not failed
        job.message = (
            f"대상 {len(targets)}종목, 실패 {len(failed)} {failed}, "
            f"고유번호 없음 {len(no_corp_code)} {no_corp_code}"
        )
        logger.info(
            "COLLECT_DISCLOSURES_DONE targets=%d inserted=%d failed=%d no_corp_code=%d",
            len(targets), job.rows, len(failed), len(no_corp_code),
        )

    return 1 if failed else 0

SUMMARY_MAX_ATTEMPTS = 3


def summarize_disclosures(limit: int) -> int:
    """요약 대기(pending) 공시를 최신순으로 limit 건 요약한다."""
    from collector.dart import DartError, fetch_document_text
    from collector.summarizer import SummaryError, get_summarizer

    summarizer = get_summarizer()

    with job_run("summarize_disclosures") as job:
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT rcept_no, report_nm, summary_attempts
                FROM disclosures
                WHERE summary_status = 'pending'
                ORDER BY rcept_dt DESC, rcept_no DESC
                LIMIT %s
                """,
                (limit,),
            )
            targets = cur.fetchall()

        failed = 0
        for i, d in enumerate(targets):
            if i > 0:
                time.sleep(DART_INTERVAL_SEC)
            try:
                text = fetch_document_text(d["rcept_no"], config.SUMMARY_SOURCE_MAX_CHARS)
                summary = summarizer.summarize(d["report_nm"], text)
            except (DartError, SummaryError) as e:
                failed += 1
                attempts = d["summary_attempts"] + 1
                # 상한에 도달하면 failed 로 멈춰서, 같은 공시에 비용이 계속 나가는 것을 막는다
                status = "failed" if attempts >= SUMMARY_MAX_ATTEMPTS else "pending"
                logger.warning(
                    "SUMMARY_FAILED rcept_no=%s attempts=%d status=%s error=%s",
                    d["rcept_no"], attempts, status, e,
                )
                with db_cursor() as cur:
                    cur.execute(
                        """
                        UPDATE disclosures
                        SET summary_attempts = %s, summary_status = %s, summary_error = %s
                        WHERE rcept_no = %s
                        """,
                        (attempts, status, str(e)[:500], d["rcept_no"]),
                    )
                continue

            with db_cursor() as cur:
                cur.execute(
                    """
                    UPDATE disclosures
                    SET summary = %s, summary_status = 'done', summarized_at = %s, summary_error = NULL
                    WHERE rcept_no = %s
                    """,
                    (summary, now_kst(), d["rcept_no"]),
                )
            job.rows += 1
            logger.info("SUMMARY_DONE rcept_no=%s summarizer=%s", d["rcept_no"], summarizer.name)

        job.ok = failed == 0
        job.message = f"대상 {len(targets)}건, 성공 {job.rows}, 실패 {failed}"
        logger.info("SUMMARIZE_DONE targets=%d done=%d failed=%d", len(targets), job.rows, failed)

    return 1 if failed else 0


def show_document(rcept_no: str) -> int:
    """확인용: 원문에서 추출한 텍스트의 길이와 앞부분을 출력한다."""
    from collector.dart import fetch_document_text

    text = fetch_document_text(rcept_no, config.SUMMARY_SOURCE_MAX_CHARS)
    print(f"추출 길이: {len(text)}자 (상한 {config.SUMMARY_SOURCE_MAX_CHARS})")
    print(text[:800])
    return 0

INSERT_BACKFILL = """
    INSERT INTO price_minute
        (stock_code, ts, price, change_rate, volume, source, collected_at)
    VALUES (%s, %s, %s, NULL, NULL, 'backfill', %s)
    ON DUPLICATE KEY UPDATE stock_code = stock_code
"""

MAX_BACKFILL_CALLS = 14   # 30건 × 14회 = 420분 → 하루(391분)를 넘는 상한


def expected_minutes(day: date, until: dtime) -> list[datetime]:
    """day 의 09:00 부터 until 까지 있어야 할 분 목록"""
    t = datetime.combine(day, MARKET_OPEN)
    end = datetime.combine(day, until)
    result = []
    while t <= end:
        result.append(t)
        t += timedelta(minutes=1)
    return result


def group_ranges(minutes: list[datetime]) -> list[tuple[datetime, datetime, int]]:
    """정렬된 분 목록을 연속 구간 (시작, 끝, 개수) 으로 묶는다"""
    ranges: list[tuple[datetime, datetime, int]] = []
    for m in minutes:
        if ranges and m - ranges[-1][1] == timedelta(minutes=1):
            start, _, count = ranges[-1]
            ranges[-1] = (start, m, count + 1)
        else:
            ranges.append((m, m, 1))
    return ranges


def fetch_bars_for_range(provider, code: str, day: date,
                         gap_start: datetime, gap_end: datetime) -> list[Bar]:
    """gap_end 부터 과거로 30개씩 거슬러 올라가며 gap_start 까지 분봉을 모은다"""
    collected: dict[datetime, Bar] = {}   # 페이지 경계에서 겹치는 봉은 dict 로 중복 제거
    cursor = (gap_end + timedelta(minutes=1)).time()
    for _ in range(MAX_BACKFILL_CALLS):
        bars = provider.get_minute_bars(code, day, cursor)
        time.sleep(config.REQUEST_INTERVAL_SEC)   # 외부 API 호출 한도 준수
        if not bars:
            break
        for b in bars:
            collected[b.ts] = b
        oldest = min(b.ts for b in bars)
        if oldest <= gap_start:
            break
        cursor = (oldest - timedelta(minutes=1)).time()
    return list(collected.values())


def backfill(day: date) -> int:
    """day 의 수집 누락 구간을 찾아 분봉으로 채우고, 결과를 collection_gaps 에 남긴다"""
    now = now_kst()
    if day.weekday() >= 5:
        logger.info("주말이므로 누락 점검을 건너뜀 (day=%s)", day)
        return 0
    if day > now.date():
        logger.error("미래 날짜는 점검할 수 없습니다 (day=%s)", day)
        return 1

    until = MARKET_CLOSE
    if day == now.date():
        if now.time() < dtime(9, 2):
            logger.info("아직 장 초반이라 점검할 구간이 없음")
            return 0
        # 아직 확정되지 않은 최근 2분은 점검하지 않는다
        until = min(MARKET_CLOSE, (now - timedelta(minutes=2)).time().replace(second=0, microsecond=0))

    provider = get_provider()
    expected = expected_minutes(day, until)
    day_start = datetime.combine(day, dtime(0, 0))

    with job_run("backfill") as job:
        with db_cursor() as cur:
            cur.execute("SELECT DISTINCT stock_code FROM watchlist ORDER BY stock_code")
            codes = [r["stock_code"] for r in cur.fetchall()]

        gaps_found = failed_gaps = 0
        for code in codes:
            with db_cursor() as cur:
                cur.execute(
                    "SELECT ts FROM price_minute WHERE stock_code = %s AND ts >= %s AND ts < %s",
                    (code, day_start, day_start + timedelta(days=1)),
                )
                have = {r["ts"] for r in cur.fetchall()}

            missing = [m for m in expected if m not in have]
            for gap_start, gap_end, count in group_ranges(missing):
                gaps_found += 1
                detected_at = now_kst()
                try:
                    bars = fetch_bars_for_range(provider, code, day, gap_start, gap_end)
                except ProviderError as e:
                    logger.warning("BACKFILL_FETCH_FAILED code=%s gap=%s~%s error=%s",
                                   code, gap_start.time(), gap_end.time(), e)
                    bars = []

                rows = [(code, b.ts, b.price, now_kst()) for b in bars
                        if gap_start <= b.ts <= gap_end]
                recovered = 0
                if rows:
                    with db_cursor() as cur:
                        cur.executemany(INSERT_BACKFILL, rows)
                        recovered = cur.rowcount

                status = "recovered" if recovered >= count else "failed"
                if status == "failed":
                    failed_gaps += 1
                with db_cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO collection_gaps
                            (stock_code, trade_date, gap_start, gap_end, missing_count,
                             status, detected_at, recovered_at, recovered_count)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (code, day, gap_start, gap_end, count, status, detected_at,
                         now_kst() if recovered else None, recovered),
                    )
                job.rows += recovered
                logger.info("GAP code=%s range=%s~%s missing=%d recovered=%d status=%s",
                            code, gap_start.time(), gap_end.time(), count, recovered, status)

        job.ok = failed_gaps == 0
        job.message = f"{day} 누락 구간 {gaps_found}개, 복구 실패 {failed_gaps}개, 복구 {job.rows}분"
        logger.info("BACKFILL_DONE day=%s gaps=%d failed=%d recovered_minutes=%d",
                    day, gaps_found, failed_gaps, job.rows)

    return 1 if failed_gaps else 0


def kis_minute_check(code: str, hhmmss: str) -> int:
    """KIS 분봉 연동 확인용: 응답 건수와 첫/마지막 행의 핵심 필드를 출력한다"""
    from collector.kis import KisProvider

    data = KisProvider().raw_minute_bars(code, datetime.strptime(hhmmss, "%H%M%S").time())
    rows = data.get("output2") or []
    print(f"rt_cd={data.get('rt_cd')} msg_cd={data.get('msg_cd')} msg1={data.get('msg1')} rows={len(rows)}")
    for label, row in (("첫 행", rows[0] if rows else {}), ("마지막 행", rows[-1] if rows else {})):
        print(f"  [{label}] " + " ".join(
            f"{k}={row.get(k)}" for k in ("stck_bsop_date", "stck_cntg_hour", "stck_prpr", "cntg_vol")))
    return 0 if data.get("rt_cd") == "0" else 1

def ops_status() -> int:
    """운영 상태를 JSON으로 출력한다. 전체 정상이면 종료 코드 0, 아니면 1."""
    import json

    from app.ops import build_ops_status

    status = build_ops_status()
    print(json.dumps(status, ensure_ascii=False, default=str, indent=2))
    return 0 if status["overall"] == "ok" else 1

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

    p_disc = sub.add_parser("collect-disclosures", help="관심종목 공시 수집")
    p_disc.add_argument("--days", type=int, default=3, help="오늘부터 며칠 전까지 조회할지 (기본 3)")

    p_sum = sub.add_parser("summarize-disclosures", help="요약 대기 공시를 요약")
    p_sum.add_argument("--limit", type=int, default=config.SUMMARY_BATCH_LIMIT)

    p_doc = sub.add_parser("show-document", help="(확인용) 공시 원문 추출 결과 출력")
    p_doc.add_argument("rcept_no")

    p_back = sub.add_parser("backfill", help="수집 누락 구간 감지 및 분봉으로 재수집")
    p_back.add_argument("--date", type=date.fromisoformat, default=None, help="기본값: 오늘")

    p_kmin = sub.add_parser("kis-minute-check", help="KIS 당일 분봉 연동 확인")
    p_kmin.add_argument("code")
    p_kmin.add_argument("hhmmss", help="기준 시각. 예: 153000")

    sub.add_parser("sync-stocks", help="DART 회사 목록으로 종목 데이터 동기화")
    sub.add_parser("ops-status", help="운영 상태를 JSON으로 출력 (정상이면 종료 코드 0)")

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
        if args.command == "collect-disclosures":
            return collect_disclosures(args.days)
        if args.command == "summarize-disclosures":
            return summarize_disclosures(args.limit)
        if args.command == "show-document":
            return show_document(args.rcept_no)
        if args.command == "backfill":
            return backfill(args.date or now_kst().date())
        if args.command == "kis-minute-check":
            return kis_minute_check(args.code, args.hhmmss)
        if args.command == "ops-status":
            return ops_status()
    except Exception:
        logger.exception("작업 중 예상하지 못한 오류")
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())