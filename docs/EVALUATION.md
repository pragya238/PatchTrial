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
export TARGET_REPO="/path/to/clean/target"
export TASK_FILE="/path/to/issue.txt"
make run
```

The target must start clean. Preserve the final target diff and `patchtrial-proof.json` as the run
artifacts.
