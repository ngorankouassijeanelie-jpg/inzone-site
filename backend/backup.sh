#!/bin/sh
# Sauvegarde SQLite + uploads (à mettre en cron quotidien).
# Exemple cron : 0 2 * * * /srv/inzone/backend/backup.sh
set -e
D=$(dirname "$0")
DAY=$(date +%F)
mkdir -p "$D/backups"
"$D/venv/bin/python" -c "
import sqlite3
src = sqlite3.connect('$D/inzone.db')
dst = sqlite3.connect('$D/backups/inzone-$DAY.db')
src.backup(dst); dst.close(); src.close()
print('base sauvegardee')"
tar -czf "$D/backups/uploads-$DAY.tar.gz" -C "$D" uploads
ls -t "$D"/backups/inzone-*.db | tail -n +8 | xargs -r rm
ls -t "$D"/backups/uploads-*.tar.gz | tail -n +8 | xargs -r rm
echo "OK $DAY (7 derniers jours conserves)"
