-- 001_init.sql
-- 규칙: 모든 DATETIME/DATE 값은 KST(Asia/Seoul) 기준이며, 애플리케이션이 직접 넣는다.
--       DB 기본값(CURRENT_TIMESTAMP 등)으로 시간을 채우지 않는다.

CREATE TABLE IF NOT EXISTS users (
    id            INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    username      VARCHAR(50)  NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at    DATETIME     NOT NULL,
    last_login_at DATETIME     NULL,
    UNIQUE KEY uk_users_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sessions (
    token_hash CHAR(64)     NOT NULL PRIMARY KEY,   -- SHA-256 hex. 원본 토큰은 저장하지 않음
    user_id    INT UNSIGNED NOT NULL,
    created_at DATETIME     NOT NULL,
    expires_at DATETIME     NOT NULL,
    KEY idx_sessions_user (user_id),
    KEY idx_sessions_expires (expires_at),
    CONSTRAINT fk_sessions_user FOREIGN KEY (user_id)
        REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS stocks (
    code           CHAR(6)      NOT NULL PRIMARY KEY,
    name           VARCHAR(100) NOT NULL,
    market         VARCHAR(10)  NULL,               -- KOSPI / KOSDAQ
    dart_corp_code CHAR(8)      NULL,
    updated_at     DATETIME     NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS watchlist (
    id             INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id        INT UNSIGNED NOT NULL,
    stock_code     CHAR(6)      NOT NULL,
    alert_up_pct   DECIMAL(5,2) NULL,               -- 예: 3.00 이면 +3% 이상 상승 시 알림
    alert_down_pct DECIMAL(5,2) NULL,               -- 예: 3.00 이면 -3% 이하 하락 시 알림
    created_at     DATETIME     NOT NULL,
    UNIQUE KEY uk_watchlist_user_stock (user_id, stock_code),
    CONSTRAINT fk_watchlist_user FOREIGN KEY (user_id)
        REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_watchlist_stock FOREIGN KEY (stock_code)
        REFERENCES stocks (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 행이 가장 많이 쌓이는 테이블. 쓰기 성능을 위해 외래키는 걸지 않음
CREATE TABLE IF NOT EXISTS price_minute (
    stock_code   CHAR(6)         NOT NULL,
    ts           DATETIME        NOT NULL,          -- 분 단위 (초는 항상 00)
    price        INT UNSIGNED    NOT NULL,
    change_rate  DECIMAL(6,2)    NULL,              -- 전일 대비 등락률(%). 재수집 데이터는 NULL 가능
    volume       BIGINT UNSIGNED NULL,              -- 누적 거래량
    source       ENUM('poll', 'backfill') NOT NULL, -- 정상 수집 / 재수집 구분
    collected_at DATETIME        NOT NULL,
    PRIMARY KEY (stock_code, ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS disclosures (
    rcept_no       CHAR(14)     NOT NULL PRIMARY KEY,  -- DART 접수번호
    stock_code     CHAR(6)      NOT NULL,
    corp_name      VARCHAR(100) NOT NULL,
    report_nm      VARCHAR(300) NOT NULL,
    rcept_dt       DATE         NOT NULL,
    summary        TEXT         NULL,
    summary_status ENUM('pending', 'done', 'failed') NOT NULL DEFAULT 'pending',
    summarized_at  DATETIME     NULL,
    collected_at   DATETIME     NOT NULL,
    KEY idx_disclosures_stock_date (stock_code, rcept_dt)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS alert_log (
    id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id     INT UNSIGNED  NOT NULL,
    stock_code  CHAR(6)       NOT NULL,
    alert_type  ENUM('up', 'down') NOT NULL,
    trade_date  DATE          NOT NULL,
    price       INT UNSIGNED  NOT NULL,
    change_rate DECIMAL(6,2)  NOT NULL,
    sent_at     DATETIME      NOT NULL,
    UNIQUE KEY uk_alert_once_per_day (user_id, stock_code, alert_type, trade_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS job_runs (
    id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    job_name      VARCHAR(50) NOT NULL,             -- 예: collect_price, backfill, dart_fetch
    started_at    DATETIME    NOT NULL,
    finished_at   DATETIME    NULL,
    status        ENUM('running', 'success', 'failed') NOT NULL,
    rows_affected INT         NULL,
    message       TEXT        NULL,
    KEY idx_job_runs_name_started (job_name, started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS collection_gaps (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    stock_code      CHAR(6)  NOT NULL,
    trade_date      DATE     NOT NULL,
    gap_start       DATETIME NOT NULL,
    gap_end         DATETIME NOT NULL,
    missing_count   INT      NOT NULL,
    status          ENUM('detected', 'recovered', 'failed') NOT NULL,
    detected_at     DATETIME NOT NULL,
    recovered_at    DATETIME NULL,
    recovered_count INT      NULL,
    KEY idx_gaps_date (trade_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;