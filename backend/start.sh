#!/bin/sh
# Lancement API inZONE (prod : utiliser systemd ou équivalent).
# Variables lues depuis l'environnement (voir .env.example).
set -e
D=$(dirname "$0")
cd "$D"
if [ -f .env ]; then set -a; . ./.env; set +a; fi
exec ./venv/bin/uvicorn app:app --host 127.0.0.1 --port 8001 --workers 2
