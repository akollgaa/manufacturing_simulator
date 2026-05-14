from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mfg_des import StudyConfig, run_study
from mfg_logic import load_factory_file, write_replay_jsonl


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a ManufacturingSim study headlessly.")
    parser.add_argument("factory_xml", type=Path, help="Path to the factory XML file.")
    parser.add_argument("--distribution", action="store_true", help="Include likely-scenario distribution output when replications are enabled.")
    parser.add_argument("--replay-out", type=Path, help="Optional JSONL path to write a replay log.")
    parser.add_argument("--replay-scenario", default="likely", choices=("perfect", "likely", "worst"), help="Scenario to export when --replay-out is provided.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    parse_result = load_factory_file(args.factory_xml)
    if not parse_result.is_valid:
        payload = {
            "errors": [
                {
                    "code": message.code,
                    "message": message.message,
                    "path": message.path,
                }
                for message in parse_result.errors
            ]
        }
        sys.stderr.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return 1

    capture_replay = (args.replay_scenario,) if args.replay_out else ()
    study_result = run_study(
        parse_result,
        StudyConfig(
            include_distribution=args.distribution,
            capture_replay_scenarios=capture_replay,
        ),
    )
    if args.replay_out:
        replay = study_result.replays.get(args.replay_scenario)
        if replay is None:
            sys.stderr.write(json.dumps({"error": f"No replay was captured for scenario '{args.replay_scenario}'."}, indent=2) + "\n")
            return 1
        write_replay_jsonl(args.replay_out, replay)
    sys.stdout.write(study_result.to_json(include_distribution=args.distribution) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
