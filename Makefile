.PHONY: help sync refresh site-dev site-build eval lint test clean

help:
	@echo "Targets:"
	@echo "  sync        Install Python deps via uv"
	@echo "  refresh     Run the full pipeline (writes ./out/)"
	@echo "  site-dev    Run the Vite dev server against ./out/dashboard.json"
	@echo "  site-build  Production-build the dashboard to site/dist/"
	@echo "  eval        Run filter/cluster evals against fixtures"
	@echo "  lint        ruff + pyright + tsc --noEmit"
	@echo "  test        Run pytest"
	@echo "  clean       Remove .cache/, out/, and build artifacts"

sync:
	uv sync --extra dev

refresh:
	uv run python -m pipeline.main --since 7d

site-dev:
	cd site && npm install && npm run dev

site-build:
	cd site && npm install && npm run build

eval:
	uv run pytest pipeline/eval -v

lint:
	uv run ruff check pipeline
	uv run pyright pipeline
	cd site && npx tsc --noEmit

test:
	uv run pytest

clean:
	rm -rf .cache out site/dist site/node_modules
	find . -type d -name __pycache__ -exec rm -rf {} +
