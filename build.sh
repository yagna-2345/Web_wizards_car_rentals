#!/usr/bin/env bash
# exit on error
set -o errexit

# Install dependencies
pip install -r requirements.txt

# Compile and collect static assets
python manage.py collectstatic --no-input

# Run database migrations
python manage.py migrate

# Seed default administrator credentials
python create_admin.py
