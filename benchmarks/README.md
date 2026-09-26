# PatchTrial benchmark suite

This directory contains ten intentionally small repositories: five Python and five JavaScript.
They cover boundary, state, validation, compatibility, and partial-implementation faults.

Each starter repository passes its visible tests and fails at least one withheld correctness test.
The hidden files are kept outside the prepared repository until the harness run finishes.

```bash
make eval-smoke
python -m patchtrial.benchmark list
python -m patchtrial.benchmark prepare py-negative-discount /tmp/patchtrial-task
```

For a genuine model comparison, configure one evaluator family at a time and run:

```bash
export AI_PROVIDER=deepseek
export AI_API_KEY="..."
export AI_BASE_URL="..."
export AI_MODEL="..."
make eval-matrix
```

Repeat with Qwen. Raw reports and the aggregate scorecard are written below
`evaluation-results/`. Never commit credentials. Do not describe fixture validation as a real
model benchmark; only reports produced with the named provider constitute model evidence.
