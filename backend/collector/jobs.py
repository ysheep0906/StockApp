from contextlib import contextmanager
from dataclasses import dataclass

from app.db import db_cursor
from app.timeutil import now_kst


@dataclass
class JobResult:
    rows: int = 0
    ok: bool = True
    message: str | None = None


@contextmanager
def job_run(job_name: str):
    """작업 실행을 job_runs 테이블에 기록한다.
    시작 시 'running'을 먼저 커밋해 두므로, 프로세스가 강제 종료되면
    finished_at 이 비어 있는 행이 남아 비정상 종료를 감지할 수 있다.
    """
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO job_runs (job_name, started_at, status) VALUES (%s, %s, 'running')",
            (job_name, now_kst()),
        )
        run_id = cur.lastrowid

    result = JobResult()
    status = "failed"
    try:
        yield result
        status = "success" if result.ok else "failed"
    except BaseException as e:
        # Ctrl+C(KeyboardInterrupt) 같은 중단도 실패로 기록
        result.message = f"{type(e).__name__}: {e}"[:1000]
        raise
    finally:
        with db_cursor() as cur:
            cur.execute(
                """
                UPDATE job_runs
                SET finished_at = %s, status = %s, rows_affected = %s, message = %s
                WHERE id = %s
                """,
                (now_kst(), status, result.rows, result.message, run_id),
            )