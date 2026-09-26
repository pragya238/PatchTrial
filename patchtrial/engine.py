from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Callable

from .config import Config
from .model import ModelClient, ModelResponse
from .prompts import SYSTEM_PROMPT, counterfeit_prompt, strengthening_prompt, task_prompt
from .protocol import ProtocolError, parse_action, parse_json_object
from .report import ProofReport, TrialResult
from .repository import CommandResult, Repository, RepositoryError


TOOLS = {
    "list_files", "search_code", "read_file", "replace_text", "create_file", "apply_patch", "run_command",
    "inspect_diff", "repository_status", "record_reproduction", "finish",
}


@dataclass
class RunResult:
    report: ProofReport
    report_path: Path
    candidate_diff: str


class PatchTrialEngine:
    def __init__(
        self,
        config: Config,
        repository: Repository,
        model: ModelClient,
        *,
        test_command: str,
        event: Callable[[str], None] = print,
    ):
        self.config = config
        self.repository = repository
        self.model = model
        self.test_command = test_command
        self.event = event
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.reproduction_recorded = False
        self.last_command_result: CommandResult | None = None
        self.patch_failures = 0

    def run(self, task: str, report_path: Path) -> RunResult:
        initial_status = self.repository.status().strip()
        if initial_status:
            raise RepositoryError(
                "target repository must start clean so patch trials can restore it safely; "
                f"current status:\n{initial_status}"
            )

        report = ProofReport(task=task, model=self.config.model, test_command=self.test_command)
        self.event("[1/5] Mapping repository")
        repository_map = self.repository.list_files(limit=250)

        self.event("[2/5] Reproducing issue and building candidate patch")
        self._build_candidate(task, repository_map)
        candidate_diff = self.repository.diff()
        if not candidate_diff.strip():
            raise RepositoryError("agent finished without producing a patch")

        report.baseline_reproduced = self.reproduction_recorded
        report.changed_files = _changed_files(candidate_diff)

        self.event("[3/5] Verifying candidate")
        candidate_test = self.repository.run_command(self.test_command)
        report.candidate_tests_passed = candidate_test.ok
        if not candidate_test.ok:
            report.verdict = "REJECTED_CANDIDATE_TESTS_FAILED"
            self._finalize_report(report, report_path)
            return RunResult(report, report_path, candidate_diff)

        self.event("[4/5] Generating and challenging counterfeit patches")
        counterfeits = self._generate_counterfeits(task, candidate_diff)
        report.trials = self._run_trials(candidate_diff, counterfeits)

        survivors = [trial for trial in report.trials if trial.valid and not trial.killed]
        report.initial_survivors = len(survivors)
        if survivors:
            report.strengthening_attempted = True
            self.event(f"  {len(survivors)} counterfeit(s) survived; strengthening evidence")
            strengthening_patch = self._generate_strengthening_patch(task, candidate_diff, survivors)
            if strengthening_patch:
                strengthened = self.repository.apply_patch(strengthening_patch)
                if strengthened.ok:
                    verified = self.repository.run_command(self.test_command)
                    if verified.ok:
                        report.strengthening_applied = True
                        report.strengthening_changed_files = _changed_files(strengthening_patch)
                        report.trials = self._rerun_survivors(
                            counterfeits,
                            report.trials,
                        )
                        candidate_diff = self.repository.diff()
                        report.changed_files = _changed_files(candidate_diff)
                    else:
                        self.event("  stronger test rejected: it fails for the correct candidate")
                        removed = self.repository.apply_patch(strengthening_patch, reverse=True)
                        if not removed.ok:
                            raise RepositoryError("could not remove rejected strengthening patch")
                else:
                    self.event(
                        "  stronger test patch did not apply cleanly: "
                        + (strengthened.stderr or strengthened.stdout).strip()
                    )

        if report.valid_trials == 0:
            report.verdict = "INCONCLUSIVE_NO_VALID_COUNTERFEITS"
        elif report.killed_trials == report.valid_trials:
            report.verdict = "ACCEPTED"
        else:
            report.verdict = "NEEDS_STRONGER_TESTS"

        self.event("[5/5] Writing proof report")
        self._finalize_report(report, report_path)
        return RunResult(report, report_path, candidate_diff)

    def _build_candidate(self, task: str, repository_map: str) -> None:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task_prompt(task, self.test_command, repository_map)},
        ]
        protocol_failures = 0
        for step in range(1, self.config.max_steps + 1):
            response = self._complete(messages)
            messages.append({"role": "assistant", "content": response.content})
            try:
                action = parse_action(response.content, TOOLS)
            except ProtocolError as exc:
                protocol_failures += 1
                if protocol_failures >= 3:
                    raise RepositoryError(f"model repeatedly violated action protocol: {exc}") from exc
                messages.append({
                    "role": "user",
                    "content": f"Protocol error: {exc}. Return exactly one valid JSON tool action.",
                })
                continue

            self.event(f"  step {step:02d}: {action.name} — {action.reason[:100]}")
            if action.name == "finish":
                return
            result = self._execute(action.name, action.arguments)
            messages.append({
                "role": "user",
                "content": f"TOOL RESULT [{action.name}]\n{result}",
            })
        raise RepositoryError(f"agent exceeded maximum of {self.config.max_steps} steps")

    def _execute(self, name: str, arguments: dict[str, Any]) -> str:
        try:
            if name == "list_files":
                return self.repository.list_files(str(arguments.get("pattern", "*")))
            if name == "search_code":
                return self.repository.search_code(
                    str(arguments["query"]), str(arguments.get("path", "."))
                )
            if name == "read_file":
                return self.repository.read_file(
                    str(arguments["path"]),
                    int(arguments.get("start_line", 1)),
                    int(arguments.get("end_line", 400)),
                )
            if name == "replace_text":
                return self.repository.replace_text(
                    str(arguments["path"]),
                    str(arguments["old"]),
                    str(arguments["new"]),
                )
            if name == "create_file":
                return self.repository.create_file(
                    str(arguments["path"]), str(arguments["content"])
                )
            if name == "apply_patch":
                if self.patch_failures >= 2:
                    return (
                        "TOOL ERROR: apply_patch is disabled after two malformed patches. "
                        "Use replace_text for existing files or create_file for a new file."
                    )
                result = self.repository.apply_patch(str(arguments["patch"]))
                if result.ok:
                    self.patch_failures = 0
                    return _format_command(result)
                self.patch_failures += 1
                return (
                    _format_command(result)
                    + "\nRECOVERY: Do not repeat the same patch. Prefer replace_text with an "
                    "exact old snippet copied from read_file, or create_file for a new file."
                )
            if name == "run_command":
                self.last_command_result = self.repository.run_command(str(arguments["command"]))
                return _format_command(self.last_command_result)
            if name == "inspect_diff":
                return self.repository.diff() or "No changes"
            if name == "repository_status":
                return self.repository.status() or "Clean"
            if name == "record_reproduction":
                if self.last_command_result is None or self.last_command_result.ok:
                    return "TOOL ERROR: reproduction requires an immediately preceding failing command"
                changed = _changed_files(self.repository.diff())
                if changed and not all(_is_test_path(path) for path in changed):
                    return (
                        "TOOL ERROR: reproduction cannot be recorded after production-code changes; "
                        "restore production code and reproduce with baseline or test-only changes"
                    )
                self.reproduction_recorded = True
                return (
                    "Reproduction evidence recorded from failing command: "
                    f"{self.last_command_result.command}"
                )
        except (KeyError, TypeError, ValueError, RepositoryError) as exc:
            return f"TOOL ERROR: {exc}"
        return f"TOOL ERROR: unsupported tool {name}"

    def _generate_counterfeits(self, task: str, candidate_diff: str) -> list[dict[str, str]]:
        prompt = counterfeit_prompt(task, candidate_diff, self.config.max_counterfeits)
        response = self._complete([{"role": "user", "content": prompt}])
        try:
            payload = parse_json_object(response.content)
        except ProtocolError as exc:
            self.event(f"  counterfeit generation failed: {exc}")
            return []
        raw = payload.get("counterfeits", [])
        if not isinstance(raw, list):
            return []
        counterfeits: list[dict[str, str]] = []
        for item in raw[: self.config.max_counterfeits]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "unnamed"))[:80]
            hypothesis = str(item.get("hypothesis", ""))[:500]
            patch = str(item.get("patch", ""))
            if patch and "diff --git" in patch:
                patch = _production_only_patch(patch)
                if patch:
                    counterfeits.append({"name": name, "hypothesis": hypothesis, "patch": patch})
        return counterfeits

    def _run_trials(
        self, candidate_diff: str, counterfeits: list[dict[str, str]]
    ) -> list[TrialResult]:
        trials: list[TrialResult] = []
        for index, counterfeit in enumerate(counterfeits, 1):
            name = counterfeit["name"]
            self.event(f"  trial {index}/{len(counterfeits)}: {name}")
            counterfeit_applied = False
            try:
                # Counterfeits are candidate-relative production mutations. Keeping the
                # candidate tests in place makes the trial both simpler and more faithful.
                applied = self.repository.apply_patch(counterfeit["patch"])
                if not applied.ok:
                    trials.append(TrialResult(
                        name=name,
                        hypothesis=counterfeit["hypothesis"],
                        valid=False,
                        killed=False,
                        test_returncode=None,
                        detail=f"invalid patch: {applied.stderr or applied.stdout}",
                    ))
                    continue
                counterfeit_applied = True
                test = self.repository.run_command(self.test_command)
                trials.append(TrialResult(
                    name=name,
                    hypothesis=counterfeit["hypothesis"],
                    valid=True,
                    killed=not test.ok,
                    test_returncode=test.returncode,
                    detail=(test.stderr or test.stdout)[-2000:],
                ))
            finally:
                if counterfeit_applied:
                    removed = self.repository.apply_patch(counterfeit["patch"], reverse=True)
                    if not removed.ok:
                        raise RepositoryError(f"could not remove counterfeit patch {name}")
        return trials

    def _generate_strengthening_patch(
        self,
        task: str,
        candidate_diff: str,
        survivors: list[TrialResult],
    ) -> str:
        survivor_text = "\n\n".join(
            f"NAME: {trial.name}\nFAULT: {trial.hypothesis}\nTEST OUTPUT:\n{trial.detail}"
            for trial in survivors
        )
        response = self._complete([{
            "role": "user",
            "content": strengthening_prompt(
                task,
                candidate_diff,
                survivor_text,
                self._test_context(),
            ),
        }])
        try:
            payload = parse_json_object(response.content)
        except ProtocolError as exc:
            self.event(f"  evidence strengthening failed: {exc}")
            return ""
        patch = payload.get("patch", "")
        if not isinstance(patch, str) or not patch.strip():
            self.event(f"  no stronger test generated: {payload.get('rationale', 'no rationale')}")
            return ""
        changed = _changed_files(patch)
        if not changed or not all(_is_test_path(path) for path in changed):
            self.event("  rejected strengthening patch because it modifies non-test files")
            return ""
        return patch

    def _test_context(self) -> str:
        paths = [
            path for path in self.repository.list_files(limit=500).splitlines()
            if _is_test_path(path)
        ][:6]
        chunks: list[str] = []
        remaining = 12_000
        for path in paths:
            try:
                content = self.repository.read_file(path, 1, 300)
            except RepositoryError:
                continue
            block = f"\n--- {path} ---\n{content}\n"
            if len(block) > remaining:
                block = block[:remaining]
            chunks.append(block)
            remaining -= len(block)
            if remaining <= 0:
                break
        return "".join(chunks) or "No existing test files were found."

    def _rerun_survivors(
        self,
        counterfeits: list[dict[str, str]],
        original_trials: list[TrialResult],
    ) -> list[TrialResult]:
        by_name = {counterfeit["name"]: counterfeit for counterfeit in counterfeits}
        updated: list[TrialResult] = []
        for trial in original_trials:
            if not trial.valid or trial.killed:
                updated.append(trial)
                continue
            counterfeit = by_name.get(trial.name)
            if counterfeit is None:
                updated.append(trial)
                continue

            counterfeit_applied = False
            try:
                # The repository already contains the correct candidate and strengthened
                # tests. Apply only the candidate-relative wrong production mutation.
                applied = self.repository.apply_patch(counterfeit["patch"])
                if not applied.ok:
                    updated.append(TrialResult(
                        trial.name, trial.hypothesis, False, False, None,
                        f"counterfeit stopped applying during strengthened trial: {applied.stderr}",
                    ))
                    continue
                counterfeit_applied = True
                test = self.repository.run_command(self.test_command)
                updated.append(TrialResult(
                    trial.name,
                    trial.hypothesis,
                    True,
                    not test.ok,
                    test.returncode,
                    (test.stderr or test.stdout)[-2000:],
                ))
            finally:
                if counterfeit_applied:
                    removed = self.repository.apply_patch(counterfeit["patch"], reverse=True)
                    if not removed.ok:
                        raise RepositoryError("could not remove counterfeit after stronger test")
        return updated

    def _complete(self, messages: list[dict[str, str]]) -> ModelResponse:
        response = self.model.complete(self._bounded_messages(messages))
        self.prompt_tokens += response.prompt_tokens
        self.completion_tokens += response.completion_tokens
        return response

    def _bounded_messages(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        limit = self.config.max_context_chars
        if sum(len(message.get("content", "")) for message in messages) <= limit:
            return messages
        if len(messages) <= 2:
            return [
                {**message, "content": message.get("content", "")[:limit // len(messages)]}
                for message in messages
            ]

        fixed = messages[:2]
        fixed_size = sum(len(message.get("content", "")) for message in fixed)
        remaining = max(1, limit - fixed_size - 200)
        recent: list[dict[str, str]] = []
        used = 0
        for message in reversed(messages[2:]):
            size = len(message.get("content", ""))
            if recent and used + size > remaining:
                break
            if not recent and size > remaining:
                recent.append({**message, "content": message.get("content", "")[-remaining:]})
                used = remaining
                break
            recent.append(message)
            used += size
        recent.reverse()
        notice = {
            "role": "user",
            "content": (
                "Earlier tool exchanges were compacted to stay within the context budget. "
                "Re-read any file or rerun any search needed for the next evidence-based action."
            ),
        }
        return [*fixed, notice, *recent]

    def _finalize_report(self, report: ProofReport, report_path: Path) -> None:
        report.prompt_tokens = self.prompt_tokens
        report.completion_tokens = self.completion_tokens
        report.write(report_path)


def _format_command(result: CommandResult) -> str:
    return (
        f"command: {result.command}\nreturncode: {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def _changed_files(diff: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"^\+\+\+ b/(.+)$", diff, flags=re.MULTILINE)))


def _is_test_path(path: str) -> bool:
    normalized = path.lower().replace("\\", "/")
    name = normalized.rsplit("/", 1)[-1]
    return (
        normalized.startswith(("test/", "tests/", "spec/", "specs/", "__tests__/"))
        or "/test/" in normalized
        or "/tests/" in normalized
        or "/spec/" in normalized
        or "/__tests__/" in normalized
        or name.startswith(("test_", "test-", "spec_", "spec-"))
        or ".test." in name
        or ".spec." in name
        or name.endswith(("_test.py", "_test.go", "tests.cs", "test.java"))
    )


def _production_only_patch(patch: str) -> str:
    sections = re.split(r"(?=^diff --git )", patch.strip(), flags=re.MULTILINE)
    kept: list[str] = []
    for section in sections:
        if not section.startswith("diff --git "):
            continue
        changed = _changed_files(section)
        if changed and not any(_is_test_path(path) for path in changed):
            kept.append(section.rstrip() + "\n")
    return "".join(kept)
