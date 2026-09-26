# PatchTrial

PatchTrial is a model-agnostic autonomous coding harness that **puts generated patches on
trial**. A candidate is not accepted merely because the repository tests pass. PatchTrial asks
the model to construct plausible but incorrect alternatives, runs the same tests against each
one, and reports whether the test evidence can distinguish the intended solution from those
counterfeits.

> Ordinary agents ask whether their patch passes. PatchTrial asks whether the tests would notice
> if the patch were wrong.

## Current MVP

The MVP implements the full first-pass workflow:

1. Map an unfamiliar repository.
2. Use a constrained JSON tool protocol to investigate the issue.
3. Encourage reproduction before implementation.
4. Apply changes only through validated Git unified diffs.
5. Run the repository's final verification command.
6. Generate issue-specific counterfeit patches.
7. Restore the baseline and run every counterfeit in isolation.
8. Ask for a focused test-only patch when a counterfeit survives.
9. Verify the stronger test against both the correct and counterfeit implementations.
10. Restore the strengthened correct candidate and write `patchtrial-proof.json`.

For weaker or inexpensive models, the implementation loop also exposes exact-text replacement and
safe new-file creation tools. Malformed diff hunk counts are repaired automatically, repeated bad
patch attempts are cut off, and failed live runs restore the repository to its clean starting state.
This keeps provider quirks from turning into corrupted worktrees or endless retry loops.

The harness uses an OpenAI-compatible chat-completions transport without an SDK. This keeps it
portable across DeepSeek, Qwen, and compatible evaluation gateways.

Reproduction is evidence-backed: the model cannot mark a bug reproduced unless the immediately
preceding repository command actually failed, and no production-code edits are present at that
point. A newly added failing regression test is allowed.

## Setup

Requirements: Python 3.10+ and Git.

```bash
make setup
```

No third-party runtime packages are required.

## Configuration

The API key is always read from the environment and must never be committed.

```bash
export AI_API_KEY="..."
export AI_BASE_URL="https://api.deepseek.com/v1"
export AI_MODEL="deepseek-chat"
```

For a Qwen-compatible gateway, change `AI_BASE_URL` and `AI_MODEL` to values supplied by the
organizers. `AI_API_KEY` is the only secret.

The local workspace also includes presets for OpenRouter, Groq Cloud, and Google Gemini. All use
their official OpenAI-compatible chat-completions endpoints, so no provider SDK is required.
Choose a provider under **Configure model locally**, paste its API key, and review the editable
base URL and model before saving. Provider free tiers, quotas, and model availability are managed
by the providers and may change.

Optional controls:

| Variable | Default | Meaning |
|---|---:|---|
| `PATCHTRIAL_MAX_STEPS` | 24 | Maximum implementation actions |
| `PATCHTRIAL_MAX_COUNTERFEITS` | 5 | Maximum adversarial patches |
| `PATCHTRIAL_API_TIMEOUT` | 120 | Model request timeout in seconds |
| `PATCHTRIAL_COMMAND_TIMEOUT` | 180 | Tool command timeout in seconds |
| `PATCHTRIAL_MAX_OUTPUT_CHARS` | 16000 | Per-command context limit |
| `PATCHTRIAL_CONTEXT_CHARS` | 80000 | Approximate conversation-history budget |

Evaluation input can also be supplied without changing `make run`:

| Variable | Meaning |
|---|---|
| `TARGET_REPO` | Repository PatchTrial should modify |
| `TASK_TEXT` | Issue text supplied directly |
| `TASK_FILE` | Path to a file containing the issue |
| `TEST_COMMAND` | Final verification command; otherwise auto-detected |
| `PATCHTRIAL_REPORT` | Optional proof-report output path |

## Run

The target must be a clean Git repository. This is required because PatchTrial temporarily
reverses and reapplies patches during adversarial trials.

For the visual interface:

```bash
export AI_API_KEY="..."
export AI_BASE_URL="..."
export AI_MODEL="..."
make ui
```

Then open `http://127.0.0.1:8765`. The guided demo needs no API key; the live workspace uses the
configured model and displays progress, evidence strength, counterfeit results, and the final diff.

```bash
export AI_API_KEY="..."
export TARGET_REPO="/path/to/target-repository"
export TASK_FILE="/path/to/issue.txt"
make run
```

`make run` accepts task text interactively or from stdin. For explicit options:

```bash
.venv/bin/python -m patchtrial.cli \
  --repo /path/to/target-repository \
  --task-file /path/to/issue.txt \
  --test-command "pytest -q"
```

You may also pass `--task "Fix ..."`. If `--test-command` is omitted, PatchTrial attempts to
detect the project type. Validate local configuration without an API call using:

```bash
.venv/bin/python -m patchtrial.cli --repo /path/to/repository --task "Example" --dry-run
```

## Verdicts

- `ACCEPTED`: candidate tests pass and every valid counterfeit is detected.
- `NEEDS_STRONGER_TESTS`: at least one plausible counterfeit survives.
- `REJECTED_CANDIDATE_TESTS_FAILED`: the proposed solution fails final verification.
- `INCONCLUSIVE_NO_VALID_COUNTERFEITS`: the adversarial patches could not be evaluated.

Invalid counterfeits—patches that do not apply—are excluded rather than being falsely counted as
detected.

## Security boundaries

- Repository paths are resolved and prevented from escaping the target root.
- Model commands are parsed without a shell and restricted to an executable allowlist.
- File modifications must be complete Git unified diffs and pass `git apply --check`.
- Tool output is truncated before being returned to the model.
- The API credential is never inserted into prompts or command arguments.

The allowlist is a safety layer, not a complete hostile-code sandbox. Repository tests can execute
repository code, so official evaluation should still use an isolated environment.

## Test

```bash
make test
```

Before evaluation, run the preflight checker against the clean target repository:

```bash
TARGET_REPO=/path/to/target make doctor
```

After several evaluation runs, aggregate their proof artifacts:

```bash
make scorecard REPORTS="run-1.json run-2.json run-3.json"
```

## Evidence strengthening

When a valid counterfeit survives, PatchTrial gives the model the failure hypothesis, candidate
diff, trial output, and a bounded view of the repository's tests. The returned patch is accepted
only when every changed path is recognizably a test file. PatchTrial then proves that the new test
passes for the correct candidate and reruns the survivor. Production-code changes are rejected
during this phase.
