#!/usr/bin/env sh
# TOD Asset Explorer - extract (first run only) and open the viewer.
# Usage: ./run.sh ["/path/to/Total Overdose"]      (the folder with TOD.exe and blocks.naz)
set -e
cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then PY=python3
elif command -v python >/dev/null 2>&1; then PY=python
else
  echo "Python 3 was not found. Install it (https://www.python.org/downloads/) and run this again."
  exit 1
fi

ASSETS="${TOD_ASSETS:-$(pwd)/assets}"

if ! find "$ASSETS" -name '*.glb' 2>/dev/null | grep -q .; then
  echo "No extracted assets found in $ASSETS."
  GAME="$1"
  if [ -z "$GAME" ]; then
    echo "Enter the Total Overdose install folder (the one that contains TOD.exe and blocks.naz)."
    printf 'Game folder: '
    read -r GAME
  fi
  if [ -z "$GAME" ]; then echo "No folder given."; exit 1; fi
  echo "Extracting models, animations and textures (about a minute)..."
  "$PY" extractor/tod_extract.py --game "$GAME" --out "$ASSETS"
fi

exec "$PY" serve.py --assets "$ASSETS" --open
