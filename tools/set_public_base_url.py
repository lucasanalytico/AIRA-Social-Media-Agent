"""Rewrite PUBLIC_BASE_URL=... in .env to the URL passed on the command line."""
import pathlib
import re
import sys


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: set_public_base_url.py <url>", file=sys.stderr)
        return 1
    url = sys.argv[1].rstrip("/")
    p = pathlib.Path(__file__).resolve().parent.parent / ".env"
    if not p.exists():
        print(f"no .env at {p}", file=sys.stderr)
        return 1
    text = p.read_text(encoding="utf-8")
    if re.search(r"^PUBLIC_BASE_URL=", text, flags=re.M):
        text = re.sub(r"^PUBLIC_BASE_URL=.*$", f"PUBLIC_BASE_URL={url}", text, flags=re.M)
    else:
        text = text.rstrip() + f"\nPUBLIC_BASE_URL={url}\n"
    p.write_text(text, encoding="utf-8")
    print(f"PUBLIC_BASE_URL set to {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
