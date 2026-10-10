#!/usr/bin/env python3
"""Sauvegarde la base SQLite de production vers backend/backups/.

Utilise l'API de sauvegarde de sqlite3 (pas une copie de fichier brute) :
elle reste sûre même si l'API écrit dans la base pendant la sauvegarde.

Lancement manuel :      python3 backup_db.py
Programmé (cron, exemple quotidien à 3h) :
    0 3 * * *  cd /chemin/vers/inzone-site/backend && python3 backup_db.py >> backups/backup.log 2>&1

Ne supprime jamais les anciennes sauvegardes automatiquement : à nettoyer
manuellement ou via une politique de rétention séparée selon l'espace
disque disponible sur le serveur de production.
"""
import os
import sqlite3
import sys
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
SOURCE_DB = os.path.join(BASE, "inzone.db")  # chemin exact utilisé par app.py
BACKUP_DIR = os.path.join(BASE, "backups")


def backup() -> str:
    if not os.path.exists(SOURCE_DB):
        print(f"Aucune base à sauvegarder : {SOURCE_DB} n'existe pas.", file=sys.stderr)
        sys.exit(1)
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest_path = os.path.join(BACKUP_DIR, f"inzone-{stamp}.db")

    source = sqlite3.connect(SOURCE_DB)
    dest = sqlite3.connect(dest_path)
    with dest:
        source.backup(dest)
    source.close()
    dest.close()

    size_kb = os.path.getsize(dest_path) / 1024
    print(f"Sauvegarde écrite : {dest_path} ({size_kb:.0f} Ko)")
    return dest_path


if __name__ == "__main__":
    backup()
