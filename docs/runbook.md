## 수집 누락 재수집
- 자동: 평일 15:40 backfill 실행 (배포 후 systemd timer)
- 수동: python -m collector.run backfill [--date YYYY-MM-DD]
- 주의: KIS 당일 분봉 API는 당일만 제공. 당일 재수집을 놓치면 이 방법으로는 복구 불가
- 개선 과제: 과거 분봉 API(FHKST03010230, 1회 120건, 최대 1년 보관)를 쓰면 과거 일자 복구 가능 (미구현)
- 알려진 한계: 거래가 없던 분은 분봉이 없어 복구 실패로 남을 수 있음 / 공휴일 판단 미구현