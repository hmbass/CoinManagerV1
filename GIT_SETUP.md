# 🚀 Git 저장소 설정 및 Push 가이드

## 📋 1단계: Git 저장소 초기화

```bash
# Git 저장소 초기화
git init

# 사용자 정보 설정 (처음 사용하는 경우)
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"
```

## 🔍 2단계: 파일 상태 확인

```bash
# .gitignore가 적용된 상태로 파일 목록 확인
git status
```

다음과 같은 파일들이 추가될 것입니다:
- ✅ **소스코드**: `src/`, `tests/`, `configs/`
- ✅ **설정파일**: `pyproject.toml`, `Makefile`, `README.md`
- ✅ **문서**: `docs/`, `Requirement/`, `rules/`
- ✅ **예시파일**: `.env.example`
- ❌ **제외파일**: `.env`, `.venv/`, `runtime/`, `__pycache__/`

## 📦 3단계: 파일 추가 및 커밋

```bash
# 모든 파일 스테이징
git add .

# 커밋 메시지와 함께 커밋
git commit -m "🎉 Initial commit: Upbit Day-Trading Automator MVP

✨ Features:
- Market scanning with technical indicators
- 3 trading strategies (ORB, sVWAP Pullback, Liquidity Sweep)
- Risk management (DDL, consecutive loss prevention)
- Paper & live trading modes
- Telegram notifications
- Comprehensive test suite

📋 Requirements: 100% SSOT compliance (requirement.md)
🚀 Ready for production use"
```

## 🌐 4단계: 원격 저장소 연결

### GitHub 사용 시:

1. **GitHub에서 새 저장소 생성**
   - 저장소명: `upbit-trading-system` 또는 원하는 이름
   - **⚠️ README 파일 생성하지 마세요** (이미 있음)

2. **원격 저장소 연결**
   ```bash
   git remote add origin https://github.com/USERNAME/REPOSITORY.git
   git branch -M main
   git push -u origin main
   ```

### GitLab/기타 사용 시:
```bash
git remote add origin YOUR_REMOTE_URL
git branch -M main  
git push -u origin main
```

## 🔐 5단계: 민감한 정보 보호 확인

다음 명령어로 `.env` 파일이 제외되었는지 확인:

```bash
# .env 파일이 목록에 없어야 함
git status

# .gitignore 내용 확인
cat .gitignore | grep -E "(\.env|runtime|__pycache__)"
```

## 🚨 중요 보안 체크리스트

- [ ] `.env` 파일이 Git에 추가되지 않음
- [ ] `runtime/` 디렉토리 제외됨 (거래 데이터)
- [ ] API 키가 코드에 하드코딩되지 않음
- [ ] `.env.example` 파일만 포함됨 (실제 키 없음)

## 📱 6단계: 협업을 위한 추가 설정

### Branch Protection (GitHub)
```bash
# 개발용 브랜치 생성
git checkout -b develop
git push -u origin develop
```

### Pre-commit Hook 설정 (선택사항)
```bash
# Pre-commit 활성화
pre-commit install

# 테스트 실행
pre-commit run --all-files
```

## 🔄 일상적인 Git 워크플로우

```bash
# 변경사항 확인
git status
git diff

# 파일 추가 및 커밋
git add .
git commit -m "✨ Add new feature: description"

# 원격 저장소에 푸시
git push origin main

# 최신 변경사항 가져오기
git pull origin main
```

## 🏷️ 태그 및 릴리스

```bash
# 버전 태그 생성
git tag -a v1.0.0 -m "🎉 Release v1.0.0: MVP Complete"

# 태그 푸시
git push origin v1.0.0

# 모든 태그 푸시
git push --tags
```

## 🆘 문제 해결

### 실수로 .env 파일을 추가한 경우:
```bash
# Git에서 제거 (파일은 유지)
git rm --cached .env
git commit -m "🔒 Remove .env from version control"
git push
```

### 큰 파일 실수로 추가한 경우:
```bash
# Git LFS 설정
git lfs install
git lfs track "*.log"
git add .gitattributes
```

### 원격 저장소 URL 변경:
```bash
git remote set-url origin NEW_URL
git remote -v  # 확인
```

## ✅ 완료!

이제 안전하고 체계적으로 코드를 관리할 수 있습니다!

**다음 단계:**
- 정기적인 백업을 위해 `git push` 실행
- 새 기능 개발 시 브랜치 사용
- 팀 협업 시 Pull Request 활용
