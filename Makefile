# Upbit Trading System (UDA) - Development & Deployment Commands
# Based on project-management.mdc standards

.DEFAULT_GOAL := help
SHELL := /bin/bash
PYTHON := python3
PIP := pip
VENV := .venv

# Colors for terminal output
BLUE := \033[36m
GREEN := \033[32m
YELLOW := \033[33m
RED := \033[31m
NC := \033[0m

##@ Help
help: ## Display available commands
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make $(YELLOW)<target>$(NC)\n"} /^[a-zA-Z_0-9-]+:.*?##/ { printf "  $(BLUE)%-15s$(NC) %s\n", $$1, $$2 } /^##@/ { printf "\n$(GREEN)%s$(NC)\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

##@ Environment Setup
setup: ## 🚀 Initial development environment setup
	@echo "$(GREEN)🚀 Setting up development environment...$(NC)"
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip setuptools wheel
	$(VENV)/bin/pip install -e .[dev]
	@echo "$(GREEN)📁 Creating project directories...$(NC)"
	mkdir -p runtime/logs runtime/reports runtime/data
	mkdir -p tests/unit tests/integration tests/fixtures
	mkdir -p scripts
	@if [ ! -f .env ]; then cp .env.example .env; echo "$(YELLOW)⚠️  Please edit .env with your API keys$(NC)"; fi
	@echo "$(GREEN)✅ Development environment ready!$(NC)"

install: ## 📦 Install dependencies
	@echo "$(GREEN)📦 Installing dependencies...$(NC)"
	$(VENV)/bin/pip install -e .[dev]

install-prod: ## 📦 Install production dependencies only
	$(VENV)/bin/pip install -e .

##@ Code Quality
format: ## 🎨 Format code (black + isort)
	@echo "$(GREEN)🎨 Formatting code...$(NC)"
	$(VENV)/bin/black src tests
	$(VENV)/bin/isort src tests

lint: ## 🔍 Lint code (flake8 + mypy)
	@echo "$(GREEN)🔍 Linting code...$(NC)"
	$(VENV)/bin/flake8 src tests
	$(VENV)/bin/mypy src

security: ## 🛡️ Security scan (bandit + safety)
	@echo "$(GREEN)🛡️ Running security scans...$(NC)"
	$(VENV)/bin/bandit -r src/
	$(VENV)/bin/safety check --json

check: format lint security ## ✅ Run all code quality checks

pre-commit: ## 🔧 Install pre-commit hooks
	$(VENV)/bin/pre-commit install

##@ Testing
test: ## 🧪 Run all tests
	@echo "$(GREEN)🧪 Running all tests...$(NC)"
	$(VENV)/bin/pytest tests/ -v

test-unit: ## 🔬 Run unit tests only
	@echo "$(GREEN)🔬 Running unit tests...$(NC)"
	$(VENV)/bin/pytest tests/unit/ -v -m unit

test-integration: ## 🔗 Run integration tests only
	@echo "$(GREEN)🔗 Running integration tests...$(NC)"
	$(VENV)/bin/pytest tests/integration/ -v -m integration

test-cov: ## 📊 Run tests with coverage report
	@echo "$(GREEN)📊 Running tests with coverage...$(NC)"
	$(VENV)/bin/pytest tests/ -v --cov=src --cov-report=html --cov-report=term-missing
	@echo "$(BLUE)📋 Coverage report: htmlcov/index.html$(NC)"

test-paper: ## 🧾 Run paper trading tests
	$(VENV)/bin/pytest tests/ -v -m paper

test-watch: ## 👀 Run tests in watch mode
	$(VENV)/bin/pytest-watch tests/

##@ Application Commands
scan: ## 📊 Run market scan (Top 2~3 candidates)
	@echo "$(GREEN)📊 Running market scan...$(NC)"
	$(VENV)/bin/python -m src.app scan

run-paper: ## 🧾 Run paper trading mode (SAFE)
	@echo "$(GREEN)🧾 Starting paper trading mode...$(NC)"
	$(VENV)/bin/python -m src.app run --paper

run-live: ## ⚠️ Run live trading (REAL MONEY - CAUTION!)
	@echo "$(RED)⚠️  LIVE TRADING MODE - REAL MONEY AT RISK!$(NC)"
	@echo "$(YELLOW)Are you absolutely sure? [y/N]$(NC)"
	@read -r response; \
	if [ "$$response" = "y" ] || [ "$$response" = "Y" ]; then \
		echo "$(RED)🚨 Starting live trading...$(NC)"; \
		$(VENV)/bin/python -m src.app run --live; \
	else \
		echo "$(GREEN)✅ Live trading cancelled$(NC)"; \
	fi

backtest: ## 📈 Run backtest (default: last 30 days)
	@echo "$(GREEN)📈 Running backtest...$(NC)"
	$(VENV)/bin/python -m src.app backtest --start=2024-01-01 --end=2024-01-31

monitor: ## 👁️ Monitor running system (logs + metrics)
	@echo "$(GREEN)👁️ Starting system monitor...$(NC)"
	$(VENV)/bin/python -m src.app monitor

##@ Server Management (server.mdc compliance)
server-start: ## 🚀 Start all servers (with mandatory log checks)
	@echo "$(GREEN)🚀 Starting all servers...$(NC)"
	./scripts/server-manager.sh start

server-stop: ## 🛑 Stop all servers
	@echo "$(YELLOW)🛑 Stopping all servers...$(NC)"
	./scripts/server-manager.sh stop

server-restart: ## 🔄 Restart all servers
	@echo "$(GREEN)🔄 Restarting all servers...$(NC)"
	./scripts/server-manager.sh restart

server-status: ## 📋 Check server status
	./scripts/server-manager.sh status

server-logs: ## 📄 View server logs
	./scripts/server-manager.sh logs all

server-logs-trading: ## 📄 View trading logs
	./scripts/server-manager.sh logs backend

server-logs-error: ## 📄 View error logs
	./scripts/server-manager.sh logs error

##@ Docker Operations
docker-build: ## 🐳 Build Docker image
	@echo "$(GREEN)🐳 Building Docker image...$(NC)"
	docker build -t upbit-trading:latest .

docker-run-paper: ## 🐳 Run paper trading in Docker
	@echo "$(GREEN)🐳 Running paper trading in Docker...$(NC)"
	docker run --rm -it \
		-v $(PWD)/runtime:/app/runtime \
		-v $(PWD)/.env:/app/.env:ro \
		-v $(PWD)/configs:/app/configs:ro \
		upbit-trading:latest run --paper

docker-run-scan: ## 🐳 Run market scan in Docker
	@echo "$(GREEN)🐳 Running market scan in Docker...$(NC)"
	docker run --rm -it \
		-v $(PWD)/runtime:/app/runtime \
		-v $(PWD)/.env:/app/.env:ro \
		-v $(PWD)/configs:/app/configs:ro \
		upbit-trading:latest scan

docker-compose-up: ## 🐳 Start entire system with Docker Compose
	@echo "$(GREEN)🐳 Starting Docker Compose stack...$(NC)"
	docker-compose up -d

docker-compose-down: ## 🐳 Stop Docker Compose stack
	@echo "$(YELLOW)🐳 Stopping Docker Compose stack...$(NC)"
	docker-compose down

docker-compose-logs: ## 🐳 View Docker Compose logs
	docker-compose logs -f

##@ Data Management
backup: ## 💾 Backup trading data and configs
	@echo "$(GREEN)💾 Creating backup...$(NC)"
	./scripts/backup.sh

restore: ## 🔄 Restore from backup (specify BACKUP_FILE=filename)
	@echo "$(GREEN)🔄 Restoring from backup...$(NC)"
	@if [ -z "$(BACKUP_FILE)" ]; then \
		echo "$(RED)❌ Please specify BACKUP_FILE=filename$(NC)"; \
		exit 1; \
	fi
	./scripts/restore.sh $(BACKUP_FILE)

clean-logs: ## 🧹 Clean old log files (>30 days)
	@echo "$(GREEN)🧹 Cleaning old log files...$(NC)"
	find runtime/logs -name "*.log" -mtime +30 -delete
	find runtime/logs -name "*.log.*" -mtime +7 -delete
	@echo "$(GREEN)✅ Old logs cleaned$(NC)"

clean-reports: ## 🧹 Clean old report files (>90 days) 
	@echo "$(GREEN)🧹 Cleaning old report files...$(NC)"
	find runtime/reports -name "*.json" -mtime +90 -delete
	@echo "$(GREEN)✅ Old reports cleaned$(NC)"

##@ Deployment
deploy-staging: ## 🚀 Deploy to staging environment
	@echo "$(GREEN)🚀 Deploying to staging...$(NC)"
	./scripts/deploy.sh staging

deploy-prod: ## 🚀 Deploy to production environment
	@echo "$(RED)🚀 Deploying to production...$(NC)"
	@echo "$(YELLOW)Deploy to production? [y/N]$(NC)"
	@read -r response; \
	if [ "$$response" = "y" ] || [ "$$response" = "Y" ]; then \
		./scripts/deploy.sh production; \
	else \
		echo "$(GREEN)✅ Production deployment cancelled$(NC)"; \
	fi

##@ Utilities
clean: ## 🧹 Clean temporary files and caches
	@echo "$(GREEN)🧹 Cleaning temporary files...$(NC)"
	rm -rf __pycache__ .pytest_cache .coverage htmlcov .mypy_cache
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	@echo "$(GREEN)✅ Cleanup complete$(NC)"

requirements: ## 📝 Generate requirements.txt from current venv
	@echo "$(GREEN)📝 Generating requirements.txt...$(NC)"
	$(VENV)/bin/pip freeze > requirements.txt
	@echo "$(GREEN)✅ requirements.txt updated$(NC)"

check-deps: ## 🔍 Check for dependency vulnerabilities
	@echo "$(GREEN)🔍 Checking dependencies...$(NC)"
	$(VENV)/bin/pip audit
	$(VENV)/bin/safety check

update-deps: ## ⬆️ Update all dependencies (careful!)
	@echo "$(YELLOW)⬆️ Updating dependencies...$(NC)"
	$(VENV)/bin/pip install --upgrade pip setuptools wheel
	$(VENV)/bin/pip install -e .[dev] --upgrade

show-config: ## ⚙️ Show current configuration
	@echo "$(GREEN)⚙️ Current Configuration:$(NC)"
	@echo "Python: $$($(VENV)/bin/python --version)"
	@echo "Pip: $$($(VENV)/bin/pip --version)"
	@echo "Project: $$(cat pyproject.toml | grep '^name' | cut -d'"' -f2)"
	@echo "Version: $$(cat pyproject.toml | grep '^version' | cut -d'"' -f2)"
	@echo "Virtual Env: $(VENV)"
	@if [ -f .env ]; then echo "Environment: ✅ .env exists"; else echo "Environment: ❌ .env missing"; fi

##@ Development Workflow
dev-setup: setup pre-commit ## 🛠️ Complete development setup
	@echo "$(GREEN)✅ Development environment fully configured!$(NC)"
	@echo "$(BLUE)💡 Next steps:$(NC)"
	@echo "  1. Edit .env with your Upbit API keys"
	@echo "  2. Review configs/config.yaml"
	@echo "  3. Run: make scan"

quick-test: format test-unit ## ⚡ Quick development test cycle
	@echo "$(GREEN)⚡ Quick test cycle complete!$(NC)"

full-check: format lint security test-cov ## 🎯 Full quality assurance
	@echo "$(GREEN)🎯 Full quality check complete!$(NC)"

release-check: full-check docker-build ## 🎁 Pre-release validation
	@echo "$(GREEN)🎁 Release validation complete!$(NC)"

##@ Info
info: show-config ## ℹ️ Show project information
	@echo ""
	@echo "$(BLUE)📋 Available Commands:$(NC)"
	@echo "  Development: make dev-setup, make quick-test, make full-check"
	@echo "  Trading:     make scan, make run-paper, make backtest"  
	@echo "  Server:      make server-start, make server-status, make server-logs"
	@echo "  Docker:      make docker-build, make docker-run-paper"
	@echo "  Quality:     make format, make lint, make test"
	@echo ""
	@echo "$(YELLOW)⚠️  Safety First: Always test with --paper before live trading!$(NC)"

.PHONY: help setup install install-prod format lint security check pre-commit
.PHONY: test test-unit test-integration test-cov test-paper test-watch
.PHONY: scan run-paper run-live backtest monitor
.PHONY: server-start server-stop server-restart server-status server-logs
.PHONY: docker-build docker-run-paper docker-run-scan docker-compose-up docker-compose-down
.PHONY: backup restore clean-logs clean-reports deploy-staging deploy-prod
.PHONY: clean requirements check-deps update-deps show-config
.PHONY: dev-setup quick-test full-check release-check info
