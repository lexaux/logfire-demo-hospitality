.PHONY: help run format check test reset-db
.DEFAULT_GOAL := help

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

run: ## Start the dev server
	uv run uvicorn src.main:app --reload

format: ## Format code + sort imports
	uv run ruff check --fix --select I src/ tests/ evals/
	uv run ruff format src/ tests/ evals/

check: ## Lint + format check
	uv run ruff check src/ tests/ evals/
	uv run ruff format --check src/ tests/ evals/

test: ## Run smoke tests
	uv run pytest tests/ -v

reset-db: ## Reset database (confirms first, re-seeds on next run)
	@echo "This will delete the database and all submitted tickets."
	@read -p "Are you sure? [y/N] " confirm && [ "$$confirm" = "y" ] || (echo "Aborted." && exit 1)
	rm -f data/tickets.db
	@echo "Database deleted. Restart the app to re-seed."
