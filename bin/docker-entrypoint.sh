#!/bin/bash
# The image's two servers: the API (uvicorn, :8000) and the gateway that
# serves the UI and passes /api/v1 on to it (node, :3000).
#
# When either one stops, the other is stopped too and the container exits
# with that status, for its restart policy to bring both back up. Started as
# `sh -c "uvicorn ... & node ..."`, a backend that died - killed for memory
# on a big PDF - left the gateway running: the container stayed up, every
# /api/v1 call answered 504, and nothing restarted it.
set -u

# docker stop sends SIGTERM to PID 1, which is this script: pass it on.
trap 'kill -TERM $(jobs -p) 2>/dev/null' TERM INT

python3 -m uvicorn src.api.app:app --host 0.0.0.0 --port 8000 &
node dist/server.cjs &

wait -n
status=$?
kill -TERM $(jobs -p) 2>/dev/null
wait
exit "$status"
