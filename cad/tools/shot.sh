#!/bin/bash
# usage: shot.sh out.png "query-string" [WxH]   (server must serve repo root on :8765)
CH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
"$CH" --headless=new --disable-gpu-sandbox --use-angle=swiftshader --enable-unsafe-swiftshader --hide-scrollbars \
  --window-size=${3:-700,700} --virtual-time-budget=20000 --screenshot="$1" \
  "http://127.0.0.1:8765/cad/tools/view.html?$2" >/dev/null 2>&1
