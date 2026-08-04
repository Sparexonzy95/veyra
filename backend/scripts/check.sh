#!/usr/bin/env sh
set -eu
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
python manage.py spectacular --file openapi.yaml
python -m compileall -q .
