from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.db import db_cursor
from app.market import is_trading_time
from app.timeutil import now_kst

router = APIRouter(tags=["ops"], dependencies=[Depends(get_current_user)])

# 시작한 지 이 시간이 지났는데 아직 running 이면 비정상 종료로 본다
STUCK_AFTER = timedelta(minutes=10)


def _always(now: datetime) -> bool:
    return True


def _business_hours(now: datetime) -> bool:
    return now.weekday() < 5 and time(8, 30) <= now.time() <= time(20, 0)


@dataclass(frozen=True)
class JobRule:
    label: str
    max_age: timedelta                        # 마지막 성공이 이보다 오래되면 '지연'
    check_window: Callable[[datetime], bool]  # 이 시간대에만 지연 여부를 검사


# 주의: 배포 후 systemd timer 스케줄을 바꾸면 이 기대치도 함께 바꿔야 한다
JOB_RULES: dict[str, JobRule] = {
    "collect_price": JobRule("시세 수집 (1분)", timedelta(minutes=3), is_trading_time),
    "price_alert": JobRule("가격 알림", timedelta(minutes=3), is_trading_time),
    "collect_disclosures": JobRule("공시 수집 (30분)", timedelta(minutes=70), _business_hours),
    "summarize_disclosures": JobRule("공시 요약 (30분)", timedelta(minutes=70), _business_hours),
    "backfill": JobRule("누락 재수집 (15:40)", timedelta(hours=80), _always),   # 주말 포함
    "sync_stocks": JobRule("종목 동기화 (주 1회)", timedelta(days=8), _always),
}


def _job_state(rule: JobRule, last: dict | None, last_success_at: datetime | None,
               now: datetime) -> str:
    if last is None:
        return "unknown"
    if last["status"] == "running":
        return "stuck" if now - last["started_at"] > STUCK_AFTER else "running"
    if last["status"] == "failed":
        return "failed"
    if rule.check_window(now) and (
        last_success_at is None or now - last_success_at > rule.max_age
    ):
        return "stale"
    return "ok"


def build_ops_status() -> dict:
    """운영 상태를 한 번에 모은다. 화면(API)과 CLI(이후 AI 일일 점검)가 같이 쓴다."""
    now = now_kst()
    with db_cursor() as cur:
        # 작업별 가장 최근 실행
        cur.execute(
            """
            SELECT j.job_name, j.started_at, j.finished_at, j.status, j.rows_affected, j.message
            FROM job_runs j
            JOIN (SELECT job_name, MAX(id) AS max_id FROM job_runs GROUP BY job_name) t
              ON t.max_id = j.id
            """
        )
        last_runs = {r["job_name"]: r for r in cur.fetchall()}

        cur.execute(
            """
            SELECT job_name, MAX(finished_at) AS last_success
            FROM job_runs WHERE status = 'success' GROUP BY job_name
            """
        )
        last_success = {r["job_name"]: r["last_success"] for r in cur.fetchall()}

        cur.execute(
            """
            SELECT job_name, COUNT(*) AS cnt FROM job_runs
            WHERE status = 'failed' AND started_at >= %s GROUP BY job_name
            """,
            (now - timedelta(hours=24),),
        )
        failures = {r["job_name"]: r["cnt"] for r in cur.fetchall()}

        cur.execute(
            """
            SELECT id, job_name, started_at FROM job_runs
            WHERE status = 'running' AND started_at < %s ORDER BY started_at
            """,
            (now - STUCK_AFTER,),
        )
        stuck_runs = cur.fetchall()

        cur.execute(
            """
            SELECT id, job_name, started_at, finished_at, message FROM job_runs
            WHERE status = 'failed' ORDER BY id DESC LIMIT 10
            """
        )
        recent_failures = cur.fetchall()

        cur.execute(
            """
            SELECT g.trade_date, g.stock_code, s.name, g.gap_start, g.gap_end,
                   g.missing_count, g.recovered_count, g.status, g.detected_at
            FROM collection_gaps g
            LEFT JOIN stocks s ON s.code = g.stock_code
            WHERE g.trade_date >= %s
            ORDER BY g.id DESC LIMIT 20
            """,
            (now.date() - timedelta(days=7),),
        )
        gaps = cur.fetchall()

        cur.execute("SELECT summary_status, COUNT(*) AS cnt FROM disclosures GROUP BY summary_status")
        queue = {r["summary_status"]: r["cnt"] for r in cur.fetchall()}

    jobs = []
    for name, rule in JOB_RULES.items():
        last = last_runs.get(name)
        jobs.append({
            "job_name": name,
            "label": rule.label,
            "state": _job_state(rule, last, last_success.get(name), now),
            "last_started_at": last["started_at"] if last else None,
            "last_status": last["status"] if last else None,
            "last_rows": last["rows_affected"] if last else None,
            "last_message": last["message"] if last else None,
            "last_success_at": last_success.get(name),
            "failures_24h": failures.get(name, 0),
        })

    states = {j["state"] for j in jobs}
    if stuck_runs or states & {"failed", "stuck"}:
        overall = "error"
    elif "stale" in states:
        overall = "warn"
    else:
        overall = "ok"

    return {
        "now": now,
        "trading": is_trading_time(now),
        "overall": overall,
        "jobs": jobs,
        "stuck_runs": stuck_runs,
        "recent_failures": recent_failures,
        "gaps": gaps,
        "summary_queue": {k: queue.get(k, 0) for k in ("pending", "done", "failed")},
    }


@router.get("/api/ops/status")
def ops_status():
    return build_ops_status()