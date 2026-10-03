#!/usr/bin/env bash
# Local setup:  ./setup.sh [--demo] [--no-run]
set -euo pipefail
cd "$(dirname "$0")"
DEMO=""; RUN=1
for a in "$@"; do case $a in --demo) DEMO="--demo";; --no-run) RUN=0;; esac; done

python3 -m venv .venv
. .venv/bin/activate
pip install -q --upgrade pip
# psycopg is only needed for PostgreSQL; install it but don't fail local SQLite setup if it can't build
grep -v '^psycopg' requirements.txt | pip install -q -r /dev/stdin
pip install -q "psycopg[binary]>=3.1" || echo "(psycopg not installed - SQLite mode only)"

python manage.py migrate --noinput
python manage.py seed_defaults $DEMO
if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ]; then
  python manage.py createsuperuser --noinput || true
else
  echo "Create an admin with:  python manage.py createsuperuser"
fi
if [ "$RUN" = "1" ]; then python manage.py runserver 0.0.0.0:8000; fi
