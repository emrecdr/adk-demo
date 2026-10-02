"""One-time GitHub Copilot login: `uv run python scripts/copilot_login.py`.

Copilot is the arm with no API key. GitHub's OAuth device flow prints a URL
and a short code; you approve it in a browser; the token is cached on disk,
after which every phase runs unattended. LiteLLM ships this flow but polls
for only sixty seconds per code, which is shorter than walking to a browser,
so this script runs the same flow with GitHub's own window (about fifteen
minutes), using LiteLLM's endpoints, client id, headers and token file so the
phases read the result exactly as if LiteLLM had written it.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


def token_path() -> Path:
    """Where LiteLLM caches the device-flow token, from the same variables LiteLLM reads.

    `phase_6_reviewer/config.py::copilot_token` is a copy: a phase folder must
    run on its own, so it cannot import this script.
    """
    token_dir = Path(os.getenv("GITHUB_COPILOT_TOKEN_DIR", "~/.config/litellm/github_copilot")).expanduser()
    return token_dir / os.getenv("GITHUB_COPILOT_ACCESS_TOKEN_FILE", "access-token")


def keep_private(directory: Path) -> None:
    """The token's folder readable by its owner alone. Measured before: written with the default umask, both token
    files were 0644 in a 0755 folder, readable by every account on the machine."""
    directory.chmod(0o700)
    for path in directory.iterdir():
        if path.is_file():
            path.chmod(0o600)


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # a Windows console is not UTF-8 by default
    # A flag it does not know, `--help` among them, stops here, never a login: measured, `--help` began one.
    parser = argparse.ArgumentParser(prog="copilot_login", description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--force", action="store_true", help="log in again although a token is cached")
    args = parser.parse_args(argv)
    token = token_path()
    if token.is_file() and token.stat().st_size and not args.force:  # an empty file is no token, as the phases read it
        print(f"[copilot] already authenticated: {token}")
        print("[copilot] re-authenticate with: uv run python scripts/copilot_login.py --force")
        return 0
    import httpx
    from litellm.llms.github_copilot.authenticator import (
        DEFAULT_GITHUB_ACCESS_TOKEN_URL,
        DEFAULT_GITHUB_CLIENT_ID,
        Authenticator,
    )

    auth = Authenticator()
    info = auth._get_device_code()  # LiteLLM's request: its client id, its headers
    expires_in = int(info.get("expires_in", 900))
    interval = int(info.get("interval", 5))
    # Flushed: with stdout redirected to a file, a buffered code would sit unseen until the flow ended.
    print(f"[copilot] open {info['verification_uri']} and enter the code {info['user_code']}", flush=True)
    print(
        f"[copilot] the code is valid for about {expires_in // 60} minutes; waiting for your approval...\n", flush=True
    )

    url = os.getenv("GITHUB_COPILOT_ACCESS_TOKEN_URL", DEFAULT_GITHUB_ACCESS_TOKEN_URL)
    body = {
        "client_id": os.getenv("GITHUB_COPILOT_CLIENT_ID", DEFAULT_GITHUB_CLIENT_ID),
        "device_code": info["device_code"],
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    }
    deadline = time.monotonic() + expires_in
    with httpx.Client(timeout=30) as client:
        while time.monotonic() < deadline:
            time.sleep(interval)
            data = client.post(url, headers=auth._get_github_headers(), json=body).json()
            if access_token := data.get("access_token"):
                auth._ensure_token_dir()
                token.write_text(access_token, encoding="utf-8")
                auth.get_api_key()  # exchange it once now, so a failure shows here and not in phase 1
                keep_private(token.parent)
                print(f"[copilot] done: token cached at {token}")
                return 0
            error = data.get("error")
            if error == "slow_down":
                interval += 5
            elif error != "authorization_pending":
                print(f"[copilot] GitHub answered {error!r}: {data.get('error_description', '')}", file=sys.stderr)
                return 1
    print("[copilot] the code expired before it was approved; run this again", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
