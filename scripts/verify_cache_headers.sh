#!/bin/bash
# 驗證部署後快取標頭與新 bundle
NEWJS=$(curl -s https://kachu.tw/ | grep -o '/assets/index-[^"]*\.js' | head -1)
echo "new_bundle=$NEWJS"
echo "--- bundle headers ---"
curl -sI "https://kachu.tw$NEWJS" | grep -iE 'cache-control|HTTP/'
echo "--- health ---"
curl -s -o /dev/null -w 'https_health=%{http_code}\n' https://kachu.tw/health
echo "HEADER_VERIFY_DONE"
