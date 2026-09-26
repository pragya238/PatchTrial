.PHONY: setup run ui doctor scorecard test verify clean demo

PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

setup:
	@command -v git >/dev/null || (echo "Git is required" && exit 1)
	@$(PYTHON) -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ is required"'
	$(PYTHON) -m venv $(VENV)
	@echo "PatchTrial uses only the Python standard library; no packages to download."

run:
	@test -n "$(AI_API_KEY)" || (echo "AI_API_KEY is required" && exit 1)
	$(BIN)/python -m patchtrial.cli

ui:
	$(BIN)/python -m patchtrial.web

doctor:
	$(BIN)/python -m patchtrial.doctor

scorecard:
	@test -n "$(REPORTS)" || (echo "Usage: make scorecard REPORTS='proof1.json proof2.json'" && exit 1)
	$(BIN)/python -m patchtrial.scorecard $(REPORTS)

test:
	$(BIN)/python -m unittest discover -s tests -v

verify: test demo
	@echo "PatchTrial verification passed."

demo:
	$(BIN)/python -m patchtrial.demo

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache *.egg-info patchtrial.egg-info
