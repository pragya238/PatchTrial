# Evaluation plan

## Primary metrics

- Issue resolution rate on hidden tasks
- Existing and newly generated tests passed
- Valid counterfeits generated per task
- Counterfeit kill rate (`patch_survival_score`)
- Surviving counterfeits eliminated by evidence strengthening
- Model tokens, commands, and wall-clock time
- Repository restoration failures (target: zero)

## Baseline comparison

Run the same task/model pair twice: once stopping after candidate tests pass, and once through the
full PatchTrial workflow. Use seeded tasks containing boundary, lost-state, compatibility, and
partial-implementation traps. Report both correctness and overhead; do not claim safety gains from
counterfeit score alone.

## Required model matrix

Run every task with the same repository commit, task text, test command, evidence policy, and
temperature on both evaluator families:

| Variant | DeepSeek | Qwen |
|---|---:|---:|
| Candidate agent only (stop after tests pass) | required | required |
| Full PatchTrial challenge loop | required | required |

Use at least ten tasks covering Python and JavaScript and at least four fault families: boundary,
state, compatibility, validation/exception, and partial implementation. Keep raw proof JSON files;
aggregate them with `make scorecard REPORTS="..."`. Report failures and inconclusive runs rather
than rerunning only the unsuccessful samples.

## Claim discipline

- `patch_survival_score` is a kill rate, not a probability that code is correct.
- `evidence_confidence` discounts a perfect kill rate when quantity or diversity is insufficient.
- Do not publish DeepSeek/Qwen success numbers until the corresponding proof files exist.
- Compare correctness and overhead against the candidate-only baseline.
- A restoration failure is a release blocker.

## Clean-environment protocol

```bash
git clone <submission>
cd <submission>
make setup
make test
make demo

export AI_API_KEY="<provided>"
export AI_BASE_URL="<provided>"
export AI_MODEL="<provided>"
export AI_PROVIDER="<deepseek-or-qwen>"
export TARGET_REPO="/path/to/clean/target"
export TASK_FILE="/path/to/issue.txt"
make run
```

The target must start clean. Preserve the final target diff and `patchtrial-proof.json` as the run
artifacts.

For every run, record the harness commit, target baseline commit, model name, endpoint family,
verdict, hidden-test result when available, tokens, command runtime, valid/invalid trials, category
diversity, and whether evidence strengthening changed the outcome.
