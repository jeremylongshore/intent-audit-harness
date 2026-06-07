#!/usr/bin/env python3
"""
audit-harness currency — advisory upstream-currency report (PP-PLAN-040 Phase 5 / E7).

Currency depends on upstream state, which is non-deterministic and network-bound, so
it is deliberately the WEAKEST kind of check: an advisory REPORT with **no exit-code
authority, no auto-fix, and no live-fetch**. It reads the per-upstream-identity pin
relation (schemas/currency/pins.v1.json) — where each upstream carries its own
pinned_version + the date it was last verified (checked_at) + a staleness window —
and reports which pins are themselves STALE (checked_at older than the window), i.e.
which pins a human should re-verify against upstream.

This models the pin's OWN staleness as detectable, rather than one opaque
".schema-version" scalar. The /sync-testing-harness skill consumes this report to
open advisory bump PRs; the report never reddens a build (always exit 0).

Stdlib only. No network. No filesystem mutation.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PINS = os.path.join(HERE, "..", "schemas", "currency", "pins.v1.json")


def parse_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def build_report(pins_doc, today):
    default_window = pins_doc.get("default_staleness_window_days", 90)
    out = []
    for pin in pins_doc.get("pins", []):
        checked = parse_date(pin.get("checked_at", ""))
        window = pin.get("staleness_window_days", default_window)
        if checked is None:
            age, status = None, "unknown-checked_at"
        else:
            age = (today - checked).days
            status = "stale" if age > window else "current"
        out.append({
            "identity": pin.get("identity"),
            "pinned_version": pin.get("pinned_version"),
            "checked_at": pin.get("checked_at"),
            "age_days": age,
            "window_days": window,
            "status": status,
            "source": pin.get("source"),
            "notes": pin.get("notes"),
        })
    return out


def main():
    ap = argparse.ArgumentParser(description="Advisory upstream-currency report (no exit authority)")
    ap.add_argument("--pins", default=DEFAULT_PINS, help="path to the pin relation datum")
    ap.add_argument("--json", action="store_true", help="emit JSON report")
    ap.add_argument("--today", default=None, help="override 'today' (YYYY-MM-DD) for reproducible reports/tests")
    args = ap.parse_args()

    pins_path = os.path.abspath(args.pins)
    try:
        with open(pins_path, "r", encoding="utf-8") as f:
            pins_doc = json.load(f)
    except Exception as e:
        sys.stderr.write(f"currency: cannot read pins at {pins_path}: {e}\n")
        sys.exit(2)

    today = parse_date(args.today) if args.today else datetime.now(timezone.utc).date()
    report = build_report(pins_doc, today)
    stale = [r for r in report if r["status"] == "stale"]
    unknown = [r for r in report if r["status"] == "unknown-checked_at"]

    if args.json:
        print(json.dumps({
            "report": "currency/v1",
            "generated_for": today.strftime("%Y-%m-%d"),
            "pins": report,
            "stale_count": len(stale),
            "advisory": True,
        }, indent=2))
    else:
        print(f"Upstream currency (advisory) — as of {today.strftime('%Y-%m-%d')}")
        print(f"{'identity':<24} {'pinned':<14} {'checked_at':<12} {'age':>5} {'win':>4}  status")
        for r in report:
            age = "—" if r["age_days"] is None else str(r["age_days"]) + "d"
            if r["status"] == "stale":
                mark = "⚠ STALE"
            elif r["status"] == "current":
                mark = "current"
            else:
                mark = "? " + r["status"]
            print(f"{(r['identity'] or ''):<24} {(r['pinned_version'] or ''):<14} "
                  f"{(r['checked_at'] or ''):<12} {age:>5} {r['window_days']:>4}  {mark}")
        print()
        if stale:
            print(f"{len(stale)} pin(s) past their staleness window — re-verify against upstream, "
                  f"then bump pinned_version + checked_at in schemas/currency/pins.v1.json:")
            for r in stale:
                print(f"  - {r['identity']}: last checked {r['checked_at']} "
                      f"({r['age_days']}d ago > {r['window_days']}d)")
        else:
            print("All pins within their staleness window.")
        if unknown:
            print(f"{len(unknown)} pin(s) have an unparseable checked_at — fix the date format (YYYY-MM-DD).")

    # Advisory ONLY: never any exit-code authority. Always exit 0.
    sys.exit(0)


if __name__ == "__main__":
    main()
