PYTHON ?= python
VENV ?= .venv

.PHONY: help venv install run test clean

help:
	@echo "Targets:"
	@echo "  venv    - create virtual environment"
	@echo "  install - install project in editable mode"
	@echo "  run     - run CLI (QUERY=\"...\")"
	@echo "  test    - run unit tests"
	@echo "  clean   - remove build artifacts"

venv:
	$(PYTHON) -m venv $(VENV)

install:
	$(VENV)/bin/pip install -e .

run:
	$(VENV)/bin/python main_cli.py

test:
	$(VENV)/bin/python -m unittest

clean:
	rm -rf build dist *.egg-info __pycache__
