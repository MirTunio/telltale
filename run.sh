#!/usr/bin/env bash
# Telltale - launch the command-line app.
cd "$(dirname "$0")"
if command -v python3 >/dev/null 2>&1; then
    exec python3 telltale.py
elif command -v python >/dev/null 2>&1; then
    exec python telltale.py
else
    echo "Python 3 was not found. Install it from https://www.python.org/downloads/"
    exit 1
fi
