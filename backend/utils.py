"""Fonctions utilitaires pures, sans dépendance à la base ou à FastAPI.

Extrait de app.py (étape 1 d'un découpage incrémental).
"""
from datetime import datetime

from constants import EUR_TO_XOF


def eur_to_xof(montant_eur) -> int:
    return round(montant_eur * EUR_TO_XOF)


def label_prix(montant_eur) -> str:
    return (f"{montant_eur:,.0f} € HT".replace(",", " ")
            + f" (≈ {eur_to_xof(montant_eur):,} FCFA)".replace(",", " "))


def add_months(dt: datetime, months: int) -> datetime:
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    last_day = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return dt.replace(year=year, month=month, day=min(dt.day, last_day))
