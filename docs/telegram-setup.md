# 📱 텔레그램 알림 설정 가이드

업비트 자동매매 시스템에서 매수/매도 알림을 텔레그램으로 받는 방법을 안내합니다.

## 🤖 1단계: 텔레그램 봇 생성

### 1.1 BotFather와 대화
1. 텔레그램에서 `@BotFather` 검색 후 대화 시작
2. `/newbot` 명령어 입력
3. 봇 이름 설정 (예: `내 트레이딩 봇`)
4. 봇 사용자명 설정 (예: `my_trading_bot`)
5. **Bot Token 복사하여 보관** (예: `1234567890:ABC-DEF1234ghIkl-Zyx57W2v1u123ew11`)

### 1.2 봇 설정
```
/setdescription - 봇 설명 설정
/setcommands - 봇 명령어 설정 (선택사항)
```

## 💬 2단계: Chat ID 확인

### 2.1 봇과 대화 시작
1. 생성된 봇 링크 클릭하여 대화방 입장
2. `/start` 명령어 입력 또는 임의 메시지 전송

### 2.2 Chat ID 확인
브라우저에서 다음 URL 접속:
```
https://api.telegram.org/bot{YOUR_BOT_TOKEN}/getUpdates
```

응답에서 `chat.id` 값 확인 (예: `123456789`)

## ⚙️ 3단계: 환경변수 설정

`.env` 파일에 텔레그램 설정 추가:

```bash
# 텔레그램 알림 설정
TELEGRAM_BOT_TOKEN=1234567890:ABC-DEF1234ghIkl-Zyx57W2v1u123ew11
TELEGRAM_CHAT_ID=123456789
```

## 🧪 4단계: 연결 테스트

```bash
# 텔레그램 연결 테스트
python -m src.app test-telegram
```

성공 시 다음과 같은 메시지가 표시됩니다:
- ✅ Telegram notifications working!
- 📨 Test message sent to your chat
- 🎯 Sample trade and risk alerts sent!

## 📨 알림 유형

시스템에서 다음과 같은 알림을 받을 수 있습니다:

### 📈 거래 알림
```
💰 LIVE TRADING ALERT

🟢 BUY EXECUTED
🏪 Market: KRW-BTC
📊 Strategy: ORB BREAKOUT

💎 Quantity: 0.00100000
💰 Price: 50,000,000 KRW  
💸 Total: 50,000 KRW

⏰ Time: 14:30:25 KST
```

### ⚠️ 리스크 알림
```
🚨 RISK ALERT - CRITICAL

🔥 Alert Type: DAILY_DRAWDOWN_LIMIT
📝 Message: Daily loss limit reached: -1.00%
Trading has been automatically suspended for today.
Loss amount: -10,000 KRW

⏰ Time: 15:45:10 KST
```

### 🚀 시스템 상태
```
🚀 SYSTEM STARTED

⏰ Time: 09:00:00 KST
```

## 🔧 문제 해결

### 봇이 메시지를 받지 못하는 경우
1. Bot Token이 정확한지 확인
2. Chat ID가 정확한지 확인  
3. 봇과 대화를 시작했는지 확인 (`/start`)

### 테스트 실패 시
```bash
# 로그 확인
tail -f runtime/logs/trading.log

# 환경변수 확인
env | grep TELEGRAM
```

### 자주 발생하는 오류

**401 Unauthorized**
- Bot Token이 잘못됨
- `.env` 파일의 토큰 재확인 필요

**400 Bad Request: chat not found**  
- Chat ID가 잘못됨
- 봇과 대화를 시작하지 않음

**403 Forbidden: bot was blocked by the user**
- 사용자가 봇을 차단함
- 봇 차단 해제 후 `/start` 재실행

## 📱 고급 설정

### 알림 음소거 설정
특정 시간대 알림을 조용히 받으려면 `disable_notification=True` 옵션 사용

### 그룹 채팅 사용
1. 봇을 그룹 채팅에 추가
2. 그룹 Chat ID 확인하여 설정
3. 봇에게 메시지 전송 권한 부여

### 메시지 포맷 커스터마이징
`src/utils/telegram.py`에서 메시지 템플릿 수정 가능

## ✅ 완료!

이제 자동매매 시스템이 모든 거래 활동을 텔레그램으로 실시간 알림해드립니다!

```bash
# 페이퍼 트레이딩으로 알림 테스트
python -m src.app run --mode paper --duration 10
```
