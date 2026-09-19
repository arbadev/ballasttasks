.DEFAULT_GOAL := help
.PHONY: help up down test test-api test-web test-integration lint lint-api lint-web

API_DIR := apps/api
WEB_DIR := apps/web
# Official uv image, used only to run the integration tests inside the compose network.
UV_IMAGE := ghcr.io/astral-sh/uv:python3.14-trixie-slim

help: ## Show the available targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-17s %s\n", $$1, $$2}'

up: ## Build and start the whole system (db, redis, api, worker, web)
	docker compose up --build

down: ## Stop the whole system
	docker compose down

test: test-api test-web ## Run every test suite with coverage

test-api: ## Run the API tests with coverage
	cd $(API_DIR) && uv run pytest --cov

test-web: ## Run the web tests with coverage
	cd $(WEB_DIR) && npm run test -- --coverage

test-integration: ## Run the API integration tests against the running compose stack (`make up` first)
	docker run --rm \
		--network "$$(docker inspect --format '{{range $$k, $$v := .NetworkSettings.Networks}}{{$$k}}{{end}}' "$$(docker compose ps -q api)")" \
		-e DATABASE__URL="$$(docker compose exec -T api printenv DATABASE__URL)" \
		-e REDIS__URL="$$(docker compose exec -T api printenv REDIS__URL)" \
		-e AUTH__JWT_SECRET="$$(docker compose exec -T api printenv AUTH__JWT_SECRET)" \
		-e UV_PROJECT_ENVIRONMENT=/tmp/venv -e UV_LINK_MODE=copy \
		-v "$(CURDIR)/$(API_DIR):/work:ro" -w /work \
		$(UV_IMAGE) uv run --frozen pytest -m integration -p no:cacheprovider

lint: lint-api lint-web ## Run every linter, type checker and import contract

lint-api: ## ruff, mypy and import-linter on the API
	cd $(API_DIR) && uv run ruff check .
	cd $(API_DIR) && uv run ruff format --check .
	cd $(API_DIR) && uv run mypy .
	cd $(API_DIR) && uv run lint-imports

lint-web: ## ESLint and the TypeScript compiler on the web app
	cd $(WEB_DIR) && npm run lint
	cd $(WEB_DIR) && npx tsc --noEmit
