# HAWK — Hongik Anomaly WatchKeeper

다변량 시계열 이상탐지 웹앱. CSV를 업로드하면 6개 탐지기가 데이터에 맞춰 임계값을 스스로 수립하고, 합의 투표로 이상을 판정한다. 라벨이 없는 데이터를 평가하기 위해 합성 이상을 주입해 탐지 품질을 정량화한다.

배포: https://sequence-project2-hawk.up.railway.app/

시계열분석 프로젝트 2.

---

## 기능

- **6개 탐지기 + 합의 투표.** 통계·머신러닝·예측·변화점·패턴 계열의 탐지기를 함께 돌리고, 여러 탐지기가 동의한 시점만 이상으로 확정한다. 하드/가중/소프트 세 가지 투표 방식을 지원한다.
- **파일마다 자동 재수립.** 업로드된 데이터의 분포와 계절성을 매번 다시 측정하고, 각 탐지기의 임계값을 그 데이터에서 F1이 최대가 되는 지점으로 재추정한다. 직전 파일 대비 드리프트도 감지한다.
- **합성 주입 기반 평가.** 임의 CSV에는 정답이 없으므로, 깨끗한 구간에 스파이크·레벨시프트·분산폭발·드리프트를 주입하고 탐지기가 그걸 잡는지로 Precision/Recall/F1과 혼동 행렬을 계산한다.
- **3개 평가지표 병기.** point-wise, point-adjusted, affiliation을 나란히 보여준다. point-adjusted가 점수를 부풀리는 문제(Kim et al. 2022)를 대시보드에서 수치로 드러낸다.
- **일반화 검증.** 임계값을 앞 50%에서 정하고 성능은 뒤 50%에서 측정해 과적합 여부를 진단한다.
- **실제 라벨 벤치마크.** 탐지기가 노린 유형에만 유리하지 않은지 확인하려고, 라벨이 고정된 NAB 스타일 데이터에서 같은 파이프라인을 돌려 합성 평가와의 갭을 본다.

---

## 실행

### 로컬

```
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# http://localhost:8000
```

백엔드가 `frontend/` 정적 파일까지 서빙하므로 서버 하나로 끝난다.

### Docker

```
docker compose up --build
# http://localhost:8000
```

### 사용 흐름

1. "데모 데이터" 버튼으로 바로 보거나 CSV를 끌어다 놓는다.
2. 백엔드가 시간축·수치 변수를 자동 감지하고 6개 탐지기를 학습, 임계값을 수립한다.
3. 대시보드에서 탐지 결과·평가지표·알고리즘 비교·판단 근거를 확인한다.
4. 합의 임계(1~4표)나 활성 탐지기를 바꾸면 즉시 재계산된다.

### AI 인사이트 (선택)

"AI 인사이트" 탭은 GPT-4o가 HAWK의 탐지 결과를 해석한다. 탐지·점수·F1 계산은 전부 HAWK가 하고 AI는 수치를 읽어 설명·우선순위만 제시한다. 시스템 프롬프트가 주어진 수치 외의 값을 만들지 못하게 강제한다.

키 설정:

```
cd backend
cp .env.example .env
# .env 의 OPENAI_API_KEY=sk-... 에 실제 키 입력
uvicorn app.main:app --port 8000
```

키가 없으면 완성된 프롬프트를 화면에 띄운다. "프롬프트 복사"로 ChatGPT에 붙여넣으면 같은 결과를 얻을 수 있다. `.env`는 `.gitignore`에 등록돼 있어 커밋되지 않는다.

---

## API

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| GET | `/api/health` | 상태·탐지기 목록·Darts 가용 여부 |
| POST | `/api/analyze` | CSV 업로드 → 전체 탐지·평가 결과 |
| GET | `/api/demo` | 내장 데모 데이터로 분석 |
| GET | `/api/benchmark` | NAB 스타일 실제 라벨 벤치마크 |
| POST | `/api/explain` | 합의 N 변경 시 근거 텍스트만 재생성 |
| POST | `/api/insight` | AI 인사이트 생성 |

