#!/bin/sh
set -e

# Wait for PostgreSQL
until pg_isready -h "$POSTGRES_HOST" -U "$POSTGRES_USER"; do
  echo "Waiting for postgres..."
  sleep 1
done

python manage.py makemigrations --noinput
python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec gunicorn nicolabeirer.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers 2
