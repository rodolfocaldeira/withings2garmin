#!/usr/bin/env python3
"""Upload Withings weigh-ins that are not yet in Garmin Connect.

Reads data/withings_weights.csv (written by withings_download.py), fetches the Garmin
weigh-ins for the same date range, and treats a Withings weigh-in as already
present when Garmin has a weigh-in on the same day whose weight differs by at
most 0.1 kg. Each Garmin weigh-in can match only one Withings weigh-in, so two
genuine same-day weigh-ins are not collapsed into one.

Dry run by default. Use --execute to upload.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path

import cleanup_weighins as cw  # login, fetch_all and the Garmin helpers

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
DEFAULT_IN = DATA_DIR / "withings_weights.csv"
UPLOAD_LOG = DATA_DIR / "upload_log.csv"
TOLERANCE_KG = 0.1
MAX_CONSECUTIVE_FAILURES = 5

log = logging.getLogger("upload")


# --------------------------------------------------------------------------- compare

def load_withings(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        rows = [
            {
                "date": r["date"],
                "time": r["time"],
                "weight_kg": float(r["weight_kg"]),
                "timestamp": int(r["timestamp"]),
                "grpid": r["grpid"],
            }
            for r in csv.DictReader(f)
        ]
    return sorted(rows, key=lambda r: r["timestamp"])


def find_missing(withings: list[dict], garmin: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split Withings weigh-ins into (already in Garmin, not yet in Garmin)."""
    garmin_by_day: dict[str, list[dict]] = {}
    for g in garmin:
        garmin_by_day.setdefault(g["date"], []).append(g)

    matched_ids: set[str] = set()
    present, missing = [], []
    for w in withings:
        match = next(
            (
                g for g in garmin_by_day.get(w["date"], [])
                if g["id"] not in matched_ids
                and round(abs(g["weight_kg"] - w["weight_kg"]), 3) <= TOLERANCE_KG
            ),
            None,
        )
        if match:
            matched_ids.add(match["id"])
            present.append(w)
        else:
            missing.append(w)
    return present, missing


# --------------------------------------------------------------------------- upload

def upload_one(api: cw.Garmin, row: dict) -> None:
    """Add one weigh-in, keeping the original local and UTC times."""
    local = f"{row['date']}T{row['time']}"
    gmt = datetime.fromtimestamp(row["timestamp"], UTC).strftime("%Y-%m-%dT%H:%M:%S")
    # No retry here: if a request timed out after Garmin saved it, a retry would
    # create a duplicate. A failed row is logged and the run stops after several in a row.
    api.add_weigh_in_with_timestamps(
        row["weight_kg"], "kg", dateTimestamp=local, gmtTimestamp=gmt,
    )


def append_upload_log(row: dict, status: str) -> None:
    new = not UPLOAD_LOG.exists()
    with UPLOAD_LOG.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["logged_at", "status", "date", "time", "weight_kg", "grpid"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), status,
                    row["date"], row["time"], row["weight_kg"], row["grpid"]])


def print_rows(rows: list[dict], limit: int) -> None:
    print(f"  {'date':<10}  {'time':<8}  {'weight_kg':>9}  withings_id")
    for r in rows[:limit]:
        print(f"  {r['date']:<10}  {r['time']:<8}  {r['weight_kg']:>9.2f}  {r['grpid']}")
    if len(rows) > limit:
        print(f"  ... and {len(rows) - limit} more")


# --------------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", type=Path, default=DEFAULT_IN, help="Withings CSV to upload from")
    ap.add_argument("--execute", action="store_true", help="actually upload (default: dry run)")
    ap.add_argument("--yes", action="store_true",
                    help="with --execute, skip the 'type UPLOAD' confirmation")
    ap.add_argument("--max-upload", type=int, default=None, metavar="N",
                    help="upload at most N weigh-ins this run (for testing)")
    ap.add_argument("--delay", type=float, default=1.0,
                    help="seconds to wait between API calls (default 1.0)")
    ap.add_argument("--tokenstore", default=cw.DEFAULT_TOKENSTORE,
                    help="Garmin token directory (default: $GARMINTOKENS or ~/.garminconnect)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    if args.max_upload is not None and args.max_upload < 1:
        ap.error("--max-upload must be >= 1")

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("garminconnect").setLevel(logging.WARNING)
    DATA_DIR.mkdir(exist_ok=True)

    withings = load_withings(args.input)
    if not withings:
        sys.exit(f"No weigh-ins found in {args.input}.")
    start = min(r["date"] for r in withings)
    end = max(r["date"] for r in withings)

    api = cw.login(args.tokenstore)

    print(f"Fetching Garmin weigh-ins {start} .. {end} ...")
    garmin = cw.fetch_all(api, date.fromisoformat(start), date.fromisoformat(end), args.delay)

    present, missing = find_missing(withings, garmin)
    print(f"\nWithings weigh-ins in file: {len(withings)}")
    print(f"Garmin weigh-ins in range:  {len(garmin)}")
    print(f"Already in Garmin:          {len(present)}")
    print(f"To upload:                  {len(missing)}")
    if not missing:
        print("Nothing to upload.")
        return

    print("\nFirst 20 to upload:")
    print_rows(missing, 20)

    if not args.execute:
        print("\nDry run: nothing uploaded. Re-run with --execute to upload.")
        return

    to_upload = missing[: args.max_upload] if args.max_upload else missing
    print(f"\nThis run will upload: {len(to_upload)} of {len(missing)}.")
    if args.yes:
        print("--yes given; skipping confirmation.")
    elif input("Type UPLOAD to confirm: ").strip() != "UPLOAD":
        sys.exit("Not confirmed; nothing uploaded.")

    uploaded = failed = consecutive_failures = 0
    for i, row in enumerate(to_upload, 1):
        label = f"[{i}/{len(to_upload)}] {row['date']} {row['time']} {row['weight_kg']:.2f} kg"
        try:
            upload_one(api, row)
            uploaded += 1
            consecutive_failures = 0
            log.info("Uploaded %s", label)
            append_upload_log(row, "uploaded")
        except Exception as e:  # the library raises several exception types
            failed += 1
            consecutive_failures += 1
            log.error("FAILED %s: %s", label, e)
            append_upload_log(row, f"failed: {e}")
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                log.error("%d consecutive failures; stopping. Re-run to resume.",
                          MAX_CONSECUTIVE_FAILURES)
                break
        time.sleep(args.delay)

    print(f"\nDone: {uploaded} uploaded, {failed} failed. Log: {UPLOAD_LOG.name}")

    print("Re-fetching Garmin to verify...")
    garmin = cw.fetch_all(api, date.fromisoformat(start), date.fromisoformat(end), args.delay)
    _, still_missing = find_missing(withings, garmin)
    print(f"Withings weigh-ins still missing from Garmin: {len(still_missing)}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nInterrupted. Re-run to resume; already-uploaded entries are skipped.")
