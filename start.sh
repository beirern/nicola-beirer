#!/usr/bin/env bash
set -euo pipefail

if ! docker info > /dev/null 2>&1; then
  echo "Docker is not running. Please start Docker and try again."
  exit 1
fi

echo "Starting database..."
docker compose up -d db

echo "Waiting for PostgreSQL to be ready..."
until docker compose exec db pg_isready -U "${POSTGRES_USER:-nicola}" > /dev/null 2>&1; do
  sleep 1
done
echo "PostgreSQL is ready."

echo "Running migrations..."
docker compose run --rm web python manage.py migrate

echo "Starting web server..."
docker compose up web
