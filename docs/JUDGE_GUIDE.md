# Judge guide

## Thirty-second summary

Ordinary coding agents stop when their patch passes. PatchTrial asks a harder question: would the
same tests reject believable wrong patches? It generates semantic counterfeits, executes them in
isolation, strengthens weak tests, and produces a hash-bound proof report.

## One-command preflight

```bash
git clone https://github.com/pragya238/PatchTrial.git
cd PatchTrial
make setup
make judge
```

This runs the unit and integration suite, deterministic end-to-end demo, and validates all ten
benchmark fixtures without making a model request.

## Visual demonstration

- Guided demo: https://pragya238.github.io/PatchTrial/
- Live workspace: https://pragya238.github.io/PatchTrial/live.html
- Use **Run guided sample — no API key** to see the full evidence loop without credits.

## Evaluator model run

```bash
export AI_API_KEY="<provided>"
export AI_BASE_URL="<provided>"
export AI_MODEL="<provided>"
export AI_PROVIDER="deepseek"  # or qwen
make eval-matrix
```

The matrix runs the same ten tasks in candidate-only and full PatchTrial modes. It preserves raw
proof reports, executes withheld tests after each run, and writes a grouped scorecard.

## What to inspect

1. `patchtrial-proof.json` for the candidate hash, commands, counterfeits, categories and verdict.
2. `evaluation-results/.../scorecard.json` for hidden-test and evidence metrics.
3. A failed or inconclusive run: PatchTrial restores the target instead of presenting weak
   evidence as success.

## Honest boundary

The no-key web path is a guided sample, not a model-performance claim. Real DeepSeek/Qwen claims
must be backed by the raw proof files produced by the evaluator matrix.
