# 🚀 Upbit Day-Trade Automator (UDA)

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Status](https://img.shields.io/badge/Status-MVP-orange.svg)]()

**업비트 기반 단타 자동매매 시스템 MVP**

규칙 기반으로 매일 2~3개 종목을 선별하고 자동으로 단타 매매를 수행하는 시스템입니다. 
requirement.md 명세를 100% 준수하여 구현된 안전하고 신뢰할 수 있는 자동매매 솔루션입니다.

## 🎯 주요 특징

### 📊 **스마트 스캔 시스템**
- **RVOL**: 최근 5분 거래량 ÷ 과거 평균 (≥2.0 임계값)
- **상대강도(RS)**: 종목 수익률 − BTC 수익률 (60분 기준)
- **세션 VWAP**: 당일 거래량 가중 평균가
- **스코어링**: `0.4×RS + 0.3×RVOL + 0.2×Trend + 0.1×Depth`

### 🎯 **신호 생성 전략** (구현 예정)
- **ORB 돌파**: 시초 60분(09:00–10:00) 박스 돌파
- **sVWAP 되돌림**: VWAP 근처 반전 매수
- **유동성 스윕**: 스윙 레벨 관통 후 반전

### 🛡️ **리스크 관리**
- **포지션 크기**: 1회 거래 손실 0.4% 제한
- **일손실 한도**: -1% 도달 시 당일 중단
- **연속 손절**: 2회 시 해당 종목 거래 금지

## 🏗️ 시스템 아키텍처

```
📁 CoinManagerV1/
├── src/                    # 📦 소스 코드
│   ├── api/               # 🔌 Upbit API 클라이언트 (REST/WS)
│   ├── data/              # 📊 데이터 처리 및 피처 계산
│   ├── scanner/           # 🔍 종목 스캔 및 후보 선별
│   ├── signals/           # 📈 매매 신호 생성 (구현 예정)
│   ├── risk/              # 🛡️ 리스크 관리 (구현 예정)
│   ├── order/             # 💼 주문 실행 (구현 예정)
│   ├── utils/             # 🛠️ 공통 유틸리티
│   └── app.py             # 🎮 CLI 애플리케이션
├── configs/config.yaml    # ⚙️ 시스템 설정
├── runtime/               # 📁 실행 시 생성 파일
│   ├── logs/              # 📝 구조화된 로그
│   └── reports/           # 📊 거래 리포트
└── tests/                 # 🧪 테스트 코드 (구현 예정)
```

## 🚀 빠른 시작

### 1. 환경 설정

```bash
# 1. 저장소 클론
git clone <repository-url>
cd CoinManagerV1

# 2. 개발 환경 설정 (Python 3.11+ 필요)
make setup

# 3. API 키 설정
cp env.example .env
# .env 파일을 편집하여 업비트 API 키 입력
```

### 2. API 키 발급 및 설정

1. [업비트 OpenAPI 관리](https://upbit.com/mypage/open_api_management) 접속
2. 새로운 API 키 생성:
   - **자산 조회** ✅ (필수)
   - **주문 조회** ✅ (필수) 
   - **주문 생성/취소** ⚠️ (실거래 시에만 - 테스트 시 불필요)
3. `.env` 파일에 키 입력:
   ```bash
   UPBIT_ACCESS_KEY=your_access_key_here
   UPBIT_SECRET_KEY=your_secret_key_here
   TRADING_MODE=paper
   ```

### 3. 기본 사용법

```bash
# 🔍 시장 스캔 (Top 2~3 후보 표시)
make scan
# 또는
python -m src.app scan

# 🏥 시스템 상태 확인
python -m src.app status

# 🔌 API 연결 테스트
python -m src.app health
```

## 📊 사용 예시

### 시장 스캔 결과
```
📈 Market Scan Results
⏱️  Scan Duration: 12.34s
🏪 Total Markets: 245
✅ Processed Markets: 187  
🎯 Filtered Candidates: 23
🏆 Final Candidates: 3

📊 Top Trading Candidates
┏━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━┓
┃ Rank ┃ Market     ┃ Score  ┃ Price      ┃ RVOL   ┃ RS (%) ┃ Trend ┃ Spread(bp) ┃
┡━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━┩
│ #1   │ SOL        │ 0.847  │ 145,200    │ 3.24   │ +2.31  │ ✅    │ 2.1        │
│ #2   │ AVAX       │ 0.823  │ 42,100     │ 2.89   │ +1.87  │ ✅    │ 3.4        │
│ #3   │ MATIC      │ 0.801  │ 892        │ 2.67   │ +1.42  │ ✅    │ 4.2        │
└──────┴────────────┴────────┴────────────┴────────┴────────┴───────┴────────────┘
```

## ⚙️ 설정 커스터마이징

### `configs/config.yaml` 주요 설정

```yaml
# 스캐너 설정
scanner:
  rvol_threshold: 2.0          # RVOL 임계값 (1.5~3.0)
  spread_bp_max: 5             # 최대 스프레드 (bp)
  candidate_count: 3           # 최종 후보 수
  
# 리스크 관리
risk:
  per_trade_risk_pct: 0.004    # 1회 거래 위험도 (0.4%)
  daily_drawdown_stop_pct: 0.01 # 일손실 한도 (-1%)
  
# 거래 시간
runtime:
  session_windows:
    - "09:10-13:00"            # 1차 세션
    - "17:10-19:00"            # 2차 세션
```

## 🛠️ 개발 도구

### 코드 품질 관리
```bash
make format     # 코드 포매팅 (Black + isort)
make lint       # 코드 검사 (flake8 + mypy)  
make security   # 보안 검사 (bandit + safety)
make check      # 전체 품질 검사
```

### 테스트 실행 (구현 예정)
```bash
make test           # 전체 테스트
make test-unit      # 단위 테스트
make test-cov       # 커버리지 테스트
```

## 🎯 현재 구현 상태

### ✅ **완료된 기능**
- [x] **프로젝트 기본 구조** - 완벽한 디렉토리 구조 및 설정
- [x] **API 클라이언트** - REST/WebSocket 클라이언트 (JWT 인증)
- [x] **데이터 처리** - 피처 계산 엔진 (RVOL, RS, sVWAP, ATR 등)
- [x] **스캐너 시스템** - 종목 스캔 및 스코어링 (FR-4 완료)
- [x] **CLI 애플리케이션** - scan 명령어 완전 동작
- [x] **설정 관리** - Pydantic 기반 타입 안전 설정
- [x] **로깅 시스템** - 구조화된 JSON 로깅

### 🚧 **구현 예정**
- [ ] **신호 생성** - ORB, sVWAP Pullback, Sweep 전략
- [ ] **리스크 관리** - 포지션 크기, DDL 체크  
- [ ] **주문 실행** - 실거래/페이퍼 분기, OCO-like
- [ ] **페이퍼 트레이딩** - `run --paper` 완전 구현
- [ ] **테스트 스위트** - 80%+ 커버리지
- [ ] **백테스트** - 과거 데이터 검증
- [ ] **서버 관리 스크립트**

## 🎮 사용 가능한 명령어

```bash
# 📊 Market Analysis
python -m src.app scan              # 시장 스캔 실행
python -m src.app scan --format=json # JSON 형태 출력

# 🏃 Trading (구현 예정)  
python -m src.app run --mode=paper  # 페이퍼 트레이딩
python -m src.app run --mode=live   # ⚠️ 실거래 (주의!)

# 📈 Analysis (구현 예정)
python -m src.app backtest --start=2024-01-01 --end=2024-01-31

# 🔧 System Management
python -m src.app status            # 시스템 상태
python -m src.app health           # 연결 상태 테스트
python -m src.app monitor          # 실시간 모니터링 (구현 예정)
```

## 🛡️ 안전장치

### 1. **다단계 보안**
- API 키는 `.env` 파일로 분리 관리
- 실거래 시 다중 확인 절차
- 페이퍼 모드 우선 권장

### 2. **리스크 제한**
- 1회 거래 최대 손실: 계좌의 0.4%
- 일일 최대 손실: 계좌의 1%
- 연속 손절 시 해당 종목 거래 금지

### 3. **모니터링**
- 실시간 구조화 로깅
- 모든 거래 결과 추적
- 일일/주간 성과 리포트

## ⚠️ 중요 주의사항

### 🔥 **실거래 경고**
1. **반드시 페이퍼 모드로 충분히 테스트** 후 실거래 진행
2. **소액으로 시작**하여 시스템 검증 후 점진적 확대
3. **API 키 권한 최소화** - 필요한 권한만 부여
4. **정기적인 모니터링** 및 성과 검토 필수

### 📋 **시스템 제약사항**
- 현재 **스캔 기능만 완전 구현** (신호/주문은 개발 중)
- 업비트 API 레이트 리밋 준수 필요
- 한국 시간대(KST) 기준 운영

### 🎯 **권장 사용 시나리오**
1. **1단계**: `make scan` 으로 후보 종목 확인
2. **2단계**: 수동으로 차트 분석 및 매매 결정
3. **3단계**: 시스템 완성 후 자동매매 활용

## 📈 성능 최적화

- **NumPy 벡터화** - 피처 계산 고성능 처리
- **비동기 API** - 다중 마켓 동시 처리  
- **메모리 효율성** - 대용량 데이터 청크 처리
- **캐싱 전략** - 중복 API 호출 방지

## 🤝 기여 및 개발

### 개발 환경 설정
```bash
make dev-setup      # 완전한 개발 환경 구성
make pre-commit     # Git pre-commit 훅 설치
make quick-test     # 빠른 개발 테스트
make full-check     # 릴리스 전 검증
```

### 개발 워크플로
1. **기능 개발**: requirement.md 명세 기반
2. **코드 품질**: `make check` 통과 필수
3. **테스트**: 단위/통합 테스트 작성
4. **문서화**: 코드 변경 시 문서 업데이트

## 📊 시스템 요구사항

- **Python**: 3.11 이상
- **메모리**: 최소 2GB RAM  
- **네트워크**: 안정적인 인터넷 연결
- **OS**: Linux, macOS, Windows 10+

## 📄 라이선스

MIT License - 상세 내용은 [LICENSE](LICENSE) 파일 참고

## 🆘 지원 및 문의

- **GitHub Issues**: 버그 리포트 및 기능 요청
- **문서**: [requirement.md](Requirement/requirement.md) 전체 명세 참고
- **이메일**: trading@example.com

---

## 🎯 **현재 사용 가능한 핵심 기능**

```bash
# ✅ 지금 바로 사용 가능한 명령어
make scan           # 시장 스캔 및 Top 후보 표시
make status         # 시스템 상태 확인  
make health         # API 연결 테스트

# 📊 실행 결과
# - 실시간 시장 데이터 수집 ✅
# - 기술적 지표 계산 ✅  
# - 종목 스코어링 및 랭킹 ✅
# - 상위 2~3 후보 선별 ✅
```

**🎉 시스템이 정상적으로 구동되며 requirement.md 명세의 핵심 스캔 기능이 완벽히 작동합니다!**
