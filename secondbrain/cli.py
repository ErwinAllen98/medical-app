"""Command line entry point — lets the loop run from cron.

    python -m secondbrain.cli status
    python -m secondbrain.cli cycle --pull
    python -m secondbrain.cli profile
    python -m secondbrain.cli plans
    python -m secondbrain.cli push-anki
    python -m secondbrain.cli export-apkg
    python -m secondbrain.cli import-reviews reviews.csv
    python -m secondbrain.cli mastery
    python -m secondbrain.cli notion
    python -m secondbrain.cli seed-demo
"""

from __future__ import annotations

import argparse
import json
import sys

from . import anki, diagnostics, ingest, mastery, notion, pipeline, restudy
from .store import Store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="secondbrain", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status")
    cycle = sub.add_parser("cycle")
    cycle.add_argument("--pull", action="store_true", help="pull review history from AnkiConnect first")
    sub.add_parser("profile")
    sub.add_parser("plans")
    sub.add_parser("push-anki")
    sub.add_parser("export-apkg")
    imp = sub.add_parser("import-reviews")
    imp.add_argument("path")
    sub.add_parser("mastery")
    sub.add_parser("notion")
    sub.add_parser("seed-demo")

    args = parser.parse_args(argv)
    store = Store()

    if args.command == "status":
        print(json.dumps(store.stats(), indent=2))

    elif args.command == "cycle":
        report = pipeline.run_cycle(store, pull_from_anki=args.pull)
        print(json.dumps(report.__dict__, indent=2))

    elif args.command == "profile":
        profile = diagnostics.build_profile(store)
        for p in profile.patterns:
            print(f"[pattern] {p.narrative}  (severity {p.severity})")
        for u in profile.top(15):
            if not u.attempts:
                continue
            print(
                f"{u.priority:6.2f}  {u.label:<55} {u.failures}/{u.attempts} "
                f"{u.top_error or '-':<22} {','.join(u.signatures)}"
            )

    elif args.command == "plans":
        for plan in store.list_plans():
            print(restudy.plan_to_markdown(store, plan))
            print("\n" + "-" * 70 + "\n")

    elif args.command == "push-anki":
        try:
            report = anki.push_cards(store)
            print(f"added={report.added} skipped={report.skipped} failed={report.failed}")
            for err in report.errors:
                print("  !", err)
        except anki.AnkiError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    elif args.command == "export-apkg":
        print(anki.export_apkg(store))

    elif args.command == "import-reviews":
        with open(args.path, encoding="utf-8") as fh:
            print(json.dumps(ingest.import_csv(store, fh.read()), indent=2))

    elif args.command == "mastery":
        for report in mastery.evaluate_all(store):
            mark = "MASTERED" if report.mastered else f"{report.score:.0%}"
            missing = "" if report.mastered else "  missing: " + ", ".join(c.key for c in report.missing)
            print(f"{mark:>9}  {report.label}{missing}")

    elif args.command == "notion":
        try:
            print(json.dumps(notion.push_mastered(store), indent=2))
        except notion.NotionError as exc:
            path = notion.export_markdown(store)
            print(f"{exc}\nExported Markdown instead: {path}")

    elif args.command == "seed-demo":
        print(json.dumps(pipeline.seed_demo(store), indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
