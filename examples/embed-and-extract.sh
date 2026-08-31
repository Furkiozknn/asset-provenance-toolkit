#!/usr/bin/env bash
# Minimal end-to-end example: embed provenance into a PNG manually, then
# read it back. Run from the repo root after `uv sync --group dev`.
set -euo pipefail

FILE="$(mktemp --suffix=.png)"
python3 -c "from PIL import Image; Image.new('RGB', (64, 64), (255, 0, 0)).save('$FILE')"

uv run aprov embed "$FILE" \
    --capability image-generate \
    --provider flux-2 \
    --params '{"prompt": "a red sneaker on a white background", "seed": 42}'

echo "--- extracted ---"
uv run aprov extract "$FILE"

echo "--- verify ---"
uv run aprov verify "$FILE"

rm -f "$FILE"
