#!/usr/bin/env python3
"""Find and delete bad (>150 kg) Garmin Connect weigh-ins created by a kg/lb mix-up.

Written against garminconnect 0.3.20 (Python >= 3.12):
  Garmin.get_weigh_ins(startdate, enddate)      -> GET /weight-service/weight/range/{s}/{e}?includeAll=true
  Garmin.delete_weigh_in(weight_pk, cdate)      -> DELETE /weight-service/weight/{cdate}/byversion/{weight_pk}
  Garmin.login(tokenstore)                      -> loads/saves DI tokens (garmin_tokens.json)

Dry run by default. Use --execute to delete.
"""

from __future__ import annotations

import argparse
import csv
import getpass
import logging
import os
import random
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectNotFoundError,
    GarminConnectTooManyRequestsError,
)

START_DATE = date(2018, 1, 1)
END_DATE = date(2026, 3, 10)  # everything from 2026-03-11 on is clean
THRESHOLD_KG = 105.0
MAX_SELECTED_FRACTION = 0.90

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
BACKUP_CSV = DATA_DIR / "backup_deleted_weighins.csv"
ALL_CSV = DATA_DIR / "all_weighins.csv"
DELETE_LOG = DATA_DIR / "deletion_log.csv"
DEFAULT_TOKENSTORE = os.getenv("GARMINTOKENS", "~/.garminconnect")

# Fields copied from each Garmin weight record into the CSVs (if present).
# Garmin reports weight / boneMass / muscleMass in grams.
GRAM_FIELDS = ("weight", "boneMass", "muscleMass")
EXTRA_FIELDS = (
    "bmi", "bodyFat", "bodyWater", "boneMass", "muscleMass", "physiqueRating",
    "visceralFat", "metabolicAge", "sourceType", "timestampGMT",
)
CSV_COLUMNS = ["date", "time", "weight_kg", "id", *EXTRA_FIELDS]

log = logging.getLogger("cleanup")


# --------------------------------------------------------------------------- login

def login(tokenstore: str) -> Garmin:
    """Resume from saved tokens; fall back to email/password (+ MFA) only if needed."""
    try:
        api = Garmin()
        api.login(tokenstore)
        log.info("Logged in with saved tokens from %s", tokenstore)
        return api
    except (GarminConnectAuthenticationError, GarminConnectConnectionError) as e:
        log.info("Saved tokens unavailable or rejected (%s); logging in with credentials.",
                 type(e).__name__)

    email = os.getenv("GARMIN_EMAIL") or input("Garmin email: ").strip()
    password = os.getenv("GARMIN_PASSWORD") or getpass.getpass("Garmin password: ")
    api = Garmin(
        email=email,
        password=password,
        prompt_mfa=lambda: input("Garmin MFA code: ").strip(),
    )
    del password
    # Passing a path makes the library dump tokens there after a credential login.
    api.login(tokenstore)
    log.info("Logged in; tokens saved to %s", tokenstore)
    return api


# --------------------------------------------------------------------------- retries

def _status_of(exc: BaseException) -> int | None:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return status if isinstance(status, int) else None


def call_with_retry(fn, *args, what: str, max_attempts: int = 6):
    """Retry on rate limiting (429) and transient errors (5xx / network)."""
    for attempt in range(1, max_attempts + 1):
        try:
            return fn(*args)
        except GarminConnectNotFoundError:
            raise
        except GarminConnectTooManyRequestsError as e:
            wait = min(60 * 2 ** (attempt - 1), 600)
            reason = f"rate limited ({e})"
        except GarminConnectConnectionError as e:
            status = _status_of(e)
            if status == 429:
                wait = min(60 * 2 ** (attempt - 1), 600)
            elif status is None or status >= 500:
                wait = min(5 * 2 ** (attempt - 1), 120)
            else:
                raise  # other 4xx: not transient
            reason = f"{e}"
        if attempt == max_attempts:
            raise RuntimeError(f"{what}: giving up after {max_attempts} attempts: {reason}")
        wait += random.uniform(0, 2)
        log.warning("%s: attempt %d failed (%s); retrying in %.0fs", what, attempt, reason, wait)
        time.sleep(wait)


# --------------------------------------------------------------------------- fetch

def month_chunks(start: date, end: date):
    cur = start
    while cur <= end:
        nxt = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
        yield cur, min(end, date.fromordinal(nxt.toordinal() - 1))
        cur = nxt


