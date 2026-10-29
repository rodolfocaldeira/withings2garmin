#!/usr/bin/env python3
"""Download body-weight measurements from the Withings API into a CSV file.

First run: opens your browser for Withings authorization, catches the callback
on a local server and stores the tokens in withings_tokens.json. Later runs reuse
and refresh those tokens, so no browser is needed.

Setup: create an app at https://developer.withings.com/dashboard, set its
callback URL to WITHINGS_REDIRECT_URI, then export the credentials:

    export WITHINGS_CLIENT_ID=...
    export WITHINGS_CLIENT_SECRET=...
    export WITHINGS_REDIRECT_URI=http://localhost:8765/callback   # optional

Usage:
    python withings_download.py                    # all weights -> withings_weights.csv
    python withings_download.py --since 2025-01-01
    python withings_download.py --days 7           # last 7 days only
    python withings_download.py --out other.csv --reauth
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
TOKEN_FILE = HERE / "withings_tokens.json"
DEFAULT_OUT = HERE / "withings_weights.csv"
DEFAULT_REDIRECT_URI = "http://localhost:8765/callback"

AUTH_URL = "https://account.withings.com/oauth2_user/authorize2"
API_BASE = "https://wbsapi.withings.net"
OAUTH_PATH = "/v2/oauth2"
MEASURE_PATH = "/measure"

SCOPE = "user.metrics"
WEIGHT_TYPE = 1       # Withings measure type for weight
CATEGORY_REAL = 1     # real measurements (2 would be user objectives)
REFRESH_MARGIN_S = 300  # refresh the access token when it has < 5 min left
RATE_LIMIT_STATUS = 601
MAX_RATE_LIMIT_RETRIES = 5
EARLIEST = date(2000, 1, 1)


class WithingsError(RuntimeError):
    """Withings answered with a non-zero status."""


# --------------------------------------------------------------------------- http

def api_request(path: str, params: dict, access_token: str | None = None) -> dict:
    """POST to the Withings API and return the 'body' of a successful response."""
    body = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(API_BASE + path, data=body, method="POST")
    if access_token:
        req.add_header("Authorization", f"Bearer {access_token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    status = payload.get("status")
    if status != 0:
        raise WithingsError(f"Withings API status {status} for action={params.get('action')}: "
                            f"{payload.get('error', 'no error message')}")
    return payload.get("body", {})


def api_request_with_retry(path: str, params: dict, access_token: str) -> dict:
    """Like api_request, but waits and retries when Withings rate-limits us."""
    for attempt in range(1, MAX_RATE_LIMIT_RETRIES + 1):
        try:
            return api_request(path, params, access_token)
        except WithingsError as e:
            if f"status {RATE_LIMIT_STATUS} " not in str(e) or attempt == MAX_RATE_LIMIT_RETRIES:
                raise
            wait = 30 * attempt
            print(f"Rate limited; waiting {wait}s before retry {attempt}...", file=sys.stderr)
            time.sleep(wait)
    raise AssertionError("unreachable")


# --------------------------------------------------------------------------- tokens

def load_tokens() -> dict | None:
    if not TOKEN_FILE.exists():
        return None
    return json.loads(TOKEN_FILE.read_text())


def save_tokens(tokens: dict) -> None:
    # Owner-only permissions: the file grants access to your health data.
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(tokens, f, indent=2)


def tokens_from_body(body: dict) -> dict:
    return {
        "userid": body.get("userid"),
        "access_token": body["access_token"],
        "refresh_token": body["refresh_token"],
        "expires_at": time.time() + int(body.get("expires_in", 10800)),
    }


def authorize(client_id: str, redirect_uri: str) -> dict:
    """Run the browser authorization flow and return fresh tokens."""
    state = secrets.token_urlsafe(16)
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "scope": SCOPE,
        "redirect_uri": redirect_uri,
        "state": state,
    })

    received: dict = {}
    callback_path = urllib.parse.urlparse(redirect_uri).path or "/"

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != callback_path:
                self.send_response(404)
                self.end_headers()
                return
            qs = urllib.parse.parse_qs(parsed.query)
            received.update({k: v[0] for k, v in qs.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Withings authorization received. You can close this tab.")

        def log_message(self, *args):  # keep the terminal quiet
            pass

    parsed_redirect = urllib.parse.urlparse(redirect_uri)
    server = HTTPServer((parsed_redirect.hostname or "localhost", parsed_redirect.port or 80),
                        CallbackHandler)
    print("Opening your browser to authorize access to Withings...")
    print(f"If it does not open, visit:\n{url}\n")
    webbrowser.open(url)
    while "code" not in received and "error" not in received:
        server.handle_request()
    server.server_close()

    if "error" in received:
        raise RuntimeError(f"Authorization failed: {received['error']}")
    if received.get("state") != state:
        raise RuntimeError("Authorization failed: state mismatch (possible CSRF); try again.")

    body = api_request(OAUTH_PATH, {
        "action": "requesttoken",
        "client_id": client_id,
        "client_secret": client_secret_from_env(),
        "grant_type": "authorization_code",
        "code": received["code"],
        "redirect_uri": redirect_uri,
    })
    tokens = tokens_from_body(body)
    save_tokens(tokens)
    print(f"Authorized (userid {tokens['userid']}); tokens saved to {TOKEN_FILE.name}.")
    return tokens


def refresh(tokens: dict, client_id: str) -> dict:
    """Exchange the refresh token. Withings rotates it, so the new one must be saved."""
    body = api_request(OAUTH_PATH, {
        "action": "requesttoken",
        "client_id": client_id,
        "client_secret": client_secret_from_env(),
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
    })
    new_tokens = tokens_from_body(body)
    new_tokens["userid"] = new_tokens["userid"] or tokens.get("userid")
    save_tokens(new_tokens)
    return new_tokens


def client_secret_from_env() -> str:
    return require_env("WITHINGS_CLIENT_SECRET")


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        sys.exit(f"Missing environment variable {name}. See the setup notes at the top of this file.")
    return value


def get_valid_tokens(client_id: str, redirect_uri: str, reauth: bool) -> dict:
    tokens = None if reauth else load_tokens()
    if tokens is None:
        return authorize(client_id, redirect_uri)
    if tokens["expires_at"] - time.time() < REFRESH_MARGIN_S:
        print("Access token expired; refreshing.")
        tokens = refresh(tokens, client_id)
    return tokens


# --------------------------------------------------------------------------- fetch

def fetch_weights(access_token: str, start_ts: int, end_ts: int) -> list[dict]:
    """Return one row per weigh-in between start_ts and end_ts (UNIX seconds)."""
    rows: dict[str, dict] = {}
    offset = None
    while True:
        params = {
            "action": "getmeas",
            "meastypes": WEIGHT_TYPE,
            "category": CATEGORY_REAL,
            "startdate": start_ts,
            "enddate": end_ts,
        }
        if offset is not None:
            params["offset"] = offset
        body = api_request_with_retry(MEASURE_PATH, params, access_token)

        zone = ZoneInfo(body.get("timezone") or "UTC")
        for grp in body.get("measuregrps", []):
            weight = next((m for m in grp.get("measures", []) if m.get("type") == WEIGHT_TYPE), None)
            if weight is None:
                continue
            # Real value = value * 10^unit, e.g. 7500 with unit -2 -> 75.00 kg.
            weight_kg = round(weight["value"] * 10 ** weight["unit"], 3)
            local = datetime.fromtimestamp(grp["date"], tz=zone)
            rows[str(grp["grpid"])] = {
                "date": local.date().isoformat(),
                "time": local.strftime("%H:%M:%S"),
                "weight_kg": weight_kg,
                "timestamp": grp["date"],
                "grpid": grp["grpid"],
            }

        if not body.get("more"):
            break
        offset = body.get("offset")

    return sorted(rows.values(), key=lambda r: r["timestamp"])


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "time", "weight_kg", "timestamp", "grpid"])
        writer.writeheader()
        writer.writerows(rows)


# --------------------------------------------------------------------------- main

def parse_day(text: str) -> date:
    return datetime.strptime(text, "%Y-%m-%d").date()


def main() -> None:
    ap = argparse.ArgumentParser(description="Download Withings weight measurements to CSV.")
    ap.add_argument("--since", type=parse_day, default=None, metavar="YYYY-MM-DD",
                    help="first day to include (UTC, default: 2000-01-01)")
    ap.add_argument("--until", type=parse_day, default=None, metavar="YYYY-MM-DD",
                    help="last day to include (UTC, default: today)")
    ap.add_argument("--days", type=int, default=None, metavar="N",
                    help="only the last N days, including today (faster than a full download)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output CSV path")
    ap.add_argument("--reauth", action="store_true",
                    help="ignore saved tokens and authorize again in the browser")
    args = ap.parse_args()

    client_id = require_env("WITHINGS_CLIENT_ID")
    redirect_uri = os.getenv("WITHINGS_REDIRECT_URI", DEFAULT_REDIRECT_URI)

    if args.days is not None and (args.days < 1 or args.since or args.until):
        ap.error("--days must be >= 1 and cannot be combined with --since or --until")

    until = args.until or datetime.now(timezone.utc).date()
    since = args.since or EARLIEST
    if args.days is not None:
        since = until - timedelta(days=args.days - 1)
    if since > until:
        ap.error("--since must not be after --until")
    start_ts = int(datetime.combine(since, datetime.min.time(), timezone.utc).timestamp())
    end_ts = int(datetime.combine(until + timedelta(days=1), datetime.min.time(),
                                  timezone.utc).timestamp()) - 1

    tokens = get_valid_tokens(client_id, redirect_uri, args.reauth)

    print(f"Fetching weights {since} .. {until} ...")
    rows = fetch_weights(tokens["access_token"], start_ts, end_ts)
    write_csv(args.out, rows)

    print(f"Wrote {len(rows)} weigh-ins to {args.out}")
    if rows:
        print(f"  first: {rows[0]['date']} {rows[0]['time']}  last: {rows[-1]['date']} {rows[-1]['time']}")


if __name__ == "__main__":
    try:
        main()
    except (WithingsError, RuntimeError, urllib.error.URLError) as e:
        sys.exit(f"Error: {e}")
    except KeyboardInterrupt:
        sys.exit("\nInterrupted.")
