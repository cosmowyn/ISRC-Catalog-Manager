PYTHON ?= python3
BLACK ?= $(PYTHON) -m black
COVERAGE ?= $(PYTHON) -m coverage
MYPY ?= $(PYTHON) -m mypy
RUFF ?= $(PYTHON) -m ruff

CHECK_PATHS = build.py isrc_manager tests

.PHONY: all-checks check fix compile lint format format-check type-check test coverage

all-checks: fix type-check coverage

fix: lint format

check: compile
	$(RUFF) check $(CHECK_PATHS)
	$(BLACK) --check $(CHECK_PATHS)
	$(MYPY)
	$(COVERAGE) erase
	$(COVERAGE) run -m unittest discover -s tests -p 'test_*.py'
	$(COVERAGE) report
	$(COVERAGE) xml

compile:
	$(PYTHON) -m py_compile ISRC_manager.py build.py icon_factory.py
	$(PYTHON) -m py_compile $$(find isrc_manager -name '*.py' | sort)
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
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py'

coverage:
	$(COVERAGE) erase
	$(COVERAGE) run -m unittest discover -s tests -p 'test_*.py'
	$(COVERAGE) report
	$(COVERAGE) xml