`/api/analyze` 응답은 변수별 탐지기 점수·임계값·ROC, 합의 투표, 합성 주입 라벨, 메타데이터를 포함한다.

---

## CSV 형식

- 첫 행은 헤더. 구분자(`,` `\t` `;` `|`)는 자동 감지.
- 시간축 컬럼은 날짜 파싱 성공률과 컬럼명으로 자동 감지하고, 없으면 행 인덱스를 쓴다.
- 나머지 수치형 컬럼은 모두 분석 대상. 결측치는 선형 보간.
- 권장 길이 50행 이상.

```
timestamp,temp_sensor,pressure,vibration,flow_rate
2026-01-01 00:00,22.13,101.2,0.51,80.3
2026-01-01 01:00,22.88,101.5,0.49,79.1
```

---

## 아키텍처

```
backend/  (FastAPI)
├── app/
│   ├── main.py            엔드포인트 + CORS + 정적 프론트 서빙
│   ├── detectors/
│   │   ├── base.py        BaseDetector 인터페이스 (Strategy 패턴)
│   │   └── algorithms.py  6개 탐지기
│   ├── core/
│   │   ├── parser.py      CSV 파싱·시간축 자동감지·데모 생성
│   │   ├── pipeline.py    합성주입·합의·평가지표·임계값 스윕
│   │   └── analysis.py    오케스트레이터 + 근거 텍스트
│   └── schemas/models.py  Pydantic 스키마
└── requirements.txt

frontend/  (정적, 빌드 불필요)
├── index.html            대시보드 + 방법론 탭
└── app.js                API 호출 + SVG 차트
```

모든 탐지기는 `BaseDetector.score(series) → [0,1]` 인터페이스를 따른다. 그래서 알고리즘 추가·비교·임계값 조정이 같은 방식으로 처리된다.

---

## 탐지 알고리즘

서로 다른 이상 유형(점·맥락·패턴·변화점)을 포착하도록 탐지기를 다양하게 구성했다. 다양성이 합의 투표의 신뢰도를 높인다.

| 탐지기 | 계열 | 근거 | 역할 |
| --- | --- | --- | --- |
| Robust Z-Score | 통계 | Iglewicz & Hoaglin (1993) | 중앙값·MAD 기반이라 이상치가 임계값을 오염시키지 않는다. 점 이상의 1차 방어선. |
| IQR Fence | 통계 | Tukey (1977) | 분포 가정이 없고 비대칭에 강하다. 임의 CSV의 안전한 기본기. |
| Isolation Forest | ML | Liu, Ting & Zhou (2008) | 무작위 분할로 고립되는 점을 찾는다. scikit-learn 구현 + 슬라이딩 윈도우로 다변량·맥락 이상에 강하다. |
| Forecast Residual (AR) | 예측 | Box & Jenkins (1970); 수업 회귀모형 자료 | 자기회귀로 다음 값을 예측하고 잔차가 크면 이상. 수업에서 배운 예측을 이상탐지로 직접 연결한 탐지기. |
| Level Shift / CUSUM | 변화점 | Page (1954) | 좌우 윈도우 평균 차로 체제 전환(센서 고장 등)을 잡는다. 구조적 변화점 담당. |
| Matrix Profile | 패턴 | Yeh et al. (2016) | 서브시퀀스 최근접 거리로 닮은꼴 없는 패턴(discord)을 탐지. 파라미터가 윈도우 길이 하나뿐이라 임의 CSV에 적합. |

### 수업 내용과의 연결

수업 자료(RNN/LSTM/GRU, Transformer, N-BEATS/N-HiTS, 트리계열 예측, Darts, 백테스팅)는 모두 예측이다. 본 프로젝트는 그 예측 관점을 이상탐지로 가져온다. 예측값과 실제값의 잔차가 크면 이상이라는 Forecast Residual 탐지기가 그 연결이다. 수업의 잔차분석(Residual/ACF)과 `check_seasonality`는 각각 잔차 기반 탐지와 Matrix Profile의 윈도우 길이 추정에 쓰였다. `requirements.txt`의 Darts는 예측기반 탐지를 RNN/N-BEATS로 확장하는 옵션으로 남겨뒀다.

