# hik_events

Export one calendar day of access control events from a Hikvision terminal (tested on `DS-K1T671MF-L`) to CSV via the ISAPI endpoint `/ISAPI/AccessControl/AcsEvent`.

Single-file Python 3 script, no package layout, no external config.

## Requirements

- Python 3.8+
- Network access to the device (LAN, VPN, or DDNS + port forward)
- Device user with permission to read `AcsEvent` (admin works)

## Install

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows (Git Bash) — use .venv/bin/activate on Linux/macOS
pip install requests urllib3
```

## Usage

```bash
python hik_events_day.py <host:port> <YYYY-MM-DD> [options]
```

Password is prompted interactively if `-p/--password` is omitted (keeps the plaintext out of `ps`, shell history, and Task Manager).

Examples:

```bash
python hik_events_day.py 192.168.1.50:80 2026-11-24
python hik_events_day.py ddns.example.com:8080 2026-11-24 --user admin --https --insecure
python hik_events_day.py 192.168.1.50:80 2026-11-24 --face-only -d ';' -p SENHA
```

Output lands in the current directory as `<ip>_<YYYYMMDD>.csv` (UTF-8 with BOM, opens cleanly in Excel pt-BR when combined with `-d ';'`).

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--user` | `admin` | ISAPI user |
| `-p`, `--password` | prompt | Device password; prompted via `getpass` if omitted |
| `--https` | off | Use HTTPS |
| `--insecure` | off | Skip TLS certificate verification (needed for the device's self-signed cert) |
| `--tz` | read from device | UTC offset override, e.g. `-03:00` |
| `-d`, `--delimiter` | `,` | CSV delimiter (`;` for Excel pt-BR) |
| `--face-only` | off | Ask the device to return only successful face-read events (`major=5, minor=75`) |

### Notes

- Authentication is HTTP Digest, not Basic.
- Timezone is auto-discovered from the device clock via `/ISAPI/System/time`; if that probe fails the script warns and falls back to `-03:00` — override with `--tz` when operating elsewhere.
- `endTime` is whole-second (`T23:59:59`); fractional seconds trigger `HTTP 400 badJsonContent` on this firmware.
- Pagination uses the ISAPI `searchID` cursor at 30 results per page (firmware cap).
- `--face-only` filters at the device, so only face events cross the wire. If your firmware uses a different code for "face passed", adjust `FACE_MAJOR, FACE_MINOR` at the top of `hik_events_day.py`.
- The host component is sanitized before being used as the CSV filename (only word chars, `.` and `-` survive) to prevent path traversal when the host string comes from an untrusted source.

### CSV columns

Rows are sorted by `(time, serialNo)`. Preferred column order:

```text
time, major, major_label, minor, minor_hex, employeeNoString, name, cardNo,
cardType, cardReaderNo, doorNo, currentVerifyMode, attendanceStatus, userType,
mask, serialNo, pictureURL
```

Any additional fields returned by the device are appended alphabetically — new firmware fields surface automatically.
