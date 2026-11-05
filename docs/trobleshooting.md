## [2026-11-04] 배포 후 헬스체크 db: unreachable
- 증상: /api/health 가 {"status":"error","db":"unreachable"}
- 확인한 것: journalctl 의 'DB health check failed' 로그를 시간순으로 확인
  - 23:57~23:58  2003 No route to host  → db VM 꺼짐 (스냅샷 후 전원을 켜지 않음)
  - 23:58 이후    1045 Access denied (using password: YES) → 설정 파일 비밀번호 불일치
  - 비밀번호 길이·줄바꿈·공백을 값 출력 없이 검사
- 원인: ① db 서버 미기동 ② 운영 설정 파일의 DB 비밀번호가 DB 계정과 다름
- 해결: db 기동, 비밀번호를 새로 생성해 DB와 설정 파일에 동일하게 적용, 서비스 재시작
- 배운 점: 오류 종류가 바뀌는 것은 한 겹이 풀리고 다음 문제가 드러났다는 신호.
  No route to host 는 서버 다운과 방화벽 거부 모두에서 나온다.
  설정 파일 수정 후에는 서비스를 재시작해야 반영된다.

  ## [2026-11-05] 운영 로그인이 500 Internal Server Error
- 증상: 정상 로그인, 틀린 로그인 모두 500. 요청마다 약 3초 후 실패
- 확인한 것:
  - 앱에 직접 요청해도 500 → Nginx 무관, 앱 내부 문제
  - traceback: auth.login → db_cursor → pymysql.connect
    → OperationalError (2003, No route to host)
  - 실패까지 약 3초 → 방화벽 거부(즉시)가 아니라 ARP 실패(서버 꺼짐) 패턴
  - ip neigh 에서 db 주소 FAILED, VMware 에서 db VM 꺼짐 확인
- 원인: db VM 미기동 (두 번째 발생)
- 해결: db 기동
- 재발 방지:
  - DB 연결 실패를 500 대신 503 + DB_UNAVAILABLE 로그로 응답 (원인이 바로 드러나게)
  - runbook 에 서버 시작 순서 명시
  - 모니터링 단계에서 DB 다운 감지·알림 추가 예정
- 배운 점: traceback 은 우리 코드가 처음 나오는 줄부터 아래만 보면 된다.
  실패까지 걸린 시간도 원인을 구분하는 단서가 된다 (즉시 거부 vs 응답 없음)