---

## 합의 투표

탐지기 하나에만 의존하면 그 탐지기가 못 보는 유형에서 약해진다. 6개 판정을 모아 투표로 최종 이상을 정한다. (Aggarwal & Sathe, 2017)

- **하드 투표** `votesᵢ = Σ_k [scoreₖ,ᵢ ≥ θₖ]` — 1을 낸 탐지기 수를 세고 ≥N표면 이상으로 확정.
- **가중 투표** `wₖ ∝ F1ₖ²` — 단독 F1이 높은 탐지기에 큰 표를 줘서 약한 탐지기의 영향을 줄인다. 가중치는 합성 평가의 탐지기별 F1로 데이터마다 다시 계산되며, 사람이 손으로 정하지 않는다.
- **소프트 합의** `sᵢ = meanₖ(wₖ·scoreₖ,ᵢ)` — 0/1 대신 점수를 평균해 임계 근처에서 갈리는 경우를 부드럽게 다룬다.

합의 임계 N은 1표부터 전체까지 바꿔가며 F1을 계산해 `N* = argmax_N F1(votes ≥ N)`로 자동 선택한다. N이 낮으면 민감(재현율↑·오탐↑), 높으면 엄격(정밀도↑·놓침↑)하다.

---

## 평가 방법론

라벨 희소성과 구간성 때문에 단일 지표로는 부족하다. 세 지표를 함께 제시해 서로의 맹점을 드러낸다.

- **Point-wise F1.** 각 시점을 독립적으로 분류해 TP·FP·FN을 센다. 가장 보수적이고 해석이 명확하지만 구간 이상의 위치 오차에 가혹하다.
- **Point-adjusted F1** (Xu et al. 2018). 정답 구간 안에서 하나라도 탐지하면 구간 전체를 정탐으로 인정. 널리 쓰이지만 Kim et al.(2022)이 무작위 예측조차 높은 F1을 만든다는 것을 증명했다. 본 대시보드는 이 지표를 표시하되 한계를 함께 경고한다. 무작위 점수를 넣으면 point-wise F1은 0.1~0.2인데 point-adjusted는 0.5~0.75로 부풀려지는 것을 평가 패널에서 보여준다.
- **Affiliation F1** (Huet et al. 2022). 예측과 정답 이벤트 사이의 시간 거리로 정밀도·재현율을 정의한다. 파라미터가 없고 "거의 맞춤"을 부분 점수로 인정해 두 지표 사이를 메운다.

Range-based 지표(Tatbul et al. 2018)는 표현력은 크지만 파라미터가 많아 채택하지 않고 affiliation을 보완 지표로 썼다.

---

## 합성 이상 주입

라벨 없는 CSV를 정량 평가하기 위해, 데이터 표준편차에 비례한 4가지 이상을 고정 시드로 주입한다.

| 유형 | 설명 | 주 대상 탐지기 |
| --- | --- | --- |
| Spike | 단일 점 급등/급락 | Robust Z, IQR |
| Level Shift | 구간 평균 이동 | Level Shift, Forecast |
| Variance Burst | 구간 변동성 폭발 | Isolation Forest |
| Drift | 점진적 추세 이탈 | Forecast, Matrix Profile |

이 주입 라벨이 임계값 자동 수립(F1 스윕)과 모든 평가지표의 기준이 된다.

---

## 일반화 검증과 실제 라벨 벤치마크

합성 평가는 탐지기가 노린 유형에 유리하게 나올 수 있다. 두 장치로 이를 견제한다.

- **Train/Test 분할.** 임계값과 가중치를 앞 50%에서만 정하고 성능은 뒤 50%에서 측정한다. train과 test의 F1 차이가 작을수록 일반화된 탐지이고, 크면 그 탐지기는 특정 구간에 과적합된 것이다.
- **NAB 스타일 벤치마크.** EC2 CPU(spike·level shift)와 장비 온도(drift·급락) 두 시나리오에서, 탐지기가 볼 수 없는 고정 라벨로 같은 파이프라인을 돌린다. 합성 점수와 실제 점수의 차이가 시스템의 실제 한계를 보여준다.

