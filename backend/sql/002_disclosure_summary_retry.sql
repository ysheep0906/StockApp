-- 002: 요약 실패 시 재시도 횟수와 마지막 오류를 기록한다
ALTER TABLE disclosures
    ADD COLUMN IF NOT EXISTS summary_attempts TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER summary_status,
    ADD COLUMN IF NOT EXISTS summary_error VARCHAR(500) NULL AFTER summary_attempts;