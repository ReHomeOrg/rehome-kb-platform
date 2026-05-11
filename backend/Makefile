.PHONY: install lint format typecheck test test-cov run clean

install:
	pip install -r requirements-dev.txt

lint:
	ruff check src tests
	ruff format --check src tests

format:
	ruff format src tests
	ruff check --fix src tests

typecheck:
	mypy --strict src tests

test:
	pytest

test-cov:
	pytest --cov=src --cov-report=term-missing --cov-fail-under=80

run:
	uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
