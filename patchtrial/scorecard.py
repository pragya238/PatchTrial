from __future__ import annotations

import argparse
import json
from pathlib import Path


def aggregate(paths: list[Path]) -> dict:
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    valid = sum(int(report.get("valid_trials", 0)) for report in reports)
    killed = sum(int(report.get("killed_trials", 0)) for report in reports)
    accepted = sum(report.get("verdict") == "ACCEPTED" for report in reports)
    strengthened = sum(bool(report.get("strengthening_applied")) for report in reports)
    inconclusive = sum(str(report.get("verdict", "")).startswith("INCONCLUSIVE") for report in reports)
    durations = [
        sum(float(item.get("duration_seconds", 0)) for item in report.get("command_log", []))
        for report in reports
    ]
    confidence = [float(report.get("evidence_confidence", 0)) for report in reports]
    return {
        "runs": len(reports),
        "accepted": accepted,
        "acceptance_rate": 100 * accepted / len(reports) if reports else 0,
        "valid_counterfeits": valid,
        "counterfeits_killed": killed,
        "counterfeit_kill_rate": 100 * killed / valid if valid else 0,
        "runs_strengthened": strengthened,
        "inconclusive": inconclusive,
        "average_evidence_confidence": sum(confidence) / len(confidence) if confidence else 0,
        "command_runtime_seconds": sum(durations),
        "restoration_failures": sum(bool(report.get("restoration_failed")) for report in reports),
        "prompt_tokens": sum(int(report.get("prompt_tokens", 0)) for report in reports),
        "completion_tokens": sum(int(report.get("completion_tokens", 0)) for report in reports),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aggregate PatchTrial proof reports")
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = aggregate(args.reports)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("PatchTrial scorecard\n")
        print(f"  Runs accepted:       {result['accepted']}/{result['runs']} ({result['acceptance_rate']:.0f}%)")
        print(f"  Counterfeits killed: {result['counterfeits_killed']}/{result['valid_counterfeits']} ({result['counterfeit_kill_rate']:.0f}%)")
        print(f"  Evidence strengthened in {result['runs_strengthened']} run(s)")
        print(f"  Inconclusive runs:    {result['inconclusive']}")
        print(f"  Avg. confidence:      {result['average_evidence_confidence']:.0f}%")
        print(f"  Command runtime:      {result['command_runtime_seconds']:.1f}s")
        print(f"  Restoration failures:{result['restoration_failures']:2d}")
        print(f"  Model tokens: {result['prompt_tokens'] + result['completion_tokens']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
