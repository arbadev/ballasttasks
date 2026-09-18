.DEFAULT_GOAL := help
.PHONY: help up down test test-api test-web lint lint-api lint-web

API_DIR := apps/api
WEB_DIR := apps/web

help: ## Show the available targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

up: ## Build and start the whole system (db, redis, api, worker, web)
	docker compose up --build

down: ## Stop the whole system
	docker compose down

test: test-api test-web ## Run every test suite with coverage

test-api: ## Run the API tests with coverage
	cd $(API_DIR) && uv run pytest --cov

test-web: ## Run the web tests with coverage
	cd $(WEB_DIR) && npm run test -- --coverage

lint: lint-api lint-web ## Run every linter, type checker and import contract

lint-api: ## ruff, mypy and import-linter on the API
	cd $(API_DIR) && uv run ruff check .
	cd $(API_DIR) && uv run ruff format --check .
	cd $(API_DIR) && uv run mypy .
	cd $(API_DIR) && uv run lint-imports

lint-web: ## ESLint and the TypeScript compiler on the web app
	cd $(WEB_DIR) && npm run lint
	cd $(WEB_DIR) && npx tsc --noEmit
