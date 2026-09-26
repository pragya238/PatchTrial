.PHONY: setup run ui doctor scorecard test verify clean demo eval-smoke eval-candidate eval-patchtrial eval-matrix judge

PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin
EVAL_OUTPUT ?= evaluation-results/$(AI_PROVIDER)-$(AI_MODEL)

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

eval-smoke:
	$(BIN)/python -m patchtrial.benchmark validate

eval-candidate:
	@test -n "$(AI_API_KEY)" || (echo "AI_API_KEY is required" && exit 1)
	$(BIN)/python -m patchtrial.benchmark matrix --variant candidate-only --output "$(EVAL_OUTPUT)/candidate-only"

eval-patchtrial:
	@test -n "$(AI_API_KEY)" || (echo "AI_API_KEY is required" && exit 1)
	$(BIN)/python -m patchtrial.benchmark matrix --variant patchtrial --output "$(EVAL_OUTPUT)/patchtrial"

eval-matrix: eval-candidate eval-patchtrial
	@reports="$$(find "$(EVAL_OUTPUT)" -name '*.json' ! -name 'scorecard.json' -type f)"; \
	test -n "$$reports" || (echo "No proof reports found" && exit 1); \
	$(BIN)/python -m patchtrial.scorecard $$reports --json > "$(EVAL_OUTPUT)/scorecard.json"; \
	$(BIN)/python -m patchtrial.scorecard $$reports

judge: verify eval-smoke
	@echo "Judge preflight passed: tests, deterministic demo, and 10-task benchmark fixtures are ready."

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache *.egg-info patchtrial.egg-info