def _iter_weight_records(obj):
    """Yield every dict carrying a samplePk + weight, wherever it sits in the response.

    The range endpoint nests records (per-day summaries with all/latest metrics);
    walking the structure avoids depending on one exact layout, and duplicates
    (e.g. a day's 'latest' record repeated) are removed by samplePk afterwards.
    """
    if isinstance(obj, dict):
        if "samplePk" in obj and "weight" in obj:
            yield obj
        for v in obj.values():
            yield from _iter_weight_records(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_weight_records(v)


def _to_row(rec: dict) -> dict | None:
    if rec.get("samplePk") is None or rec.get("weight") is None:
        return None
    # 'date' is epoch-ms of the *local* wall-clock time; calendarDate is the local day.
    local = None
    if isinstance(rec.get("date"), (int, float)):
        local = datetime.fromtimestamp(rec["date"] / 1000, tz=timezone.utc)
    cal = rec.get("calendarDate") or (local.date().isoformat() if local else None)
    if not cal:
        return None
    row = {
        "date": cal,
        "time": local.strftime("%H:%M:%S") if local else "",
        "weight_kg": round(rec["weight"] / 1000.0, 3),
        "id": str(rec["samplePk"]),
        "_raw_weight": rec["weight"],
    }
    for f in EXTRA_FIELDS:
        v = rec.get(f)
        if f in GRAM_FIELDS and isinstance(v, (int, float)):
            v = round(v / 1000.0, 3)
        row[f] = "" if v is None else v
    return row


def fetch_all(api: Garmin, start: date, end: date, delay: float) -> list[dict]:
    rows: dict[str, dict] = {}
    for s, e in month_chunks(start, end):
        data = call_with_retry(api.get_weigh_ins, s.isoformat(), e.isoformat(),
                               what=f"fetch {s:%Y-%m}")
        n_before = len(rows)
        for rec in _iter_weight_records(data):
            row = _to_row(rec)
            # Keep strictly inside the requested window, whatever the API returns.
            if row and start.isoformat() <= row["date"] <= end.isoformat():
                rows.setdefault(row["id"], row)
        log.info("Fetched %s: %d weigh-ins", f"{s:%Y-%m}", len(rows) - n_before)
        time.sleep(delay)
    return sorted(rows.values(), key=lambda r: (r["date"], r["time"], r["id"]))


# --------------------------------------------------------------------------- csv

def write_csv(path: Path, rows: list[dict]) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def write_backup(selected: list[dict]) -> int:
    """Merge with any existing backup so reruns never lose already-deleted entries."""
    merged: dict[str, dict] = {}
    if BACKUP_CSV.exists():
        with BACKUP_CSV.open(newline="") as f:
            for r in csv.DictReader(f):
                merged[r["id"]] = r
    for r in selected:
        merged[r["id"]] = r
    rows = sorted(merged.values(), key=lambda r: (r["date"], r["time"], r["id"]))
    write_csv(BACKUP_CSV, rows)
    return len(rows)


def write_full_export(rows: list[dict]) -> None:
    # Keep the previous export rather than overwrite it (e.g. the pre-deletion one).
    if ALL_CSV.exists():
        ALL_CSV.rename(ALL_CSV.with_name(f"all_weighins.{datetime.now():%Y%m%d-%H%M%S}.csv"))
    write_csv(ALL_CSV, rows)


def append_delete_log(row: dict, status: str) -> None:
    new = not DELETE_LOG.exists()
    with DELETE_LOG.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["logged_at", "status", "date", "time", "weight_kg", "id"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), status,
                    row["date"], row["time"], row["weight_kg"], row["id"]])


# --------------------------------------------------------------------------- main

def print_rows(rows: list[dict], limit: int) -> None:
    print(f"  {'date':<10}  {'time':<8}  {'weight_kg':>9}  id")
    for r in rows[:limit]:
        print(f"  {r['date']:<10}  {r['time']:<8}  {r['weight_kg']:>9.2f}  {r['id']}")
    if len(rows) > limit:
        print(f"  ... and {len(rows) - limit} more")


def safety_checks(all_rows: list[dict], selected: list[dict]) -> None:
    bad = [r for r in selected if not r["weight_kg"] > THRESHOLD_KG]
    if bad:
        sys.exit(f"ABORT: {len(bad)} selected entries are <= {THRESHOLD_KG} kg (e.g. {bad[0]}).")
    outside = [r for r in selected if not START_DATE.isoformat() <= r["date"] <= END_DATE.isoformat()]
    if outside:
        sys.exit(f"ABORT: {len(outside)} selected entries fall outside {START_DATE}..{END_DATE}.")
    if all_rows and len(selected) / len(all_rows) > MAX_SELECTED_FRACTION:
        sys.exit(f"ABORT: {len(selected)}/{len(all_rows)} entries selected "
                 f"(> {MAX_SELECTED_FRACTION:.0%}). Something is off; nothing deleted.")
    # Sanity check on units: Garmin should return grams (a real ~75 kg reading = 75000).
    raw_max = max((r["_raw_weight"] for r in all_rows), default=0)
    if all_rows and raw_max < 1000:
        sys.exit(f"ABORT: largest raw weight is {raw_max}; values don't look like grams.")


