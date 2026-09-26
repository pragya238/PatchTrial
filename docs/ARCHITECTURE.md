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

Passing candidate tests is necessary but insufficient. `ACCEPTED` requires at least one valid
counterfeit and zero surviving valid counterfeits. Invalid generated patches are excluded, never
counted as detected. When tests are strengthened, only recognized test paths may change.
