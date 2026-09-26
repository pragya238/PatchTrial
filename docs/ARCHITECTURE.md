# PatchTrial architecture

PatchTrial separates model judgment from executable evidence.

```text
Task + clean Git repository
          |
          v
Repository map -> constrained implementation loop -> candidate diff
                                                    |
                                                    v
                                             final test command
                                                    |
                                                    v
                                      semantic counterfeit generator
                                                    |
                                     baseline <-> isolated patch trials
                                                    |
                              +---------------------+------------------+
                              |                                        |
                         all killed                              survivor found
                              |                                        |
                           accept                         test-only strengthening
                                                                       |
                                                        correct passes / wrong fails
                                                                       |
                                                                    accept
```

## Trust boundaries

The model proposes actions; the harness validates and executes them. Paths cannot escape the
repository, edits must be valid Git diffs, commands do not use a shell, executables are allowlisted,
and repository processes do not receive `AI_API_KEY`. Patch trials require a clean Git baseline so
every temporary state can be reversed exactly.

## Model portability

`ModelClient` uses the common chat-completions HTTP contract and has no provider SDK dependency.
The action protocol is JSON embedded in ordinary text rather than native function calling, avoiding
provider-specific tool schemas. Model, endpoint, context budget, step budget, and timeouts are all
runtime configuration.

## Acceptance semantics

Passing candidate tests is necessary but insufficient. `ACCEPTED` requires zero surviving valid
counterfeits plus a configurable minimum quantity and fault-category diversity (defaults: three
valid counterfeits across two categories). Invalid generated patches are excluded, never counted
as detected. When tests are strengthened, only recognized test paths may change. Kill rate and
evidence confidence are reported separately.

## Failure atomicity

The clean Git commit is a transaction boundary. Any unexpected model, protocol, command, or patch
failure restores tracked and untracked changes to that boundary. CLI runs also restore completed
but non-accepted candidates. Only a fully `ACCEPTED` candidate is intentionally left in place.

## Proof chain

The machine-readable report binds the result to a baseline commit and candidate-diff SHA-256. It
records model configuration, evidence thresholds, test outputs, command timings, trials, categories,
tokens, and strengthening decisions without recording the API credential.
