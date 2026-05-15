"""Dev launcher — orchestrate cloudflared + server + webhook in one process.

Replaces start_dev.bat's cmd plumbing with Python, which has none of cmd's
parenthesis-and-quote brittleness.

Flow:
  1. Spawn cloudflared as a child process, log to tunnel.log
  2. Wait for it to print a https://*.trycloudflare.com URL
  3. Write PUBLIC_BASE_URL into .env
  4. Spawn server.py as a child process (inherits the updated env vars
     via .env file load on its own boot)
  5. Register the Telegram webhook
  6. Stream both child stdouts side-by-side until Ctrl+C

Ctrl+C cleanly terminates both children. Logs end up in tunnel.log + server.log
in the repo root for post-mortem.
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENV_PATH = REPO / ".env"
TUNNEL_LOG = REPO / "tunnel.log"
SERVER_LOG = REPO / "server.log"

PYTHON = sys.executable
CLOUDFLARED = r"C:\Program Files (x86)\cloudflared\cloudflared.exe"
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def fail(msg: str, code: int = 1) -> None:
    print(f"\nERROR: {msg}\n", flush=True)
    input("Press Enter to exit...")
    sys.exit(code)


def set_public_base_url(url: str) -> None:
    text = ENV_PATH.read_text(encoding="utf-8")
    if re.search(r"^PUBLIC_BASE_URL=", text, flags=re.M):
        text = re.sub(r"^PUBLIC_BASE_URL=.*$", f"PUBLIC_BASE_URL={url}", text, flags=re.M)
    else:
        text = text.rstrip() + f"\nPUBLIC_BASE_URL={url}\n"
    ENV_PATH.write_text(text, encoding="utf-8")
    print(f"[launcher] wrote PUBLIC_BASE_URL={url} to .env", flush=True)


def stream_to(prefix: str, src, dst_path: Path):
    """Pipe a subprocess stdout into both a logfile and our own console."""
    with open(dst_path, "w", encoding="utf-8", errors="ignore") as f:
        for raw in src:
            line = raw.decode("utf-8", errors="ignore").rstrip()
            print(f"[{prefix}] {line}", flush=True)
            f.write(line + "\n")
            f.flush()


def wait_for_tunnel(proc: subprocess.Popen, timeout_s: int = 60) -> str:
    """Tail cloudflared's stdout until we see a tunnel URL or timeout."""
    deadline = time.time() + timeout_s
    buf: list[str] = []
    while time.time() < deadline:
        if proc.poll() is not None:
            fail(
                "cloudflared exited before publishing a URL. "
                "Output:\n  " + "\n  ".join(buf[-20:])
            )
        line = proc.stdout.readline()
        if not line:
            time.sleep(0.2)
            continue
        text = line.decode("utf-8", errors="ignore").rstrip()
        print(f"[cloudflared] {text}", flush=True)
        buf.append(text)
        m = URL_RE.search(text)
        if m:
            return m.group(0)
    fail(f"cloudflared didn't publish a URL within {timeout_s}s. Is your DNS / VPN OK?")


def main() -> int:
    if not Path(CLOUDFLARED).exists():
        fail(f"cloudflared not found at {CLOUDFLARED}")
    if not ENV_PATH.exists():
        fail(f".env not found at {ENV_PATH}")

    print("=== AIRA Social Media Agent — dev launcher ===\n", flush=True)

    print("[1/5] Starting cloudflared tunnel on port 10000...", flush=True)
    cf = subprocess.Popen(
        [CLOUDFLARED, "tunnel", "--url", "http://localhost:10000", "--no-autoupdate"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    )

    print("[2/5] Waiting up to 60s for the tunnel URL...", flush=True)
    tunnel_url = wait_for_tunnel(cf, timeout_s=60)
    print(f"\n[launcher] Tunnel: {tunnel_url}\n", flush=True)

    print("[3/5] Writing PUBLIC_BASE_URL into .env...", flush=True)
    set_public_base_url(tunnel_url)

    print("[4/5] Starting server.py...", flush=True)
    server_env = os.environ.copy()
    server_env["PUBLIC_BASE_URL"] = tunnel_url  # belt+suspenders alongside .env
    server_env["PYTHONIOENCODING"] = "utf-8"
    server = subprocess.Popen(
        [PYTHON, str(REPO / "server.py")],
        cwd=str(REPO),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
        env=server_env,
    )

    print("[5/5] Registering Telegram webhook...", flush=True)
    wh = subprocess.run(
        [PYTHON, str(REPO / "set_webhook.py"), tunnel_url],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )
    print(wh.stdout, flush=True)
    if wh.returncode != 0:
        print(f"[launcher] set_webhook returned {wh.returncode}: {wh.stderr}", flush=True)

    print("\n=== Ready ===", flush=True)
    print(f"   Tunnel:  {tunnel_url}", flush=True)
    print(f"   Webhook: {tunnel_url}/telegram/callback", flush=True)
    print(f"   Media:   {tunnel_url}/media/<post_id>/<n>.jpg", flush=True)
    print("\nNow message @aira_social_bot on Telegram with /start\n", flush=True)
    print("Press Ctrl+C here to stop everything.\n", flush=True)

    # Stream cloudflared + server stdout from background threads to logs.
    threading.Thread(target=stream_to, args=("cf", cf.stdout, TUNNEL_LOG), daemon=True).start()
    threading.Thread(target=stream_to, args=("srv", server.stdout, SERVER_LOG), daemon=True).start()

    def shutdown(*_):
        print("\n[launcher] shutting down...", flush=True)
        for p in (server, cf):
            try:
                p.terminate()
            except Exception:
                pass
        for p in (server, cf):
            try:
                p.wait(timeout=5)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, shutdown)

    while True:
        if cf.poll() is not None:
            print(f"[launcher] cloudflared exited (code {cf.returncode}) — stopping.", flush=True)
            shutdown()
        if server.poll() is not None:
            print(f"[launcher] server.py exited (code {server.returncode}) — stopping.", flush=True)
            shutdown()
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
