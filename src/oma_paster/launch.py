"""Start the server (if needed) and open oma-paster as a standalone Omarchy web-app window."""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
import urllib.request

URL = "http://127.0.0.1:8787"


def _up() -> bool:
    try:
        urllib.request.urlopen(f"{URL}/api/theme", timeout=0.5)
        return True
    except OSError:
        return False


def main() -> None:
    if not _up():
        subprocess.Popen(
            [sys.executable, "-m", "oma_paster.server"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        for _ in range(80):
            if _up():
                break
            time.sleep(0.25)
    if shutil.which("omarchy-launch-webapp"):
        subprocess.Popen(["omarchy-launch-webapp", URL], start_new_session=True)
    else:
        subprocess.Popen(["chromium", f"--app={URL}"], start_new_session=True)


if __name__ == "__main__":
    main()
