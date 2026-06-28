#!/usr/bin/env python3
"""
serve.py  -  Launch the Telltale web UI locally and open it in the browser.

Usage:
    python telltale_webui/serve.py            # default 127.0.0.1:8765, opens browser
    python telltale_webui/serve.py 8080       # custom port
    python telltale_webui/serve.py 8080 --no-browser
    python -m telltale_webui.serve            # also works

The CLI is completely unaffected - run  python telltale.py  whenever you like.
This only reads/writes the same database and files the CLI uses.
"""
import os
import sys

# allow running as a plain script (python telltale_webui/serve.py) by putting the
# project root on the path before importing the package.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from telltale_webui import server   # noqa: E402


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    port = 8765
    open_browser = True
    for a in argv:
        if a in ("--no-browser", "-n"):
            open_browser = False
        elif a.isdigit():
            port = int(a)
    server.run(port=port, open_browser=open_browser)


if __name__ == "__main__":
    main()
