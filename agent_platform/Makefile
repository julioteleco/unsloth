.PHONY: install lint typecheck test demo demo-licitacion demo-evaluacion \
	demo-persistencia demo-juicio-valor demo-notion check

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

demo-persistencia:
	$(PYTHON) examples/persistencia_demo.py

demo-juicio-valor:
	$(PYTHON) examples/juicio_valor_demo.py

demo-notion:
	$(PYTHON) examples/notion_store_demo.py

check: lint typecheck test
