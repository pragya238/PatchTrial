from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path


@dataclass
class TrialResult:
    name: str
    hypothesis: str
    valid: bool
    killed: bool
    test_returncode: int | None
    detail: str = ""


@dataclass
class ProofReport:
    task: str
    model: str
    test_command: str
    candidate_tests_passed: bool = False
    baseline_reproduced: bool = False
    trials: list[TrialResult] = field(default_factory=list)
    initial_survivors: int = 0
    strengthening_attempted: bool = False
    strengthening_applied: bool = False
    strengthening_changed_files: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    verdict: str = "INCOMPLETE"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def valid_trials(self) -> int:
        return sum(trial.valid for trial in self.trials)

    @property
    def killed_trials(self) -> int:
        return sum(trial.valid and trial.killed for trial in self.trials)

    @property
    def survival_score(self) -> float:
        if self.valid_trials == 0:
            return 0.0
        return 100.0 * self.killed_trials / self.valid_trials

    def write(self, path: Path) -> None:
        payload = asdict(self)
        payload["valid_trials"] = self.valid_trials
        payload["killed_trials"] = self.killed_trials
        payload["patch_survival_score"] = self.survival_score
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def summary(self) -> str:
        return (
            "\nPATCH TRIAL VERDICT\n"
            f"  Candidate tests:      {'PASS' if self.candidate_tests_passed else 'FAIL'}\n"
            f"  Valid counterfeits:   {self.valid_trials}\n"
            f"  Counterfeits killed:  {self.killed_trials}\n"
            f"  Initially survived:   {self.initial_survivors}\n"
            f"  Evidence strengthened:{' yes' if self.strengthening_applied else ' no'}\n"
            f"  Evidence strength:    {self.survival_score:.0f}%\n"
            f"  Verdict:              {self.verdict}\n"
        )
