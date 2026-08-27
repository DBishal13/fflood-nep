import argparse
import json
from pathlib import Path

from .config import EventConfig
from .stac import acquisition_plan
from .timeline import CATEGORIES as TIMELINE_CATEGORIES


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
    detect_parser.add_argument("--no-ems", action="store_true")

    ems_parser = subparsers.add_parser(
        "ems", help="fetch the Copernicus EMS Rapid Mapping activation snapshot for this event (EMSR927)"
    )
    ems_parser.add_argument("--output", type=Path, default=Path("docs/data/ems_activation.json"))

    timeline_parser = subparsers.add_parser("timeline", help="manage the public event timeline")
    timeline_sub = timeline_parser.add_subparsers(dest="timeline_command", required=True)
    timeline_add_parser = timeline_sub.add_parser("add", help="append a new entry to the event timeline")
    timeline_add_parser.add_argument("--output", type=Path, default=Path("docs/data/timeline.json"))
    timeline_add_parser.add_argument("--date", required=True, help="ISO 8601 UTC, e.g. 2026-08-27T12:00:00Z")
    timeline_add_parser.add_argument("--category", required=True, choices=sorted(TIMELINE_CATEGORIES))
    timeline_add_parser.add_argument("--headline", required=True)
    timeline_add_parser.add_argument("--body", required=True)
    timeline_add_parser.add_argument(
        "--source", action="append", required=True, metavar="LABEL|URL",
        help="repeatable; format 'Label|https://...'",
    )

    insar_parser = subparsers.add_parser(
        "insar", help="check for a post-event SLC pass and submit/track a HyP3 coherence job (needs ~/.netrc)"
    )
    insar_parser.add_argument("--bbox", nargs=4, type=float, metavar=("MINX", "MINY", "MAXX", "MAXY"), required=True)
    insar_parser.add_argument("--event-start", required=True, help="ISO 8601 UTC, e.g. 2026-08-26T00:00:00Z")
    insar_parser.add_argument("--output", type=Path, default=Path("docs/data/insar_status.json"))

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
            with_ems=not args.no_ems,
        )
        print(f"Wrote {args.output_dir} with status: {report['status']}")
    elif args.command == "ems":
        from . import ems

        activation = ems.fetch_ems_activation()
        payload = {
            "source": ems.EMS_ACTIVATION_URL,
            "source_note": ems.EMS_CAVEAT,
            "activation": ems.summarize_activation(activation) if activation else None,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        if activation:
            print(f"Wrote {args.output} ({payload['activation']['code']}, {len(payload['activation']['products'])} product rows)")
        else:
            print(f"Wrote {args.output} (no activation data available)")
    elif args.command == "timeline" and args.timeline_command == "add":
        from . import timeline

        sources = []
        for raw in args.source:
            if "|" not in raw:
                parser.error(f"--source must be 'Label|https://url', got {raw!r}")
            label, url = raw.split("|", 1)
            sources.append({"label": label.strip(), "url": url.strip()})

        entry = timeline.add_entry(
            args.output,
            date=args.date,
            category=args.category,
            headline=args.headline,
            body=args.body,
            sources=sources,
        )
        print(f"Added timeline entry ({entry['category']}, {entry['date']}): {entry['headline']}")
    elif args.command == "insar":
        from . import insar

        state = insar.check_and_advance(args.output, tuple(args.bbox), args.event_start)
        if state["job"]:
            print(f"Job {state['job']['job_id']}: {state['job']['status']}")
        elif state["post_event_scene"]:
            print(f"Post-event scene found ({state['post_event_scene']['sceneId']}) but job not yet submitted")
        elif state["pre_event_scene"]:
            print(f"Pinned pre-event scene {state['pre_event_scene']['sceneId']}; no post-event pass yet")
        else:
            print("No SLC scenes found for this AOI/date range")


if __name__ == "__main__":
    main()
