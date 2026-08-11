.PHONY: install test lint format typecheck check changelog-draft changelog build clean

install:
	uv sync --all-extras

test:
	uv sync --all-extras --reinstall-package summonpot
	uv run pytest tests/ -v

lint:
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/

typecheck:
	uv run pyright src/ tests/

format:
	uv run ruff check --fix src/ tests/
	uv run ruff format src/ tests/

check: lint typecheck test

changelog-draft:
	uv run towncrier build --draft --version $$(uv version --short)

changelog:
	uv run towncrier build --yes --version $$(uv version --short)

build:
	uv build

clean:
	rm -rf dist/ build/ *.egg-info .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +