#!/bin/sh
set -eu

cd "$(dirname "$0")"
exec docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build "$@"
