.PHONY: setup run test clean demo

PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

setup:
	$(PYTHON) -m venv $(VENV)
	@echo "PatchTrial uses only the Python standard library; no packages to download."

run:
	@test -n "$(AI_API_KEY)" || (echo "AI_API_KEY is required" && exit 1)
	$(BIN)/python -m patchtrial.cli

test:
	$(BIN)/python -m unittest discover -s tests -v

demo:
	$(BIN)/python -m patchtrial.demo

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache *.egg-info patchtrial.egg-info
