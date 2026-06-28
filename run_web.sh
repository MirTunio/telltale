#!/usr/bin/env bash
# Telltale - launch the local web UI (opens in your browser).
cd "$(dirname "$0")"
if command -v python3 >/dev/null 2>&1; then
    exec python3 telltale_webui/serve.py
elif command -v python >/dev/null 2>&1; then
    exec python telltale_webui/serve.py
else
    echo "Python 3 was not found. Install it from https://www.python.org/downloads/"
    exit 1
fi
