#!/usr/bin/env sh
# Single-container startup for Hugging Face Spaces (and any one-process host):
# Redis must live INSIDE this container because a Space exposes only one service
# on one port. We launch an in-memory Redis in the background, then hand the
# foreground (PID 1 signal handling) to uvicorn via exec.
set -e

# In-memory only: no RDB/AOF persistence (the queue is rebuilt from Postgres on
# startup), bound to localhost since only this container's workers use it.
redis-server \
  --save "" \
  --appendonly no \
  --bind 127.0.0.1 \
  --port 6379 \
  --dir /tmp \
  --daemonize no &
REDIS_PID=$!

# Give Redis a moment and verify it actually came up; fail fast if not so the
# Space logs show a clear cause instead of opaque enqueue errors later.
for i in $(seq 1 20); do
  if redis-cli -h 127.0.0.1 -p 6379 ping >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$REDIS_PID" 2>/dev/null; then
    echo "redis-server exited during startup" >&2
    exit 1
  fi
  sleep 0.25
done

PORT="${APP_PORT:-8000}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"
