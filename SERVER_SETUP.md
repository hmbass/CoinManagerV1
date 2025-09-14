# 🖥️ 서버 환경 설정 가이드

Linux/Ubuntu 서버에서 업비트 자동매매 시스템을 설정하고 실행하는 방법을 안내합니다.

## 🚀 빠른 설정 (원클릭 설치)

```bash
# 프로젝트 디렉토리로 이동
cd ~/CoinManagerV1

# 자동 환경 설정 실행
./scripts/server-manager.sh setup

# API 키 설정 (필수!)
nano .env
# UPBIT_ACCESS_KEY와 UPBIT_SECRET_KEY를 실제 값으로 변경

# 시스템 테스트
./scripts/server-manager.sh health

# 자동매매 시작
./scripts/server-manager.sh start
```

## 📋 상세 설정 단계

### 1️⃣ 시스템 요구사항 확인

```bash
# Python 3.11+ 설치 확인
python3 --version

# 필수 패키지 설치 (Ubuntu/Debian)
sudo apt update
sudo apt install -y python3-pip python3-venv python3-dev build-essential

# Git 설치 (프로젝트 다운로드용)
sudo apt install -y git
```

### 2️⃣ 프로젝트 다운로드

```bash
# Git으로 다운로드
git clone https://github.com/YOUR_USERNAME/upbit-trading-system.git
cd upbit-trading-system

# 또는 파일 업로드 후
cd ~/CoinManagerV1
```

### 3️⃣ 환경 설정

```bash
# 자동 설정 실행
./scripts/server-manager.sh setup
```

또는 수동 설정:

```bash
# 가상환경 생성
python3 -m venv .venv
source .venv/bin/activate

# 의존성 설치
pip install --upgrade pip
pip install -e .[dev]

# 환경변수 파일 생성
cp .env.example .env
```

### 4️⃣ API 키 설정

```bash
# .env 파일 편집
nano .env
```

다음 내용을 실제 값으로 변경:

```bash
UPBIT_ACCESS_KEY=your_real_access_key_here
UPBIT_SECRET_KEY=your_real_secret_key_here
TRADING_MODE=paper  # 처음엔 paper로 테스트!

# 텔레그램 알림 (선택사항)
TELEGRAM_BOT_TOKEN=your_bot_token_here  
TELEGRAM_CHAT_ID=your_chat_id_here
```

### 5️⃣ 시스템 테스트

```bash
# 연결 테스트
./scripts/server-manager.sh health

# 시장 스캔 테스트
source .venv/bin/activate
python3 -m src.app scan
```

## 🎛️ 서버 관리 명령어

### 기본 명령어

```bash
# 환경 설정 (처음 한 번만)
./scripts/server-manager.sh setup

# 시스템 시작
./scripts/server-manager.sh start

# 시스템 중지
./scripts/server-manager.sh stop

# 시스템 재시작
./scripts/server-manager.sh restart

# 상태 확인
./scripts/server-manager.sh status

# 헬스 체크
./scripts/server-manager.sh health
```

### 로그 확인

```bash
# 거래 로그 확인
./scripts/server-manager.sh logs trading

# 에러 로그 확인
./scripts/server-manager.sh logs error

# 모든 로그 확인
./scripts/server-manager.sh logs all
```

### 백업 및 관리

```bash
# 데이터 백업
./scripts/server-manager.sh backup

# 도움말
./scripts/server-manager.sh help
```

## 🔧 문제 해결

### 가상환경 오류

```bash
# 오류: Virtual environment not found
./scripts/server-manager.sh setup

# 또는 수동으로:
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

### 권한 오류

```bash
# 스크립트 실행 권한 부여
chmod +x scripts/server-manager.sh

# 로그 디렉토리 권한 확인
mkdir -p runtime/logs
chmod 755 runtime/logs
```

### API 연결 오류

```bash
# .env 파일 확인
cat .env | grep UPBIT

# API 키 테스트
source .venv/bin/activate
python3 -m src.app health
```

### Python 버전 오류

```bash
# Python 3.11+ 설치 (Ubuntu 20.04+)
sudo apt update
sudo apt install software-properties-common
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt install python3.11 python3.11-venv python3.11-dev
```

## 🚀 자동 시작 설정 (systemd)

서버 부팅 시 자동으로 시작하려면:

```bash
# systemd 서비스 파일 생성
sudo nano /etc/systemd/system/upbit-trading.service
```

내용:

```ini
[Unit]
Description=Upbit Trading System
After=network.target

[Service]
Type=forking
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/CoinManagerV1
ExecStart=/home/YOUR_USERNAME/CoinManagerV1/scripts/server-manager.sh start
ExecStop=/home/YOUR_USERNAME/CoinManagerV1/scripts/server-manager.sh stop
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

서비스 활성화:

```bash
sudo systemctl daemon-reload
sudo systemctl enable upbit-trading
sudo systemctl start upbit-trading

# 상태 확인
sudo systemctl status upbit-trading
```

## 📊 모니터링

### 실시간 모니터링

```bash
# 로그 실시간 확인
tail -f runtime/logs/trading.log

# 시스템 리소스 모니터링
htop

# 디스크 사용량
df -h
du -sh runtime/
```

### 성능 확인

```bash
# 거래 통계
./scripts/server-manager.sh status

# 백업 파일 확인
ls -la backups/
```

## 🔐 보안 권장사항

```bash
# 파일 권한 설정
chmod 600 .env
chmod 644 configs/*
chmod 755 scripts/*

# 방화벽 설정 (필요한 포트만)
sudo ufw enable
sudo ufw allow ssh

# 로그 로테이션 설정
sudo nano /etc/logrotate.d/upbit-trading
```

## ✅ 설정 완료 체크리스트

- [ ] Python 3.11+ 설치됨
- [ ] 가상환경 생성됨 (`.venv/` 디렉토리 존재)
- [ ] 의존성 설치 완료
- [ ] `.env` 파일에 API 키 설정됨
- [ ] Health check 통과
- [ ] 시장 스캔 테스트 성공
- [ ] 로그 파일 생성 확인 (`runtime/logs/`)
- [ ] 백업 디렉토리 생성 (`backups/`)

---

🎉 **설정 완료!** 이제 안전하게 자동매매 시스템을 운영할 수 있습니다.
