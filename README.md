# k APT Dashboard v14 — 영등포구 단일지역 파일럿

이번 버전은 영등포구만 수집합니다.

## 핵심
- 매매 실거래 수집만 정상이어도 사이트 배포까지 완료합니다.
- 전세 API가 안 되면 전세/갭만 비활성화하고 계속 진행합니다.
- K-apt가 안 되면 세대수/역세권 보강만 건너뜁니다.
- 건축HUB가 안 되면 용적률 보강만 건너뜁니다.
- 부가 API 하나가 안 된다고 GitHub Actions 전체를 실패시키지 않습니다.

## 실행
GitHub → Actions → `Update Yeongdeungpo dashboard v14`
→ Run workflow
→ `건축HUB 용적률 보강 시도`는 켜둬도 됩니다.

## 제한
- 지역: 영등포구만
- Actions 최대 실행시간: 45분
- API 단일 요청: 12초, 최대 2회 재시도

## 확인
완료 후 `data/site-data.json`의 `meta.api_status`에서
전세/K-apt/FAR 사용 가능 여부를 확인할 수 있습니다.

현재 v14이며 다음 수정은 v15입니다.
