# Two-minute demo script

**0:00–0:15 — Problem**

“A generated patch passing tests does not prove much when the tests are incomplete. PatchTrial
tests the evidence, not only the patch.”

**0:15–0:35 — Candidate**

Open the guided sample. Show the percentage-discount fix passing the original positive-price test.

**0:35–1:05 — Challenge**

Show the three semantic counterfeits: sign loss, zero-clamping, and skipping discounts for credits.
Explain that all are plausible mistakes and initially survive.

**1:05–1:30 — Strengthen**

Show the generated negative-credit regression test. Emphasize that PatchTrial permits only a
test-only strengthening patch and proves it still passes for the intended implementation.

**1:30–1:50 — Evidence**

Show 3/3 counterfeits caught, fault-category diversity, the final diff, and the downloadable proof.

**1:50–2:00 — Close**

“Ordinary agents ask whether their patch passes. PatchTrial asks whether the tests would notice if
the patch were wrong.”

Do not describe the guided sample as a DeepSeek/Qwen benchmark. For model claims, show the matrix
scorecard and corresponding raw proof JSON files.