---

## 배포

백엔드가 프론트까지 서빙하므로 컨테이너 하나만 올리면 된다.

```
docker compose up --build        # 로컬 확인
# 플랫폼에 backend Dockerfile 지정, 포트 8000 노출
```

기본 의존성(FastAPI·pandas·scikit-learn·NumPy)은 가벼워 무료 티어에서도 돈다. Darts/PyTorch는 `requirements.txt`에서 주석 처리해 뒀고, 활성화하려면 메모리가 큰 플랜이 필요하다.

OpenAI 키는 배포 환경에서 별도로 넣는다. `.env`는 커밋되지 않으므로 플랫폼 대시보드의 환경변수로 등록한다.

- Render: 서비스 → Environment → `OPENAI_API_KEY`
- Railway: 프로젝트 → Variables → `OPENAI_API_KEY`
- Fly.io: `fly secrets set OPENAI_API_KEY=sk-...`

키가 없어도 앱은 동작하며 AI 인사이트 탭만 "프롬프트 복사" 모드로 바뀐다. 배포 실패에 대비해 전체 소스를 zip으로도 제출한다. `pip install -r requirements.txt && uvicorn app.main:app` 두 줄로 어디서든 실행된다.

### 흔한 오류

- AI 인사이트가 "키 없음"으로 뜸 → 환경변수 `OPENAI_API_KEY` 등록 후 재배포. `/api/health`의 `openai_key_set`으로 확인.
- 빌드 중 메모리 초과 → 무료 티어(512MB)에서 가끔 발생. 한 단계 위 플랜을 쓰거나 numpy/pandas 버전을 고정.
- 첫 요청이 느림 → 무료 티어는 유휴 시 슬립된다. 첫 분석에 10~30초 걸릴 수 있다.
- `darts_available: false` → 정상. Darts는 선택 의존성이고 없어도 6개 탐지기는 전부 동작한다.

---

## 한계

- 합성 주입 평가는 주입한 유형에 대한 탐지력만 측정한다. 실제 도메인 이상이 다르면 지표가 그대로 옮겨지지 않는다. affiliation·point-wise 병기와 실제 라벨 벤치마크로 과신을 막는다.
- "다변량"이지만 실제로는 각 변수를 독립 단변량으로 분석하고 변수별 이상 밀도를 비교한다. 변수 간 상관 구조가 깨지는 순간은 잡지 못한다. PCA 재구성 오차 기반 탐지기를 추가하면 확장된다.
- 전체 시계열을 한 번에 받는 배치 구조다. 한 점씩 들어오는 온라인 스트리밍 탐지는 지원하지 않는다.
- Matrix Profile은 O(n²)이라 수만 점 이상에서 느려진다(수천 점까지 쾌적).

---

## 참고문헌

- Iglewicz, B., & Hoaglin, D. (1993). *How to Detect and Handle Outliers*. ASQC Quality Press.
- Tukey, J. W. (1977). *Exploratory Data Analysis*. Addison-Wesley.
- Liu, F. T., Ting, K. M., & Zhou, Z.-H. (2008). Isolation Forest. *ICDM*.
- Box, G. E. P., & Jenkins, G. M. (1970). *Time Series Analysis: Forecasting and Control*.
- Page, E. S. (1954). Continuous Inspection Schemes. *Biometrika*.
- Yeh, C.-C. M., et al. (2016). Matrix Profile I. *ICDM*.
- Aggarwal, C. C., & Sathe, S. (2017). *Outlier Ensembles*. Springer.
- Xu, H., et al. (2018). Unsupervised Anomaly Detection via VAE for Seasonal KPIs. *WWW*.
- Kim, S., et al. (2022). Towards a Rigorous Evaluation of Time-series Anomaly Detection. *AAAI*.
- Huet, A., Navarro, J. M., & Rossi, D. (2022). Local Evaluation of Time Series Anomaly Detection Algorithms. *KDD*.
- Tatbul, N., et al. (2018). Precision and Recall for Time Series. *NeurIPS*.
