import argparse
import json
from pathlib import Path

from .config import EventConfig
from .stac import acquisition_plan


def main() -> None:
    parser = argparse.ArgumentParser(prog="fflood-nep")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="write a reproducible STAC acquisition plan")
    plan_parser.add_argument("--config", type=Path, required=True)
    plan_parser.add_argument("--output", type=Path, required=True)

    detect_parser = subparsers.add_parser("detect", help="run Sentinel-1 flood-extent change detection")
    detect_parser.add_argument("--config", type=Path, required=True)
    detect_parser.add_argument("--output-dir", type=Path, required=True)
    detect_parser.add_argument("--data-dir", type=Path, default=Path("data"))
    detect_parser.add_argument("--polarization", default="VV", choices=["VV", "VH", "HH", "HV"])
    detect_parser.add_argument("--threshold-db", type=float, default=-3.0)
    detect_parser.add_argument("--no-exposure", action="store_true")
    detect_parser.add_argument("--no-gauge", action="store_true")

    args = parser.parse_args()

    if args.command == "plan":
        config = EventConfig.from_toml(args.config)
        plan = acquisition_plan(config)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {args.output} with {len(plan['searches'])} STAC searches")
    elif args.command == "detect":
        from .detect import run_detection

        config = EventConfig.from_toml(args.config)
        report = run_detection(
            config,
            args.output_dir,
            data_dir=args.data_dir,
            polarization=args.polarization,
            threshold_db=args.threshold_db,
            with_exposure=not args.no_exposure,
            with_gauge=not args.no_gauge,
        )
        print(f"Wrote {args.output_dir} with status: {report['status']}")


if __name__ == "__main__":
    main()
