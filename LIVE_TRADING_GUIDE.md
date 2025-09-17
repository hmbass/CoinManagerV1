# 🚨 Live Trading Guide (실제 투자 가이드)

## ⚠️ 중요한 경고 / IMPORTANT WARNING

**이 시스템은 실제 돈으로 거래합니다. 모든 투자에는 손실 위험이 있습니다.**

**This system trades with REAL MONEY. All investments carry the risk of loss.**

---

## 📋 사전 준비 / Prerequisites

### 1. 업비트 API 키 설정
```bash
# .env 파일에 실제 API 키 설정
UPBIT_ACCESS_KEY=your_actual_access_key
UPBIT_SECRET_KEY=your_actual_secret_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
```

### 2. 계좌 잔고 확인
- **최소 권장 잔고**: 1,000,000 KRW (100만원)
- **거래당 위험**: 계좌의 0.2% (10만원당 200원)
- **일일 손실 한도**: 계좌의 0.5% (10만원당 500원)

### 3. 업비트 API 권한 설정
필요한 권한:
- ✅ 자산 조회 (Assets)
- ✅ 주문 조회 (Orders)
- ✅ 주문하기 (Trade)
- ❌ 출금하기 (Withdraw) - 보안상 불필요

---

## 🔧 시스템 설정 / System Configuration

### 보수적 거래 설정 (Conservative Settings)

**거래 시간**:
- 오전: 09:15 - 12:45 KST
- 오후: 17:15 - 18:45 KST

**리스크 관리**:
- 거래당 위험: 0.2% of account
- 일일 손실 한도: -0.5%
- 최대 포지션 크기: 300,000 KRW
- 연속 손실 후 중단: 1회

**시장 선택**:
- 고유동성 시장만 (일 거래량 100억원 이상)
- 최대 20개 시장 스캔
- 상위 2개 후보만 선택

---

## 🚀 Live Trading 시작하기

### 1. 시스템 상태 확인
```bash
# 환경 확인
./scripts/server-manager.sh health

# API 연결 테스트
python3 -m src.app health --config configs/live-trading.yaml
```

### 2. 텔레그램 알림 테스트
```bash
python3 -m src.app test-telegram
```

### 3. Live Trading 시작
```bash
./scripts/start-live-trading.sh
```

**⚠️ 시작 시 여러 번 확인 요청됩니다:**
1. "I UNDERSTAND THE RISKS" 입력
2. "yes" 확인
3. 최종 "yes" 확인

### 4. 상태 모니터링
```bash
# 실시간 로그 확인
tail -f runtime/logs/live_trading.log

# 시스템 상태 확인
./scripts/server-manager.sh status

# 주문 로그 확인
tail -f runtime/logs/live_orders.log
```

---

## 🛑 Live Trading 중지하기

### 정상 중지
```bash
./scripts/stop-live-trading.sh
```

### 비상 중지
```bash
./scripts/stop-live-trading.sh --emergency
```

**⚠️ 중지 후 확인사항:**
- 업비트에서 미체결 주문 확인
- 보유 포지션 확인
- 필요시 수동으로 정리

---

## 📊 모니터링 및 알림

### 텔레그램 알림 종류

**거래 알림**:
- 🎯 매수 신호 발생
- ✅ 매수 주문 체결
- 💰 매도 주문 체결 (익절/손절)

**리스크 알림**:
- ⚠️ 일일 손실 한도 근접
- 🚨 거래 중단 (DDL 도달)
- ❌ API 오류

**시스템 알림**:
- 🚀 시스템 시작
- 🛑 시스템 중지
- 🔄 시장 스캔 결과

### 로그 파일 위치
```
runtime/logs/
├── live_trading.log     # 전체 시스템 로그
├── live_error.log       # 오류 로그
├── live_orders.log      # 주문 체결 로그
└── live_api.log         # API 호출 로그
```

---

## ⚡ 긴급 상황 대응

### 시스템 응답 없음
```bash
# 1. 프로세스 강제 종료
./scripts/stop-live-trading.sh --emergency

# 2. 수동으로 프로세스 확인
ps aux | grep "src.app"
kill -9 [PID]

# 3. 업비트에서 미체결 주문 취소
```

### API 오류 발생
```bash
# 1. 시스템 중지
./scripts/stop-live-trading.sh

# 2. 오류 로그 확인
tail -100 runtime/logs/live_error.log

# 3. API 키 및 권한 재확인
```

### 예상치 못한 손실
```bash
# 1. 즉시 시스템 중지
./scripts/stop-live-trading.sh --emergency

# 2. 업비트에서 모든 포지션 확인
# 3. 필요시 수동으로 손절
```

---

## 🔒 보안 및 안전 수칙

### API 키 보안
- ❌ API 키를 코드에 하드코딩하지 마세요
- ✅ .env 파일 사용 (gitignore에 포함됨)
- ✅ 불필요한 권한은 부여하지 마세요
- ✅ 정기적으로 API 키 갱신

