#!/bin/sh
set -eu

cd "$(dirname "$0")/.."
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
REPORT_URL="file://$(pwd)/examples/out/kev-report.html"

"$CHROME" --headless=new --force-light-mode --screenshot=docs/report.png --window-size=1200,900 --hide-scrollbars "$REPORT_URL"
