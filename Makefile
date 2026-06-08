.PHONY: help run format check test evals bt-evals load reset-db
.DEFAULT_GOAL := help

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

run: ## Start both dev servers (support agent on :8000, service-status on :8001)
	@uv run uvicorn src.status_service_app:app --port 8001 --reload & \
	STATUS_PID=$$!; \
	trap "kill $$STATUS_PID 2>/dev/null" INT TERM; \
	uv run uvicorn src.main:app --port 8000 --reload; \
	kill $$STATUS_PID 2>/dev/null; \
	wait $$STATUS_PID 2>/dev/null || true

format: ## Format code + sort imports
	uv run ruff check --fix --select I src/ tests/ evals/
	uv run ruff format src/ tests/ evals/

check: ## Lint + format check
	uv run ruff check src/ tests/ evals/
	uv run ruff format --check src/ tests/ evals/

test: ## Run smoke tests
	uv run pytest tests/ -v

evals: ## Run evals (SOURCE=static|curated|both, MODEL=..., TAG=...). Default: static — curated requires the Logfire dataset named in evals/curated.py to exist.
	MODEL_NAME=$(or $(MODEL),$(MODEL_NAME),gpt-4o) uv run python -m evals.run_evals --source $(or $(SOURCE),static) $(if $(TAG),--tag $(TAG))

bt-evals: ## Run the Braintrust eval (MODEL=... overrides .env). Logs an experiment named static-<model>. Needs BRAINTRUST_API_KEY in .env.
	$(if $(MODEL),MODEL_NAME=$(MODEL)) uv run --env-file .env braintrust eval evals/braintrust_eval.py

push-curated: ## Push the local static dataset to Logfire as the curated dataset (NAME=... to override)
	uv run python -m evals.push_curated $(if $(NAME),--name $(NAME))

load: ## Generate N agent runs across prompt variants for Braintrust classification (TOTAL=200 CONCURRENCY=4 VARIANTS=baseline,strict MODEL=...)
	$(if $(MODEL),MODEL_NAME=$(MODEL)) uv run python -m evals.load --total $(or $(TOTAL),200) --concurrency $(or $(CONCURRENCY),4) $(if $(VARIANTS),--variants $(VARIANTS))

reset-db: ## Reset database (confirms first, re-seeds on next run)
	@echo "This will delete the database and all submitted tickets."
	@read -p "Are you sure? [y/N] " confirm && [ "$$confirm" = "y" ] || (echo "Aborted." && exit 1)
	rm -f data/tickets.db
	@echo "Database deleted. Restart the app to re-seed."
