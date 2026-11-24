#!/usr/bin/env python3
"""Download all access control events of a given day from a Hikvision
terminal (e.g. DS-K1T671MF-L) via ISAPI and save them as <ip>_<YYYYMMDD>.csv.

Usage:
    python3 hik_events_day.py 192.168.1.50:80 2026-11-24
    python3 hik_events_day.py ddns.example.com:8080 2026-11-24 --user admin --https --insecure
    python3 hik_events_day.py 192.168.1.50:80 2026-11-24 --face-only -p SENHA
"""
import argparse
import csv
import getpass
import json
import re
import sys
import uuid
from datetime import datetime

import requests
import urllib3
from requests.auth import HTTPDigestAuth

PAGE_SIZE = 30  # most firmwares cap maxResults at 30
MAJOR_LABELS = {1: "alarm", 2: "exception", 3: "operation", 5: "event"}
FACE_MAJOR, FACE_MINOR = 5, 75  # event / "Face Authentication Passed"
PREFERRED_FIELDS = [
    "time", "major", "major_label", "minor", "minor_hex", "employeeNoString",
    "name", "cardNo", "cardType", "cardReaderNo", "doorNo", "currentVerifyMode",
    "attendanceStatus", "userType", "mask", "serialNo", "pictureURL",
]


def device_utc_offset(session, base_url):
    """Read the device's local time and return its UTC offset (e.g. '-03:00')."""
    r = session.get(f"{base_url}/ISAPI/System/time", timeout=10)
    r.raise_for_status()
    m = re.search(r"<localTime>([^<]+)</localTime>", r.text)
    if m:
        off = re.search(r"([+-]\d{2}:\d{2})$", m.group(1).strip())
        if off:
            return off.group(1)
    return None


def fetch_events(session, base_url, start, end, major=0, minor=0):
    url = f"{base_url}/ISAPI/AccessControl/AcsEvent?format=json"
    search_id = str(uuid.uuid4())
    pos = 0
    while True:
        body = {"AcsEventCond": {
            "searchID": search_id,
            "searchResultPosition": pos,
            "maxResults": PAGE_SIZE,
            "major": major,
            "minor": minor,
            "startTime": start,
            "endTime": end,
        }}
        r = session.post(url, json=body, timeout=20)
        r.raise_for_status()
        data = r.json().get("AcsEvent", {})
        items = data.get("InfoList", [])
        yield from items
        total = data.get("totalMatches", "?")
        # Guard against firmwares that report numOfMatches=0 alongside a non-empty
        # InfoList (would stall pos and loop forever) and against firmwares that
        # keep returning "MORE" on the last page (would never break on that alone).
        advance = data.get("numOfMatches") or len(items)
        pos += advance
        print(f"\r{pos}/{total} events", end="", file=sys.stderr, flush=True)
        if advance == 0 or data.get("responseStatusStrg") != "MORE":
            break
    print(file=sys.stderr)


def normalize(ev):
    row = {}
    for k, v in ev.items():
        row[k] = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
    major, minor = ev.get("major"), ev.get("minor")
    row["major_label"] = MAJOR_LABELS.get(major, "")
    row["minor_hex"] = f"0x{minor:02X}" if isinstance(minor, int) else ""
    return row


def main():
    p = argparse.ArgumentParser(description="Export one day of Hikvision ISAPI access events to CSV.")
    p.add_argument("host", help="ip:port (port defaults to 80, or 443 with --https)")
    p.add_argument("date", help="YYYY-MM-DD")
    p.add_argument("--user", default="admin")
    p.add_argument("-p", "--password", help="device password (prompted if omitted)")
    p.add_argument("--https", action="store_true", help="use HTTPS")
    p.add_argument("--insecure", action="store_true",
                   help="skip TLS certificate verification (self-signed device certs)")
    p.add_argument("--tz", help="UTC offset override, e.g. -03:00 (default: read from device)")
    p.add_argument("-d", "--delimiter", default=",", help="CSV delimiter (use ';' for Excel pt-BR)")
    p.add_argument("--face-only", action="store_true",
                   help="ask the device to return only successful face-read events "
                        f"(major={FACE_MAJOR}, minor={FACE_MINOR})")
    args = p.parse_args()

    try:
        day = datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError:
        sys.exit("error: date must be YYYY-MM-DD")

    password = args.password or getpass.getpass("Password: ")

    ip_safe = re.sub(r"[^\w.\-]", "_", args.host.split(":")[0])
    scheme = "https" if args.https else "http"
    base_url = f"{scheme}://{args.host}"

    session = requests.Session()
    session.auth = HTTPDigestAuth(args.user, password)
    session.verify = not args.insecure
    if not session.verify:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    try:
        offset = args.tz or device_utc_offset(session, base_url)
        if offset is None:
            offset = "-03:00"
            print(f"warning: could not read device timezone, defaulting to {offset}; "
                  "pass --tz to override", file=sys.stderr)
        start = f"{args.date}T00:00:00{offset}"
        end = f"{args.date}T23:59:59{offset}"
        major, minor = (FACE_MAJOR, FACE_MINOR) if args.face_only else (0, 0)
        filter_desc = f" (major={major}, minor={minor})" if args.face_only else ""
        print(f"Querying {base_url} from {start} to {end}{filter_desc}", file=sys.stderr)
        rows = [normalize(ev) for ev in fetch_events(session, base_url, start, end, major, minor)]
        rows.sort(key=lambda r: (r.get("time", ""), r.get("serialNo", 0)))

        extra = sorted({k for r in rows for k in r} - set(PREFERRED_FIELDS))
        fields = [f for f in PREFERRED_FIELDS if any(f in r for r in rows)] + extra

        out = f"{ip_safe}_{day:%Y%m%d}.csv"
        with open(out, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=fields or PREFERRED_FIELDS,
                                delimiter=args.delimiter, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)

        print(f"Saved {len(rows)} events to {out}", file=sys.stderr)
    except requests.HTTPError as e:
        # e.response is a Response object; its truthiness is False for 4xx/5xx,
        # so compare against None explicitly.
        if e.response is not None:
            code = e.response.status_code
            hint = " (check user/password)" if code == 401 else ""
            sys.exit(f"error: HTTP {code}{hint}: {e.response.text[:300]}")
        sys.exit(f"error: HTTP failure: {e}")
    except requests.RequestException as e:
        sys.exit(f"error: cannot reach device: {e}")


if __name__ == "__main__":
    main()