### 계좌 보안
- ✅ 거래용 계좌와 보관용 계좌 분리
- ✅ 전체 자산의 일부만 거래에 사용
- ✅ 2FA(이중인증) 설정
- ✅ 정기적인 계좌 확인

### 시스템 보안
- ✅ VPS 사용 시 SSH 키 인증
- ✅ 방화벽 설정
- ✅ 로그 파일 권한 관리
- ✅ 정기적인 시스템 업데이트

---

## 📈 성과 분석

### 일일 리포트
```bash
# 오늘의 거래 결과 확인
grep "Order filled" runtime/logs/live_orders.log | grep $(date +%Y-%m-%d)

# P&L 계산
python3 -c "
import json
from pathlib import Path

log_file = Path('runtime/logs/live_orders.log')
if log_file.exists():
    with open(log_file) as f:
        lines = f.readlines()
    
    pnl = 0
    trades = 0
    for line in lines:
        if 'filled' in line.lower():
            try:
                data = json.loads(line)
                if 'pnl' in data.get('data', {}):
                    pnl += data['data']['pnl']
                    trades += 1
            except:
                pass
    
    print(f'총 거래: {trades}건')
    print(f'총 P&L: {pnl:,.0f} KRW')
    print(f'평균 P&L: {pnl/max(trades,1):,.0f} KRW')
"
```

### 주간 분석
- 승률 계산
- 평균 손익비 (R-multiple)
- 최대 연속 손실
- 최대 드로우다운

---

## 🎯 최적화 가이드

### 성과 개선이 필요한 경우

**1. 리스크 줄이기**:
```yaml
# configs/live-trading.yaml 수정
risk:
  per_trade_risk_pct: 0.001  # 0.1%로 감소
  daily_drawdown_stop_pct: 0.003  # -0.3%로 감소
```

**2. 더 보수적인 신호**:
```yaml
scanner:
  rvol_threshold: 3.0  # 더 높은 임계값
  min_score: 0.7  # 더 높은 최소 점수
```

**3. 거래 빈도 줄이기**:
```yaml
runtime:
  scan_interval_minutes: 15  # 더 긴 스캔 간격
  candidate_count: 1  # 1개 후보만
```

### 성과가 좋은 경우

**주의사항**:
- 🚫 갑작스러운 포지션 크기 증가 금지
- 🚫 리스크 한도 무리하게 늘리기 금지
- ✅ 점진적인 조정만 고려
- ✅ 백테스팅으로 검증 후 적용

---

## 📞 지원 및 문의

### 문제 해결 순서
1. 🔍 로그 파일 확인
2. 📚 이 가이드 재검토
3. 🔄 시스템 재시작 시도
4. 🆘 필요시 수동 개입

### 로그 수집 (문의시 첨부)
```bash
# 문제 발생 시 로그 수집
tar -czf debug_logs_$(date +%Y%m%d_%H%M%S).tar.gz \
  runtime/logs/ \
  configs/live-trading.yaml \
  .env.example

# 개인 정보 제거 후 공유
```

---

## ⚖️ 법적 고지

**투자 위험 고지**:
- 모든 투자는 원금 손실 위험이 있습니다
- 과거 성과는 미래 수익을 보장하지 않습니다
- 본인의 투자 판단과 책임 하에 사용하세요

**시스템 책임 한계**:
- 소프트웨어 버그로 인한 손실
- 네트워크 장애로 인한 거래 실패
- 시장 급변으로 인한 예상치 못한 손실
- API 장애로 인한 주문 처리 지연

**사용 전 권고사항**:
- 충분한 테스트 (Paper Trading)
- 소액부터 시작
- 정기적인 모니터링
- 손실 한도 엄격히 준수

---

## 📚 추가 학습 자료

### 기술적 분석
- ORB (Opening Range Breakout) 전략
- sVWAP (Session Volume Weighted Average Price)
- 상대강도 (Relative Strength) 분석

### 리스크 관리
- 포지션 사이징
- 포트폴리오 이론
- 드로우다운 관리

### 시장 이해
- 암호화폐 시장 특성
- 업비트 거래 시간
- 시장 유동성과 변동성

---

## 🎉 성공적인 Live Trading을 위한 팁

1. **작게 시작하세요** - 소액으로 시작해서 경험을 쌓으세요
2. **꾸준히 모니터링** - 초기에는 자주 확인하세요
3. **감정 제거** - 시스템이 설정대로 작동하도록 두세요
4. **정기적 검토** - 주간/월간 성과를 분석하세요
5. **계속 학습** - 시장과 기술을 계속 공부하세요

**행운을 빕니다! 🍀**

---

*⚠️ 이 문서는 정보 제공 목적이며, 투자 조언이 아닙니다.*
*모든 투자 결정은 본인의 판단과 책임 하에 이루어져야 합니다.*
