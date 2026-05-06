.PHONY: help run format check test evals reset-db
.DEFAULT_GOAL := help

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

run: ## Start both dev servers (ticketing on :8000, pms-status on :8001)
	@uv run uvicorn src.pms_status_app:app --port 8001 --reload & \
	PMS_PID=$$!; \
	trap "kill $$PMS_PID 2>/dev/null" INT TERM; \
	uv run uvicorn src.main:app --port 8000 --reload; \
	kill $$PMS_PID 2>/dev/null; \
	wait $$PMS_PID 2>/dev/null || true

format: ## Format code + sort imports
	uv run ruff check --fix --select I src/ tests/ evals/
	uv run ruff format src/ tests/ evals/

check: ## Lint + format check
	uv run ruff check src/ tests/ evals/
	uv run ruff format --check src/ tests/ evals/

test: ## Run smoke tests
	uv run pytest tests/ -v

evals: ## Run offline evals (MODEL=openai:gpt-4o-mini TAG=new-prompt to override)
	MODEL_NAME=$(or $(MODEL),$(MODEL_NAME),openai:gpt-4o) uv run python -m evals.run_evals $(if $(TAG),--tag $(TAG))

reset-db: ## Reset database (confirms first, re-seeds on next run)
	@echo "This will delete the database and all submitted tickets."
	@read -p "Are you sure? [y/N] " confirm && [ "$$confirm" = "y" ] || (echo "Aborted." && exit 1)
	rm -f data/tickets.db
	@echo "Database deleted. Restart the app to re-seed."
