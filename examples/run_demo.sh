#!/bin/sh
set -eu

cd "$(dirname "$0")/.."
PYTHONPATH=src python -m watchkit run kev --watchlist examples/watchlist.txt --offline tests/fixtures/kev_sample.json --out examples/out/kev-report.html --state-dir examples/out/.state
