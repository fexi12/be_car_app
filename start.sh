#!/usr/bin/env sh
set -eu
PORT="${PORT:-8080}"
exec gunicorn -w 2 -b "0.0.0.0:${PORT}" car.app:app
