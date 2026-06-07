.PHONY: install lint typecheck test demo demo-licitacion demo-evaluacion check

PYTHON ?= python3

install:
	$(PYTHON) -m pip install -e ".[dev]"

lint:
	$(PYTHON) -m ruff check src tests examples

typecheck:
	$(PYTHON) -m mypy
	$(PYTHON) -m mypy --strict tests examples

test:
	$(PYTHON) -m pytest -q

demo:
	$(PYTHON) examples/demo.py

demo-licitacion:
	$(PYTHON) examples/licitacion_demo.py

demo-evaluacion:
	$(PYTHON) examples/evaluacion_demo.py

check: lint typecheck test
