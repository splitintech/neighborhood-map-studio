#!/bin/sh
set -eu

PORT="${PORT:-3000}"
case "$PORT" in
  ''|*[!0-9]*) echo "PORT must be a decimal port number" >&2; exit 2 ;;
esac
if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
  echo "PORT must be between 1 and 65535" >&2
  exit 2
fi

exec python -m uvicorn server.map_studio.main:app \
  --host 0.0.0.0 \
  --port "$PORT" \
  --limit-concurrency 40 \
  --timeout-keep-alive 5 \
  --no-access-log \
  --proxy-headers \
  --forwarded-allow-ips "127.0.0.1"
