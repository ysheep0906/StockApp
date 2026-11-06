#!/bin/bash
# 백엔드 배포: sudo stockapp-deploy <커밋번호>
# 전제: /tmp/stockapp-<커밋번호>.tar.gz 가 업로드되어 있어야 한다
set -euo pipefail

REV="$1"
ARCHIVE="/tmp/stockapp-${REV}.tar.gz"
BASE=/opt/stockapp
REL="$BASE/releases/$(date +%Y%m%d-%H%M)-${REV}"
LOG=/var/log/stockapp-deploy.log
HEALTH=http://127.0.0.1:8000/api/health

log() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }

healthy() {
    curl -fsS -m 3 "$HEALTH" 2>/dev/null | grep -q '"status":"ok"'
}

[ -f "$ARCHIVE" ] || { log "중단: 아카이브 없음 $ARCHIVE"; exit 1; }

# 1. 배포 전 점검: 지금이 이미 비정상이면 배포하지 않는다
#    (DB 다운 등 환경 문제를 새 버전 탓으로 착각하고 롤백하는 일을 막음)
if ! healthy; then
    log "중단: 배포 전 헬스체크 실패. 현재 환경부터 확인할 것 (DB 상태 등)"
    exit 1
fi

PREV=$(readlink -f "$BASE/current")
log "배포 시작 rev=$REV prev=$PREV"

# 2. 새 릴리스 준비 (여기서 실패하면 current 는 그대로라 서비스 영향 없음)
mkdir -p "$REL"
tar -xzf "$ARCHIVE" -C "$REL"
python3.12 -m venv "$REL/venv"
"$REL/venv/bin/pip" install --quiet --no-cache-dir -r "$REL/backend/requirements.txt"

# 3. 전환
ln -sfn "$REL" "$BASE/current"
systemctl restart stockapp-api

# 4. 헬스체크: 재시작 직후엔 준비가 안 됐을 수 있으므로 최대 30초 재시도
for i in $(seq 1 15); do
    if healthy; then
        log "배포 성공 rev=$REV release=$REL (헬스체크 ${i}회째 통과)"
        rm -f "$ARCHIVE"
        exit 0
    fi
    sleep 2
done

# 5. 실패하면 자동 롤백
log "헬스체크 실패 → 롤백 prev=$PREV"
ln -sfn "$PREV" "$BASE/current"
systemctl restart stockapp-api
sleep 3
healthy && log "롤백 후 정상" || log "경고: 롤백 후에도 비정상. 즉시 확인 필요"
exit 1