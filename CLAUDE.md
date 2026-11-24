# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Single-file Python 3 CLI that exports one calendar day of access control events from a Hikvision terminal (tested on `DS-K1T671MF-L`) via the ISAPI HTTP endpoint `/ISAPI/AccessControl/AcsEvent` and writes them to `<ip>_<YYYYMMDD>.csv`.

No package layout, no tests, no requirements file yet — just `hik_events_day.py` plus a local `.venv/`.

## Commands

Activate the venv before anything else (Windows bash):

```bash
source .venv/Scripts/activate
```

Dependencies (only `requests` + `urllib3`, both runtime) are not pinned; install into the venv on first use:

```bash
pip install requests urllib3
```

Run against a device:

```bash
python hik_events_day.py <host:port> <YYYY-MM-DD> [-p SENHA] [--user admin] [--https] [--insecure] [--tz -03:00] [-d ';'] [--face-only]
```

Password is `getpass`-prompted when `-p` is omitted. CSV lands in the current working directory as `<ip>_<YYYYMMDD>.csv` (UTF-8 with BOM — Excel pt-BR opens cleanly with `-d ';'`).

## Architecture notes (non-obvious)

- **Timezone handling:** `device_utc_offset()` scrapes `<localTime>` from `/ISAPI/System/time` to discover the device's local offset, so start/end timestamps match the device's clock. `--tz` overrides; when the probe fails the script warns on stderr and falls back to `-03:00`. Querying with a wrong offset silently returns the wrong events, so don't bypass this logic.
- **Day boundary:** `endTime` is `T23:59:59` (whole seconds). Fractional seconds (`T23:59:59.999`) are rejected by the device's ISAPI JSON parser with `HTTP 400 badJsonContent`, so any event timestamped in the last fractional second of the day is silently dropped — acceptable tradeoff for access control logs.
- **Pagination:** ISAPI `AcsEvent` is a stateful search identified by `searchID` (a UUID generated per run). The firmware caps `maxResults` at 30 (`PAGE_SIZE`). Advance uses `advance = numOfMatches or len(items)` — this guards against two known firmware quirks: `numOfMatches=0` returned alongside a non-empty `InfoList` (would stall `pos` and loop forever) and `responseStatusStrg="MORE"` persisted on the last page. The loop breaks when `advance == 0` or the status flips. `fetch_events()` yields rows lazily — keep it a generator if touching it.
- **Auth & TLS:** HTTP Digest (`HTTPDigestAuth`), not Basic. TLS verification defaults to ON; `--insecure` flips it off and silences the urllib3 warning — required for the device's self-signed cert on direct LAN access, typically not needed behind a terminating proxy.
- **Filename safety:** the host (which comes from argv) is passed through `re.sub(r"[^\w.\-]", "_", ...)` before being used as the CSV filename, so a hostile host string cannot path-traverse.
- **Row normalization:** `normalize()` JSON-encodes nested values so every column is a scalar, then adds `major_label` (via `MAJOR_LABELS`) and `minor_hex` for readability. `PREFERRED_FIELDS` sets column order; any extra keys seen on the device are appended alphabetically — so new firmware fields surface automatically without code changes.
- **Output sort:** rows are sorted by `(time, serialNo)` after collection, not during streaming, because ISAPI does not guarantee ordering across pages.
- **HTTPError handler quirk:** `requests.Response.__bool__` returns `self.ok`, which is `False` for 4xx/5xx — so the error handler compares `e.response is not None` explicitly, otherwise the 401 hint path would be unreachable.

## Conventions specific to this repo

- Keep it a single file. Don't split into a package unless the scope clearly grows beyond "export one day to CSV".
- Prefer the standard library + `requests`. Any new dependency needs a reason.
- `print()` goes to **stderr** for progress/log lines (the CSV path is the only stdout-worthy artifact and it's written to disk, not piped). Don't introduce `logging` just for parity with other projects — `print(..., file=sys.stderr)` is the established style here.
