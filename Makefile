VENV_PYTHON := .venv/bin/python
PYTHON ?= $(if $(wildcard $(VENV_PYTHON)),$(VENV_PYTHON),python3)
BLACK ?= $(PYTHON) -m black
COVERAGE ?= $(PYTHON) -m coverage
MYPY ?= $(PYTHON) -m mypy
RUFF ?= $(PYTHON) -m ruff

HEADLESS_TEST_ENV ?= QT_QPA_PLATFORM=offscreen CI=1 PYTHONUNBUFFERED=1

CHECK_PATHS = ISRC_manager.py build.py isrc_manager scripts tests

.PHONY: all-checks check fix compile lint format black format-check type-check test coverage

all-checks: fix type-check coverage

fix: lint format

black: format

check: compile
	$(RUFF) check $(CHECK_PATHS)
	$(BLACK) --check $(CHECK_PATHS)
	$(MYPY)
	$(HEADLESS_TEST_ENV) $(COVERAGE) erase
	$(HEADLESS_TEST_ENV) $(COVERAGE) run -m unittest discover -s tests -p 'test_*.py'
	$(HEADLESS_TEST_ENV) $(COVERAGE) report
	$(HEADLESS_TEST_ENV) $(COVERAGE) xml

compile:
	$(PYTHON) -m py_compile ISRC_manager.py build.py icon_factory.py
	$(PYTHON) -m py_compile $$(find isrc_manager -name '*.py' | sort)
	$(PYTHON) -m py_compile $$(find scripts -name '*.py' | sort)
	$(PYTHON) -m py_compile $$(find tests -name '*.py' | sort)

lint:
	$(RUFF) check $(CHECK_PATHS) --fix

format:
	$(BLACK) $(CHECK_PATHS)

format-check:
	$(BLACK) --check $(CHECK_PATHS)

type-check:
	$(MYPY)

test:
	$(HEADLESS_TEST_ENV) $(PYTHON) -m unittest discover -s tests -p 'test_*.py'

coverage:
	$(HEADLESS_TEST_ENV) $(COVERAGE) erase
	$(HEADLESS_TEST_ENV) $(COVERAGE) run -m unittest discover -s tests -p 'test_*.py'
	$(HEADLESS_TEST_ENV) $(COVERAGE) report
	$(HEADLESS_TEST_ENV) $(COVERAGE) xml