def report_remaining(rows: list[dict]) -> None:
    over = [r for r in rows if r["weight_kg"] > THRESHOLD_KG]
    print(f"\nVerification: {len(rows)} weigh-ins remain in {START_DATE}..{END_DATE}; "
          f"{len(over)} above {THRESHOLD_KG:g} kg.")
    if rows:
        ws = [r["weight_kg"] for r in rows]
        print(f"  min weight: {min(ws):.2f} kg   max weight: {max(ws):.2f} kg")
    if over:
        print("  Remaining entries above threshold:")
        print_rows(over, 20)


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--execute", action="store_true", help="actually delete (default: dry run)")
    ap.add_argument("--yes", action="store_true",
                    help="with --execute, skip the 'type DELETE' confirmation")
    ap.add_argument("--max-delete", type=int, default=None, metavar="N",
                    help="delete at most N entries this run (for testing)")
    ap.add_argument("--delay", type=float, default=1.0,
                    help="seconds to wait between API calls (default 1.0)")
    ap.add_argument("--tokenstore", default=DEFAULT_TOKENSTORE,
                    help="token directory (default: $GARMINTOKENS or ~/.garminconnect)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    if args.max_delete is not None and args.max_delete < 1:
        ap.error("--max-delete must be >= 1")

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    # Keep library internals quiet even in verbose mode.
    logging.getLogger("garminconnect").setLevel(logging.WARNING)

    api = login(args.tokenstore)

    print(f"Fetching weigh-ins {START_DATE} .. {END_DATE} in monthly chunks...")
    all_rows = fetch_all(api, START_DATE, END_DATE, args.delay)
    selected = [r for r in all_rows if r["weight_kg"] > THRESHOLD_KG]

    write_full_export(all_rows)
    backup_total = write_backup(selected)
    print(f"\nFetched {len(all_rows)} weigh-ins. Full export: {ALL_CSV.name}")
    print(f"Selected {len(selected)} entries > {THRESHOLD_KG:g} kg. "
          f"Backup: {BACKUP_CSV.name} ({backup_total} rows incl. earlier runs)")

    safety_checks(all_rows, selected)

    if not selected:
        print("Nothing to delete.")
        report_remaining(all_rows)
        return

    print("\nFirst 20 selected entries:")
    print_rows(selected, 20)

    if not args.execute:
        print("\nDry run: nothing deleted. Re-run with --execute to delete.")
        return

    to_delete = selected[: args.max_delete] if args.max_delete else selected
    print(f"\nTotal selected: {len(selected)}. This run will delete: {len(to_delete)}.")
    if args.yes:
        print("--yes given; skipping confirmation.")
    elif input("Type DELETE to confirm: ").strip() != "DELETE":
        sys.exit("Not confirmed; nothing deleted.")

    deleted = gone = failed = consecutive_failures = 0
    for i, r in enumerate(to_delete, 1):
        # Belt and braces: re-check every row right before deleting it.
        if not (r["weight_kg"] > THRESHOLD_KG and r["date"] <= END_DATE.isoformat()):
            sys.exit(f"ABORT: refusing to delete {r}")
        label = f"[{i}/{len(to_delete)}] {r['date']} {r['time']} {r['weight_kg']:.2f} kg id={r['id']}"
        try:
            call_with_retry(api.delete_weigh_in, r["id"], r["date"], what=f"delete {r['id']}")
            deleted += 1
            consecutive_failures = 0
            log.info("Deleted %s", label)
            append_delete_log(r, "deleted")
        except GarminConnectNotFoundError:
            gone += 1
            log.info("Already gone %s", label)
            append_delete_log(r, "already_gone")
        except (GarminConnectConnectionError, RuntimeError) as e:
            failed += 1
            consecutive_failures += 1
            log.error("FAILED %s: %s", label, e)
            append_delete_log(r, f"failed: {e}")
            if consecutive_failures >= 5:
                log.error("5 consecutive failures; stopping. Re-run to resume.")
                break
        time.sleep(args.delay)

    print(f"\nDone: {deleted} deleted, {gone} already gone, {failed} failed. "
          f"Log: {DELETE_LOG.name}")

    print("Re-fetching to verify...")
    report_remaining(fetch_all(api, START_DATE, END_DATE, args.delay))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nInterrupted. Re-run to resume; already-deleted entries are skipped.")
