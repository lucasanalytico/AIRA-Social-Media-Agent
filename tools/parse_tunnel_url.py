"""Print the first https://*.trycloudflare.com URL found in a log file. Empty if none."""
import re
import sys


def main() -> int:
    if len(sys.argv) < 2:
        return 0
    try:
        with open(sys.argv[1], encoding="utf-8", errors="ignore") as f:
            data = f.read()
    except FileNotFoundError:
        return 0
    m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", data)
    if m:
        print(m.group(0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
