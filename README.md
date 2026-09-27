# ko부동산 가격비교 도구

개인용 **정적 부동산 비교 대시보드**입니다. 브라우저에서 `data/site-data.json`을 읽어 영등포구·성동구·마포구 아파트를 비교합니다. 서버나 DB는 필요하지 않습니다.

핵심 지표는 단순 월 최고가가 아니라 **“그 시점에 이 단지의 정상적인 중층 이상을 실제 매수하려면 대략 얼마가 필요했는가?”**를 실거래로 추정한 `정상 중층 매수가`입니다.

## 포함 범위

- 지역: 영등포구, 성동구, 마포구
- 단지: 메타데이터에 존재하는 해당 3개 구 아파트 전체를 사이트 데이터에 포함
- 기본 화면 필터: 300세대 이상
- 면적: 전용 59㎡ / 84㎡
- 실거래 원자료 보관 범위: 기본 2022-09 ~ 현재
- 비교 기간 기본값: 2025-09 ~ 현재
- 저층: 1~9층 제외
- 직거래/취소거래: 수집 단계에서 제외 가능한 자료는 제외
- 가격 추정: 기준월 → ±1 → ±2 → ±3 → ±6 → ±12개월 순으로 확대하고 가까운 달에 더 큰 가중치
- 데이터가 부족한 단지: 삭제하지 않고 `중층 데이터 부족`으로 유지

## 구조

```text
index.html                  정적 페이지
assets/style.css            UI
assets/app.js               필터·랭킹·추정 로직
assets/grade-map.png        급지 참고 지도
data/site-data.json         브라우저가 읽는 데이터
scripts/build_data.py       메타데이터 + 실거래 수집/정규화
.github/workflows/
  update-data.yml           월 1회 자동 갱신
vercel.json                 Vercel 정적 배포 설정
```

## 데이터 출처

- 실거래: 국토교통부 아파트 매매 실거래가 공개자료
  - 공식 API: `https://www.data.go.kr/data/15126468/openapi.do`
- 단지 기본정보: 서울 열린데이터광장 `OA-15818` 기반 공개 메타데이터
  - `https://data.seoul.go.kr/dataList/OA-15818/A/1/datasetView.do`
- 키가 없는 경우 실거래 수집은 국토교통부 데이터를 중계하는 공개 `k-skill-proxy`를 fallback으로 사용합니다.
- 용적률은 매칭 가능한 단지에 한해 건축물대장 표제부를 조회하고 `data/far-cache.json`에 캐시합니다. 매칭 실패 값은 임의로 만들지 않고 `—`로 둡니다.

## GitHub에 올리기

새 GitHub 저장소를 만든 뒤 이 폴더의 **내용 전체**를 `main` 브랜치에 올립니다.

첫 push에는 `data/site-data.json`이 `sample` 상태이므로 GitHub Actions가 자동으로 **영등포구·성동구·마포구 전체 구축(full build)**을 시작합니다. 완료되면 Actions가 갱신된 JSON을 저장소에 자동 커밋합니다.

공식 국토부 API를 직접 쓰고 싶으면 GitHub 저장소의 **Settings → Secrets and variables → Actions → New repository secret**에서 아래 값을 추가하세요.

```text
PUBLIC_DATA_API_KEY = 공공데이터포털 일반 인증키
```

이 secret은 선택사항입니다. 없으면 공개 proxy fallback을 사용합니다.

### 첫 전체 구축을 수동으로 다시 실행

GitHub → **Actions → Update apartment data → Run workflow**에서:

- mode: `full`
- enrich_far: `true`

를 선택합니다.

## 매월 자동 업데이트

워크플로는 **매월 1일 오전 4시(Asia/Seoul)**에 최근 3~4개월을 다시 조회합니다. 신고 지연·정정 등을 반영하기 위해 당월만 받지 않고 최근 몇 달을 재수집합니다.

자동화가 `data/site-data.json`을 커밋하면 GitHub와 연결된 Vercel이 같은 URL에 새 버전을 자동 배포합니다.

## Vercel 배포

1. Vercel 로그인
2. **Add New → Project**
3. 방금 만든 GitHub 저장소 Import
4. Framework Preset은 `Other` 그대로 사용
5. Build Command / Output Directory는 비워 둠
6. Deploy

이 프로젝트는 빌드가 필요 없는 정적 사이트라 `index.html`이 바로 서비스됩니다.

## 수동 데이터 갱신

GitHub Actions의 `Run workflow`에서 `incremental`을 선택하면 최근 데이터만 다시 받고, `full`을 선택하면 2022-09부터 전체를 다시 구축합니다.

## 가격 산정 주의

`(추정)` 가격은 감정평가액·KB시세·호가가 아닙니다. 국토교통부 신고 실거래 중 비교 가능한 중층 거래를 사용해 **비교용 정상 매수가**를 계산한 값입니다. 거래가 희박한 단지는 `*5 ~ *1` 신뢰도와 사용 거래내역을 함께 확인하세요.
