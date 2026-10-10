"""Constantes métier : tarifs, barème de commission, statuts valides.

Extrait de app.py (étape 1 d'un découpage incrémental) : données pures,
sans dépendance à la base ou à FastAPI, pour que ce module reste
trivialement sûr à importer depuis n'importe où dans le backend.
"""

# ---------- tarifs (source unique, en euros, converti en FCFA au taux fixe) ----------
EUR_TO_XOF = 655.957
PLANS = {
    ("Veille", 6): 1400, ("Veille", 12): 2400,
    ("Veille Pro", 6): 3100, ("Veille Pro", 12): 5400,
}
VERIFS_INCLUSES = {("Veille", 6): 0, ("Veille", 12): 0,
                    ("Veille Pro", 6): 1, ("Veille Pro", 12): 2}
TARIF_FONDATEUR = 1800          # Veille 12 mois, 10 premiers abonnés seulement
TARIF_FONDATEUR_MAX = 10
PRIX_VERIF_SUP = 2000           # € par vérification hors formule ou au-delà de l'incluse
STATUTS_VENTE = ("Disponible", "Réservé", "Vendu")
TYPES_TERRAIN = ("Terrain privé", "Zone industrielle publique")
VERIF_STATUTS = ("Demandée", "Payée", "En cours", "Livrée")

# ---------- barème interne : reversements agents de terrain et apporteurs d'affaires ----------
BAREME_SEED = {
    "agent_terrain_signale": 20000, "agent_visite_constat": 40000,
    "agent_mise_a_jour": 5000, "agent_prime_vente_pct": 5,
    "apporteur_client_premier_pct": 12, "apporteur_client_commission_pct": 10,
    "apporteur_terrain_pct": 15,
}
