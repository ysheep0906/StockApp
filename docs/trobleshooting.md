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

  ## [2026-11-05] 배포 후 새 기능이 동작하지 않음 (ImportError: is_trading_day)
- 증상: 배포 성공 후 확인 단계에서 holidays.txt 없음, is_trading_day ImportError
- 확인한 것: 오류 경로가 이전 릴리스(e81fccd)를 가리킴 → current 링크 확인
- 원인: 헬스체크 성공 후에도 롤백 명령을 실행해 이전 버전으로 되돌아감
- 해결: current 를 새 릴리스로 재지정, 재시작
- 배운 점: 오류 메시지의 파일 경로로 실행 중인 버전을 알 수 있다.
  재시작 직후에는 앱이 준비되지 않아 헬스체크가 빈 응답일 수 있다 → 재시도 필요
- 부수 결과: 롤백 소요 시간 약 20초 확인

## [2026-11-05] requirements.txt 에 무관한 패키지 수십 개 포함
- 증상: 서버 배포 시 PyQt5, playwright, pyinstaller 등 수백 MB 설치
- 원인: 전역 Python 환경에서 pip freeze 를 실행해 다른 프로젝트 패키지까지 기록됨
- 해결: 직접 의존성만 requirements.in 으로 분리, 깨끗한 venv 에서 재생성
- 결과: venv 용량 OOO MB → OOO MB, 패키지 수 OO개 → OO개 (실측값 기입)
- 재발 방지: requirements.txt 는 깨끗한 venv 에서만 생성, 커밋 전 목록 확인

## [2026-11-06] Prometheus 화면에 "Server time is out of sync" (약 1시간 4분)
- 증상: 브라우저와 mon 서버 시간 차이 1h 4m 28s 경고
- 확인한 것: w32tm 으로 Windows 시계, chronyc tracking 으로 VM 4대의 오차 비교
- 원인: (확인 결과. 예: mon VM 일시정지 후 재개로 시계 뒤처짐)
  chrony 기본 설정(makestep 1.0 3)은 시작 직후에만 즉시 보정하고
  이후엔 천천히 따라잡아 1시간 차이가 수 시간 지속됨
- 해결: chronyc makestep 으로 즉시 보정
- 재발 방지: open-vm-tools 설치, makestep 1.0 -1 (트레이드오프는 decisions.md),
  Suspend 대신 정상 종료, 시계 차이 경보 추가 예정(5-3)
- 배운 점: 시간 동기화 서비스가 "켜져 있는 것"과 "지금 맞는 것"은 다르다

## [2026-11-06] 첫 자동 운영일, 15:40 누락 재수집 실패
- 감지: Grafana "실패한 systemd 유닛" 패널 (web 1개), Discord ops-report 알림
- 확인한 것: systemctl --failed → stockapp-job@backfill / journalctl 의 GAP, BACKFILL_FETCH_FAILED
- 원인:
  1. 오전 공백(09:00~13:00): 타이머를 13:00 무렵 활성화 (운영 일정 문제)
  2. 재수집 실패: KIS 모의투자 호출 한도 초과(EGW00201). 약 0.65초 간격에서도 발생
     → 자료로 알려진 값보다 실제 한도가 엄격함을 관측으로 확인
  3. 큰 공백은 분할 호출 중 한 번 실패하면 구간 전체를 포기하는 구조
- 조치(당일): 호출 간격 0.6 → 1.2초(설정만 변경), 자정 전 수동 재수집 → 결과: (기입)
- 개선(배포): 한도 초과 시 백오프 재시도(최대 2회), 부분 수집분 보존
- 배운 점: 외부 API 한도는 문서값이 아니라 운영 관측으로 확정한다.
  당일 분봉만 제공되는 제약 때문에 "당일 안에 복구"가 운영 절차의 핵심이다