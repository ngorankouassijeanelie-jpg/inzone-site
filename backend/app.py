"""inZONE API v1 — FastAPI + SQLite (stdlib).

Lancement :  backend/venv/bin/uvicorn app:app --port 8001
(dev : recharger avec --reload)
"""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
import jwt
import stripe
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "inzone.db")
UPLOAD_DIR = os.path.join(BASE, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _dev_secret():
    """Secret de repli pour le développement local : généré une fois et conservé
    dans un fichier non versionné, plutôt qu'une chaîne publique écrite dans le code."""
    path = os.path.join(BASE, ".secret")
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        pass
    value = secrets.token_hex(32)
    with open(path, "w") as f:
        f.write(value)
    return value


SECRET = os.environ.get("INZONE_SECRET") or _dev_secret()
TOKEN_DAYS = 7

app = FastAPI(title="inZONE API", version="1.0.0")
CORS_ORIGINS = [o.strip() for o in os.environ.get("INZONE_CORS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,  # prod : INZONE_CORS=https://votredomaine.ci
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


# ---------- base SQLite ----------
def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db()
    c = con.cursor()
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL,
          pwd_hash TEXT NOT NULL, salt TEXT NOT NULL,
          role TEXT NOT NULL DEFAULT 'client',
          name TEXT, company TEXT, country TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS terrains(
          ref TEXT PRIMARY KEY, name TEXT, zone TEXT,
          surface_ha REAL, price_m2 INTEGER,
          status TEXT, level TEXT, point_cle TEXT);
        CREATE TABLE IF NOT EXISTS verifications(
          id INTEGER PRIMARY KEY, terrain_ref TEXT, client_email TEXT,
          level TEXT, current_step INTEGER DEFAULT 1, total_steps INTEGER DEFAULT 6,
          updated TEXT);
        CREATE TABLE IF NOT EXISTS steps(
          id INTEGER PRIMARY KEY, verif_id INTEGER,
          label TEXT, source TEXT, status TEXT, position INTEGER);
        CREATE TABLE IF NOT EXISTS demandes(
          id INTEGER PRIMARY KEY, name TEXT, email TEXT,
          objet TEXT, niveau TEXT, message TEXT,
          status TEXT DEFAULT 'Nouvelle', created TEXT);
        CREATE TABLE IF NOT EXISTS zones(
          id INTEGER PRIMARY KEY, name TEXT, surface TEXT,
          ecoulement TEXT, date_donnee TEXT, statut TEXT, maj TEXT);
        CREATE TABLE IF NOT EXISTS bulletins(
          id INTEGER PRIMARY KEY, num TEXT, date TEXT,
          title TEXT, source TEXT, status TEXT DEFAULT 'Brouillon');
        CREATE TABLE IF NOT EXISTS tarifs(
          niveau TEXT PRIMARY KEY, contenu TEXT, delai TEXT, tarif TEXT);
        CREATE TABLE IF NOT EXISTS documents(
          id INTEGER PRIMARY KEY, name TEXT, terrain TEXT,
          type TEXT, etat TEXT);
        CREATE TABLE IF NOT EXISTS photos(
          id INTEGER PRIMARY KEY, terrain_ref TEXT, file TEXT,
          original TEXT, caption TEXT, size INTEGER, created TEXT);
        CREATE TABLE IF NOT EXISTS factures(
          id INTEGER PRIMARY KEY, demande_id INTEGER, client_email TEXT,
          objet TEXT, niveau TEXT, montant TEXT,
          status TEXT DEFAULT 'Émise', created TEXT);
        CREATE TABLE IF NOT EXISTS zones_projets(
          id INTEGER PRIMARY KEY, name TEXT, surface TEXT, remarque TEXT);
        CREATE TABLE IF NOT EXISTS rubriques(
          id INTEGER PRIMARY KEY, titre TEXT, etat TEXT);
        CREATE TABLE IF NOT EXISTS reset_tokens(
          email TEXT PRIMARY KEY, token TEXT, exp INTEGER);
        CREATE TABLE IF NOT EXISTS paiements(
          id INTEGER PRIMARY KEY, facture_id INTEGER, provider TEXT,
          provider_ref TEXT, montant_xof INTEGER, status TEXT DEFAULT 'pending',
          created TEXT, updated TEXT);
        CREATE TABLE IF NOT EXISTS abonnements(
          id INTEGER PRIMARY KEY, client_email TEXT, formule TEXT, duree_mois INTEGER,
          prix_eur INTEGER, tarif_fondateur INTEGER DEFAULT 0,
          statut_paiement TEXT DEFAULT 'En attente',
          date_debut TEXT, date_fin TEXT,
          verifs_incluses_total INTEGER DEFAULT 0, verifs_incluses_utilisees INTEGER DEFAULT 0,
          facture_id INTEGER, created TEXT, updated TEXT);
        CREATE TABLE IF NOT EXISTS demandes_verification(
          id INTEGER PRIMARY KEY, terrain_ref TEXT, client_email TEXT,
          projet TEXT, secteur TEXT, delai TEXT, status TEXT DEFAULT 'Demandée',
          incluse INTEGER DEFAULT 0, facture_id INTEGER, created TEXT, updated TEXT);
        CREATE TABLE IF NOT EXISTS mises_en_relation(
          id INTEGER PRIMARY KEY, terrain_ref TEXT, client_email TEXT,
          status TEXT DEFAULT 'Demandée', issue TEXT DEFAULT 'En cours',
          commission_due TEXT, commission_encaissee TEXT,
          commission_due_eur REAL, commission_encaissee_eur REAL,
          ncc_accepted_at TEXT, ncc_expire_at TEXT, created TEXT, updated TEXT);
        CREATE TABLE IF NOT EXISTS notes_veille(
          id INTEGER PRIMARY KEY, titre TEXT, mois TEXT, texte TEXT, pdf_file TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS agents(
          id INTEGER PRIMARY KEY, nom TEXT, secteur TEXT, contact TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS taches_agents(
          id INTEGER PRIMARY KEY, agent_id INTEGER, terrain_ref TEXT, type TEXT,
          statut TEXT DEFAULT 'Soumise', montant INTEGER DEFAULT 0, created TEXT, updated TEXT);
        CREATE TABLE IF NOT EXISTS apporteurs(
          id INTEGER PRIMARY KEY, nom TEXT, type TEXT, contact TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS apports(
          id INTEGER PRIMARY KEY, apporteur_id INTEGER, type TEXT, cible TEXT,
          convention_signee TEXT DEFAULT 'non', convention_signed_at TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS bareme(cle TEXT PRIMARY KEY, valeur REAL);
        """
    )
    try:
        c.execute("ALTER TABLE factures ADD COLUMN montant_xof INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    for col in ("description TEXT", "acces TEXT", "sol TEXT", "riverains TEXT",
                "reseaux TEXT", "source_prix TEXT", "gps TEXT",
                "lat REAL", "lon REAL", "created TEXT",
                "type_terrain TEXT DEFAULT 'Terrain privé'", "atouts TEXT",
                "exemple INTEGER DEFAULT 0", "statut_vente TEXT DEFAULT 'Disponible'",
                "statut_vente_date TEXT", "commission_signed TEXT DEFAULT 'non'",
                "commission_taux REAL", "commission_signed_at TEXT",
                "commission_expire_at TEXT", "commission_payeur TEXT"):
        try:
            c.execute(f"ALTER TABLE terrains ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass
    try:
        c.execute("ALTER TABLE documents ADD COLUMN file TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE documents ADD COLUMN client_email TEXT")
    except sqlite3.OperationalError:
        pass
    for col in ("criteria TEXT", "alerts TEXT", "avatar TEXT", "ncc_accepted_at TEXT"):
        try:
            c.execute(f"ALTER TABLE users ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass
    for col in ("verif_request_id INTEGER", "abonnement_id INTEGER"):
        try:
            c.execute(f"ALTER TABLE factures ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass
    con.commit()
    if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        seed(con)
    c.execute("UPDATE terrains SET created=? WHERE created IS NULL",
              ("2026-09-01T00:00:00+00:00",))
    c.execute("UPDATE terrains SET statut_vente_date=? WHERE statut_vente_date IS NULL",
              ("2026-09-01T00:00:00+00:00",))
    con.commit()
    backfill_projets(con)
    backfill_bareme(con)
    con.close()


def hash_pwd(pwd: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pwd.encode(), salt.encode(), 200_000).hex()


def make_user(con, email, pwd, role, name, company="", country=""):
    salt = secrets.token_hex(16)
    con.execute(
        "INSERT INTO users(email,pwd_hash,salt,role,name,company,country,created)"
        " VALUES(?,?,?,?,?,?,?,?)",        (email, hash_pwd(pwd, salt), salt, role, name, company, country,
         datetime.now(timezone.utc).isoformat()),
    )


def seed(con):
    c = con.cursor()
    make_user(con, "jeaneliengoran@africandconsulting.com", "demonstration", "admin",
              "Africand Consulting", "Africand Consulting", "Côte d'Ivoire")
    make_user(con, "investisseur@exemple.ma", "demonstration", "client",
              "Investisseur exemple", "Société exemple", "Maroc")
    c.executemany(
        "INSERT INTO terrains(ref,name,zone,surface_ha,price_m2,status,level,point_cle,"
        "type_terrain,atouts,exemple) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("INZ-GBA-001", "Grand-Bassam", "Grand-Bassam", 6.0, 60000,
             "Analyse standard", "Fiche complète",
             "Adapté à la logistique et à l'industrie légère", "Terrain privé",
             "Logistique et industrie légère · Autoroute à 1,5 km · 35 min de l'aéroport", 1),
            ("INZ-ATT-002", "Attinguié", "Attinguié PK31", 8.46, None,
             "Analyse en cours", "Fiche en préparation", "À confirmer sur site", "Terrain privé",
             "Proche autoroute du Nord · Voie Y4 en construction", 0),
            ("INZ-ANY-003", "Anyama", "Anyama", 6.0, None,
             "Annoncé", "Données vendeur", "À analyser", "Terrain privé",
             "Voisin d'une cimenterie · 6 ha disponibles", 0),
        ],
    )
    c.execute(
        "INSERT INTO verifications(terrain_ref,client_email,level,current_step,total_steps,updated)"
        " VALUES(?,?,?,?,?,?)",
        ("INZ-GBA-001", "investisseur@exemple.ma", "Vérification premium",
         4, 6, "2026-10-09"),
    )
    vid = c.lastrowid
    c.executemany(
        "INSERT INTO steps(verif_id,label,source,status,position) VALUES(?,?,?,?,?)",
        [
            (vid, "Électricité : distance au réseau, capacité, délai", "CIE", "Réponse attendue", 1),
            (vid, "Eau : réseau au droit du terrain, débit", "SODECI", "À lancer", 2),
            (vid, "Vocation industrielle au plan d'urbanisme", "Administration", "À lancer", 3),
            (vid, "Constat sur site : accès, eau, occupation", "Visite sur place", "À lancer", 4),
        ],
    )
    c.executemany(
        "INSERT INTO demandes(name,email,objet,niveau,message,status,created) VALUES(?,?,?,?,?,?,?)",
        [
            ("Société exemple", "investisseur@exemple.ma", "Grand-Bassam",
             "Vérification premium d'un terrain", "8 ha, logistique, T1 2027",
             "Nouvelle", "2026-10-08"),
            ("Prospect Abidjan", "prospect@exemple.ci", "Attinguié PK31",
             "Analyse standard d'un nouveau terrain", "5 ha, industrie légère",
             "Nouvelle", "2026-10-07"),
        ],
    )
    c.executemany(
        "INSERT INTO zones(name,surface,ecoulement,date_donnee,statut,maj) VALUES(?,?,?,?,?,?)",
        [
            ("Akoupé-Zeudji PK24", "1 000 ha", "284,1 ha attribués, 173 entreprises dont 67 en activité",
             "Février 2026", "En exploitation", "À jour"),
            ("Yamoussoukro", "750 ha", "Tranche 250 ha occupée à 60 %",
             "Décembre 2025", "En extension", "À jour"),
            ("Yopougon", "469 ha", "Non publié", "Antérieure à 2025", "Réhabilitée", "À actualiser"),
            ("Plateforme PEIA, PK24", "431 ha", "Capacité de 150 unités",
             "Février 2026", "En aménagement", "À jour"),
            ("Koumassi", "120 ha", "Non publié", "Antérieure à 2025", "En réhabilitation", "À actualiser"),
            ("Vridi", "120 ha", "Non publié", "Antérieure à 2025", "En réhabilitation", "À actualiser"),
            ("Korhogo (anacarde)", "28,7 ha", "Opérateurs attendus",
             "Février 2026", "Inaugurée en 2023", "À jour"),
            ("Attinguié PK31", "Non publié", "Deux sites inaugurés en 2025 et 2026",
             "Juin 2026", "En développement", "À jour"),
        ],
    )
    c.executemany(
        "INSERT INTO bulletins(num,date,title,source,status) VALUES(?,?,?,?,?)",
        [
            ("n° 0", "Octobre 2026", "Attinguié : usine de biochar inaugurée au PK31", "Afriveille", "Publié"),
            ("n° 0", "Octobre 2026", "PK24 : 284 ha attribués, 67 entreprises en activité", "Fraternité Matin", "Publié"),
            ("n° 0", "Octobre 2026", "Y4 : section Anyama-autoroute du Nord ouverte (13 km)", "Connectionivoirienne", "Publié"),
            ("n° 0", "Octobre 2026", "Yamoussoukro : 70 ha en aménagement", "Abidjan.net", "Publié"),
            ("n° 0", "Octobre 2026", "Quatre programmes : 1 450 ha, 370 Mds FCFA", "Afrik Soir", "Publié"),
        ],
    )
    c.executemany(
        "INSERT INTO tarifs VALUES(?,?,?,?)",
        [
            ("Consultation", "Carte des zones, hectares attribués, projets, catalogue", "Immédiat", "Libre"),
            ("Analyse standard", "Fiche complète : voisinage, accès, distances, relief, vigilance", "24 à 48 h", "Sur mesure"),
            ("Vérification premium", "CIE, SODECI, urbanisme, constat sur site, localisation exacte", "1 à 3 semaines", "Sur mesure"),
            ("Veille premium", "Bulletin mensuel : lots, prix, travaux, textes", "Mensuel", "Abonnement"),
            ("Mission", "Recherche de site, étude d'implantation, notaire partenaire", "Selon projet", "Sur devis"),
        ],
    )
    c.executemany(
        "INSERT INTO documents(name,terrain,type,etat) VALUES(?,?,?,?)",
        [
            ("Analyse standard", "Grand-Bassam", "Fiche, 3 pages", "Disponible"),
            ("Rapport de vérification premium", "Grand-Bassam", "Rapport", "En préparation"),
            ("Plan et localisation exacte", "Grand-Bassam", "Plan", "Remis avec le rapport"),
            ("Analyse standard", "Attinguié", "Fiche", "En préparation"),
            ("Bulletin de veille n° 0", "Toutes zones", "Bulletin, octobre 2026", "Disponible"),
        ],
    )
    con.commit()


PROJETS_SEED = [
    ("Ville industrielle du PK50", "1 500 ha", "Futur site phare, logements et services"),
    ("San Pedro", "540 ha", "Parcelle déclarée d'utilité publique"),
    ("Yamoussoukro, programme complet", "500 ha", ""),
    ("Bonoua", "329 ha", "Réserve déclarée d'utilité publique"),
    ("Adzopé", "300 ha", "432 ha selon une autre source"),
    ("Bouaké", "150 ha", "Parcelle réservée par décret"),
    ("Assouba", "23 ha", ""),
    ("Bondoukou et Séguéla (anacarde)", "15 ha chacune", ""),
    ("Ferkessédougou, Abengourou, Daloa, Mankono, M'Bengué", "Non publié", "Annoncées à l'horizon 2030"),
]


RUBRIQUES_SEED = [
    ("Lots attribués non mis en valeur", "En attente des données de la SOGEDI"),
    ("Attributions et retraits de lots", "En attente des données de la SOGEDI"),
    ("Nouveaux terrains privés en bordure des zones", "Ouverte"),
    ("Prix constatés, zone par zone", "Ouverte"),
    ("Avancement réel des routes et des réseaux", "Ouverte"),
    ("Textes et décisions du Conseil des ministres", "Ouverte"),
]


def backfill_projets(con):
    if con.execute("SELECT COUNT(*) FROM zones_projets").fetchone()[0] == 0:
        con.executemany(
            "INSERT INTO zones_projets(name,surface,remarque) VALUES(?,?,?)",
            PROJETS_SEED)
        con.commit()
    if con.execute("SELECT COUNT(*) FROM rubriques").fetchone()[0] == 0:
        con.executemany(
            "INSERT INTO rubriques(titre,etat) VALUES(?,?)",
            RUBRIQUES_SEED)
        con.commit()


BAREME_SEED = {
    "agent_terrain_signale": 20000, "agent_visite_constat": 40000,
    "agent_mise_a_jour": 5000, "agent_prime_vente_pct": 5,
    "apporteur_client_premier_pct": 12, "apporteur_client_commission_pct": 10,
    "apporteur_terrain_pct": 15,
}


def backfill_bareme(con):
    if con.execute("SELECT COUNT(*) FROM bareme").fetchone()[0] == 0:
        con.executemany(
            "INSERT INTO bareme(cle,valeur) VALUES(?,?)",
            list(BAREME_SEED.items()))
        con.commit()


# ---------- auth ----------
LOGIN_ATTEMPTS: dict = {}
if not os.environ.get("INZONE_SECRET"):
    print("ATTENTION : INZONE_SECRET non défini, secret de développement généré localement utilisé.")
class Login(BaseModel):
    email: str
    password: str


def make_token(user: dict) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": user["email"], "role": user["role"], "name": user.get("name", ""),
         "iat": now, "exp": now + TOKEN_DAYS * 86400},
        SECRET, algorithm="HS256",
    )


def current_user(authorization: str = Header(default="")) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token manquant")
    try:
        data = jwt.decode(authorization[7:], SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expirée")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token invalide")
    con = db()
    row = con.execute("SELECT * FROM users WHERE email=?", (data["sub"],)).fetchone()
    con.close()
    if not row:
        raise HTTPException(status_code=401, detail="Compte introuvable")
    return dict(row)


def admin_only(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Réservé à l'administration")
    return user


def current_user_optional(authorization: str = Header(default="")) -> Optional[dict]:
    if not authorization.startswith("Bearer "):
        return None
    try:
        data = jwt.decode(authorization[7:], SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    con = db()
    row = con.execute("SELECT * FROM users WHERE email=?", (data["sub"],)).fetchone()
    con.close()
    return dict(row) if row else None


def abonnement_actif(con, email: str) -> Optional[dict]:
    row = con.execute(
        "SELECT * FROM abonnements WHERE client_email=? AND statut_paiement='Payé' "
        "AND date_fin>=? ORDER BY date_fin DESC LIMIT 1",
        (email, datetime.now(timezone.utc).date().isoformat())).fetchone()
    return dict(row) if row else None


def rows(con, q, args=()):
    return [dict(r) for r in con.execute(q, args).fetchall()]


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


def eur_to_xof(montant_eur) -> int:
    return round(montant_eur * EUR_TO_XOF)


def label_prix(montant_eur) -> str:
    return f"{montant_eur:,.0f} € HT".replace(",", " ") + f" (≈ {eur_to_xof(montant_eur):,} FCFA)".replace(",", " ")


# ---------- routes ----------
@app.on_event("startup")
def startup():
    init_db()


@app.get("/api/health")
def health():
    return {"ok": True, "service": "inZONE API v1"}


@app.post("/api/login")
def login(body: Login, request: Request):
    ip = request.client.host if request.client else "?"
    now = time.time()
    hits = LOGIN_ATTEMPTS.get(ip, [])
    hits = [t for t in hits if now - t < 60]
    if len(hits) >= 12:
        raise HTTPException(status_code=429, detail="Trop de tentatives, réessayez dans une minute")
    hits.append(now)
    LOGIN_ATTEMPTS[ip] = hits
    con = db()
    row = con.execute("SELECT * FROM users WHERE email=?",
                      (body.email.strip().lower(),)).fetchone()
    con.close()
    if not row or not hmac.compare_digest(
            hash_pwd(body.password, row["salt"]), row["pwd_hash"]):
        raise HTTPException(status_code=401, detail="Identifiants incorrects")
    user = dict(row)
    return {"token": make_token(user), "role": user["role"], "name": user["name"],
            "avatar": user.get("avatar", "")}


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    return {"email": user["email"], "role": user["role"], "name": user["name"],
            "company": user["company"], "country": user.get("country", ""),
            "criteria": user.get("criteria", ""), "alerts": user.get("alerts", ""),
            "avatar": user.get("avatar", ""), "ncc_accepted_at": user.get("ncc_accepted_at")}


@app.post("/api/me/avatar")
def upload_avatar(file: UploadFile = File(...), user: dict = Depends(current_user)):
    saved = save_upload("av-" + user["email"].replace("@", "-at-"), file, ("image/",))
    if saved["size"] > 8 * 1024 * 1024:
        try:
            os.remove(os.path.join(UPLOAD_DIR, os.path.basename(saved["file"])))
        except OSError:
            pass
        raise HTTPException(status_code=413, detail="Photo trop lourde (max 8 Mo)")
    old = user.get("avatar", "")
    con = db()
    con.execute("UPDATE users SET avatar=? WHERE email=?", (saved["file"], user["email"]))
    con.commit()
    con.close()
    if old and old.startswith("/uploads/av-"):
        try:
            os.remove(os.path.join(UPLOAD_DIR, os.path.basename(old)))
        except OSError:
            pass
    return {"avatar": saved["file"]}


class MeIn(BaseModel):
    name: str = ""
    company: str = ""
    country: str = ""
    criteria: str = ""
    alerts: str = ""


@app.put("/api/me")
def update_me(body: MeIn, user: dict = Depends(current_user)):
    sets, vals = [], []
    for f in ("name", "company", "country", "criteria", "alerts"):
        v = getattr(body, f)
        if v:
            sets.append(f"{f}=?")
            vals.append(v.strip())
    if not sets:
        raise HTTPException(status_code=422, detail="Rien à mettre à jour")
    con = db()
    con.execute(f"UPDATE users SET {', '.join(sets)} WHERE email=?",
                (*vals, user["email"]))
    con.commit()
    con.close()
    return {"email": user["email"], "updated": sets}


@app.get("/api/users")
def list_users(_: dict = Depends(admin_only)):
    con = db()
    out = rows(con, "SELECT email,name,company,country,role,created,avatar FROM users ORDER BY id")
    con.close()
    return out


# --- catalogue public ---
@app.get("/api/zones")
def zones():
    con = db()
    out = rows(con, "SELECT * FROM zones ORDER BY id")
    con.close()
    return out


@app.get("/api/zones-projets")
def zones_projets():
    con = db()
    out = rows(con, "SELECT * FROM zones_projets ORDER BY id")
    con.close()
    return out


@app.get("/api/rubriques")
def list_rubriques(_: dict = Depends(admin_only)):
    con = db()
    out = rows(con, "SELECT * FROM rubriques ORDER BY id")
    con.close()
    return out


class RubriqueIn(BaseModel):
    etat: str


@app.put("/api/rubriques/{rid}")
def update_rubrique(rid: int, body: RubriqueIn, _: dict = Depends(admin_only)):
    if len(body.etat.strip()) < 2:
        raise HTTPException(status_code=422, detail="État requis")
    con = db()
    con.execute("UPDATE rubriques SET etat=? WHERE id=?", (body.etat.strip(), rid))
    con.commit()
    con.close()
    return {"id": rid, "etat": body.etat.strip()}


@app.delete("/api/documents/{did}")
def delete_document(did: int, _: dict = Depends(admin_only)):
    con = db()
    row = con.execute("SELECT file FROM documents WHERE id=?", (did,)).fetchone()
    if not row:
        con.close()
        raise HTTPException(status_code=404, detail="Document introuvable")
    if row["file"]:
        try:
            os.remove(os.path.join(UPLOAD_DIR, os.path.basename(row["file"])))
        except OSError:
            pass
    con.execute("DELETE FROM documents WHERE id=?", (did,))
    con.commit()
    con.close()
    return {"id": did, "deleted": True}


TERRAIN_BASE_FIELDS = ("ref", "name", "zone", "surface_ha", "price_m2", "status", "level",
                       "point_cle", "type_terrain", "statut_vente", "statut_vente_date",
                       "exemple", "created")
TERRAIN_FICHE_EXTRA = ("description", "acces", "sol", "riverains", "reseaux", "atouts", "source_prix")


def terrain_list_view(row: dict, enriched: bool) -> dict:
    out = {k: row.get(k) for k in TERRAIN_BASE_FIELDS}
    if enriched:
        out["atouts"] = row.get("atouts")
    return out


def terrain_detail_view(row: dict, unlocked: bool) -> dict:
    out = {k: row.get(k) for k in TERRAIN_BASE_FIELDS}
    if unlocked:
        for k in TERRAIN_FICHE_EXTRA:
            out[k] = row.get(k)
    out["locked"] = not unlocked
    return out


@app.get("/api/terrains")
def terrains(user: Optional[dict] = Depends(current_user_optional)):
    con = db()
    is_admin = bool(user) and user.get("role") == "admin"
    enriched = is_admin or (bool(user) and abonnement_actif(con, user["email"]) is not None)
    out = [terrain_list_view(dict(r), enriched)
           for r in con.execute("SELECT * FROM terrains").fetchall()]
    con.close()
    return out


@app.get("/api/terrains/{ref}")
def terrain(ref: str, user: Optional[dict] = Depends(current_user_optional)):
    con = db()
    row = con.execute("SELECT * FROM terrains WHERE ref=?", (ref,)).fetchone()
    if not row:
        con.close()
        raise HTTPException(status_code=404, detail="Terrain introuvable")
    row = dict(row)
    is_admin = bool(user) and user.get("role") == "admin"
    is_sub = bool(user) and abonnement_actif(con, user["email"]) is not None
    con.close()
    unlocked = is_admin or is_sub or bool(row.get("exemple"))
    return terrain_detail_view(row, unlocked)


@app.get("/api/bulletins")
def bulletins():

    con = db()
    out = rows(con, "SELECT * FROM bulletins ORDER BY id")
    con.close()
    return out


@app.get("/api/tarifs")
def tarifs():
    con = db()
    out = rows(con, "SELECT * FROM tarifs")
    con.close()
    return out


# --- demandes (dépôt public, lecture admin) ---
class DemandeIn(BaseModel):
    name: str
    email: str
    objet: str = ""
    niveau: str = ""
    message: str = ""


@app.post("/api/demandes", status_code=201)
def create_demande(body: DemandeIn):
    if len(body.name.strip()) < 2 or "@" not in body.email:
        raise HTTPException(status_code=422, detail="Nom et email valide requis")
    con = db()
    cur = con.execute(
        "INSERT INTO demandes(name,email,objet,niveau,message,status,created)"
        " VALUES(?,?,?,?,?,?,?)",
        (body.name.strip(), body.email.strip(), body.objet.strip(),
         body.niveau.strip(), body.message.strip(), "Nouvelle",
         datetime.now(timezone.utc).isoformat()),
    )
    con.commit()
    did = cur.lastrowid
    con.close()
    return {"id": did, "status": "Nouvelle"}


@app.get("/api/demandes")
def list_demandes(_: dict = Depends(admin_only)):

    con = db()
    out = rows(con, "SELECT * FROM demandes ORDER BY id DESC")
    con.close()
    return out


@app.get("/api/mes-demandes")
def mes_demandes(user: dict = Depends(current_user)):
    con = db()
    out = rows(con, "SELECT * FROM demandes WHERE email=? ORDER BY id DESC",
               (user["email"],))
    con.close()
    return out


@app.post("/api/demandes/{did}/traiter")
def traiter_demande(did: int, _: dict = Depends(admin_only)):
    con = db()
    con.execute("UPDATE demandes SET status='Traitée' WHERE id=?", (did,))
    con.commit()
    con.close()
    return {"id": did, "status": "Traitée"}


# --- espace client (connecté) ---
@app.get("/api/verifications")
def verifications(user: dict = Depends(current_user)):
    con = db()
    if user["role"] == "admin":
        verifs = rows(con, "SELECT * FROM verifications ORDER BY id DESC")
    else:
        verifs = rows(con, "SELECT * FROM verifications WHERE client_email=?",
                      (user["email"],))
    for v in verifs:
        v["steps"] = rows(con, "SELECT * FROM steps WHERE verif_id=? ORDER BY position",
                          (v["id"],))
    con.close()
    return verifs


@app.get("/api/documents")
def documents(user: dict = Depends(current_user)):
    con = db()
    if user["role"] == "admin":
        out = rows(con, "SELECT * FROM documents ORDER BY id")
    else:
        out = rows(
            con,
            "SELECT * FROM documents WHERE client_email IS NULL OR client_email=? ORDER BY id",
            (user["email"],),
        )
    con.close()
    return out


# --- admin : écriture ---
class StatutIn(BaseModel):
    status: str


class TerrainIn(BaseModel):
    name: str
    zone: str = ""
    surface_ha: float = 0
    price_m2: int = 0
    status: str = "Annoncé"
    point_cle: str = ""
    description: str = ""
    acces: str = ""
    sol: str = ""
    riverains: str = ""
    reseaux: str = ""
    source_prix: str = ""
    gps: str = ""
    type_terrain: str = "Terrain privé"
    atouts: str = ""
    exemple: int = 0


STATUTS = ("Annoncé", "Analyse en cours", "Analyse standard", "Vérifié premium")


@app.post("/api/terrains", status_code=201)
def create_terrain(body: TerrainIn, _: dict = Depends(admin_only)):
    name = body.name.strip()
    if len(name) < 2:
        raise HTTPException(status_code=422, detail="Nom du terrain requis")
    if body.status not in STATUTS:
        raise HTTPException(status_code=422, detail="Statut invalide")
    if body.type_terrain not in TYPES_TERRAIN:
        raise HTTPException(status_code=422, detail="Type de terrain invalide")
    base = "".join(ch for ch in (body.zone or name) if ch.isalnum())[:3].upper() or "GEN"
    con = db()
    n = con.execute("SELECT COUNT(*) FROM terrains").fetchone()[0] + 1
    ref = f"INZ-{base}-{n:03d}"
    while con.execute("SELECT 1 FROM terrains WHERE ref=?", (ref,)).fetchone():
        n += 1
        ref = f"INZ-{base}-{n:03d}"
    now = datetime.now(timezone.utc).isoformat()
    con.execute(
        "INSERT INTO terrains(ref,name,zone,surface_ha,price_m2,status,level,point_cle,"
        "description,acces,sol,riverains,reseaux,source_prix,gps,"
        "type_terrain,atouts,exemple,created,statut_vente,statut_vente_date)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (ref, name, body.zone.strip(), body.surface_ha or None,
         body.price_m2 or None, body.status, "", body.point_cle.strip(),
         body.description.strip(), body.acces.strip(), body.sol.strip(),
         body.riverains.strip(), body.reseaux.strip(),
         body.source_prix.strip(), body.gps.strip(),
         body.type_terrain, body.atouts.strip(), 1 if body.exemple else 0, now,
         "Disponible", now),
    )
    con.commit()
    con.close()
    return {"ref": ref, "status": body.status}


class TerrainPatch(BaseModel):
    status: str = ""
    name: str = ""
    zone: str = ""
    surface_ha: float = -1
    price_m2: int = -1
    point_cle: str = ""
    description: str = ""
    acces: str = ""
    sol: str = ""
    riverains: str = ""
    reseaux: str = ""
    source_prix: str = ""
    gps: str = ""
    type_terrain: str = ""
    atouts: str = ""
    exemple: int = -1
    statut_vente: str = ""


@app.put("/api/terrains/{ref}")
def update_terrain(ref: str, body: TerrainPatch, _: dict = Depends(admin_only)):
    con = db()
    cur = con.execute("SELECT statut_vente FROM terrains WHERE ref=?", (ref,)).fetchone()
    if not cur:
        con.close()
        raise HTTPException(status_code=404, detail="Terrain introuvable")
    sets, vals = [], []
    if body.status:
        if body.status not in STATUTS:
            con.close()
            raise HTTPException(status_code=422, detail="Statut invalide")
        sets.append("status=?")
        vals.append(body.status)
    if body.type_terrain:
        if body.type_terrain not in TYPES_TERRAIN:
            con.close()
            raise HTTPException(status_code=422, detail="Type de terrain invalide")
        sets.append("type_terrain=?")
        vals.append(body.type_terrain)
    if body.statut_vente:
        if body.statut_vente not in STATUTS_VENTE:
            con.close()
            raise HTTPException(status_code=422, detail="Statut de vente invalide")
        sets.append("statut_vente=?")
        vals.append(body.statut_vente)
        if body.statut_vente != cur["statut_vente"]:
            sets.append("statut_vente_date=?")
            vals.append(datetime.now(timezone.utc).isoformat())
    for f in ("name", "zone", "point_cle", "description", "acces", "sol",
              "riverains", "reseaux", "source_prix", "gps", "atouts"):
        v = getattr(body, f)
        if v:
            sets.append(f"{f}=?")
            vals.append(v.strip())
    if body.exemple >= 0:
        sets.append("exemple=?")
        vals.append(1 if body.exemple else 0)
    if body.surface_ha >= 0:
        sets.append("surface_ha=?")
        vals.append(body.surface_ha or None)
    if body.price_m2 >= 0:
        sets.append("price_m2=?")
        vals.append(body.price_m2 or None)
    if not sets:
        con.close()
        raise HTTPException(status_code=422, detail="Rien à mettre à jour")
    con.execute(f"UPDATE terrains SET {', '.join(sets)} WHERE ref=?", (*vals, ref))
    con.commit()
    con.close()
    return {"ref": ref, "updated": sets}


COMMISSION_FIELDS = ("commission_signed", "commission_taux", "commission_signed_at",
                     "commission_expire_at", "commission_payeur")


class CommissionIn(BaseModel):
    commission_signed: str = "non"
    commission_taux: float = 0
    commission_signed_at: str = ""
    commission_expire_at: str = ""
    commission_payeur: str = ""


@app.get("/api/terrains/{ref}/commission")
def get_commission(ref: str, _: dict = Depends(admin_only)):
    con = db()
    row = con.execute(f"SELECT {','.join(COMMISSION_FIELDS)} FROM terrains WHERE ref=?",
                      (ref,)).fetchone()
    con.close()
    if not row:
        raise HTTPException(status_code=404, detail="Terrain introuvable")
    return dict(row)


@app.put("/api/terrains/{ref}/commission")
def put_commission(ref: str, body: CommissionIn, _: dict = Depends(admin_only)):
    if body.commission_signed not in ("oui", "non"):
        raise HTTPException(status_code=422, detail="Valeur invalide pour l'accord signé")
    if body.commission_signed == "oui" and not (1 <= body.commission_taux <= 3):
        raise HTTPException(status_code=422, detail="Taux de commission entre 1 et 3")
    if body.commission_payeur and body.commission_payeur not in ("Propriétaire", "Mandataire"):
        raise HTTPException(status_code=422, detail="Payeur invalide")
    con = db()
    t = con.execute("SELECT 1 FROM terrains WHERE ref=?", (ref,)).fetchone()
    if not t:
        con.close()
        raise HTTPException(status_code=404, detail="Terrain introuvable")
    con.execute(
        "UPDATE terrains SET commission_signed=?, commission_taux=?, commission_signed_at=?, "
        "commission_expire_at=?, commission_payeur=? WHERE ref=?",
        (body.commission_signed, body.commission_taux or None,
         body.commission_signed_at.strip() or None, body.commission_expire_at.strip() or None,
         body.commission_payeur.strip() or None, ref))
    con.commit()
    con.close()
    return {"ref": ref, "commission_signed": body.commission_signed}


@app.delete("/api/terrains/{ref}")
def delete_terrain(ref: str, _: dict = Depends(admin_only)):
    con = db()
    t = con.execute("SELECT name FROM terrains WHERE ref=?", (ref,)).fetchone()
    if not t:
        con.close()
        raise HTTPException(status_code=404, detail="Terrain introuvable")
    for (f,) in con.execute("SELECT file FROM photos WHERE terrain_ref=?", (ref,)).fetchall():
        try:
            os.remove(os.path.join(UPLOAD_DIR, os.path.basename(f)))
        except OSError:
            pass
    vids = [r[0] for r in con.execute(
        "SELECT id FROM verifications WHERE terrain_ref=?", (ref,)).fetchall()]
    for vid in vids:
        con.execute("DELETE FROM steps WHERE verif_id=?", (vid,))
    con.execute("DELETE FROM verifications WHERE terrain_ref=?", (ref,))
    con.execute("DELETE FROM photos WHERE terrain_ref=?", (ref,))
    con.execute("DELETE FROM documents WHERE terrain=?", (t["name"],))
    con.execute("DELETE FROM terrains WHERE ref=?", (ref,))
    con.commit()
    con.close()
    return {"ref": ref, "deleted": True}


MAX_FILE = 8 * 1024 * 1024


def save_upload(ref: str, up: UploadFile, allowed: tuple) -> dict:
    ctype = (up.content_type or "").lower()
    if not ctype.startswith(allowed):
        raise HTTPException(status_code=422, detail=f"Fichier refusé : {up.filename}")
    data = up.file.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise HTTPException(status_code=413, detail="Fichier trop lourd (max 8 Mo)")
    if not data:
        raise HTTPException(status_code=422, detail="Fichier vide")
    ext = os.path.splitext(up.filename or "")[1].lower()[:5] or ".bin"
    fname = f"{ref}-{uuid.uuid4().hex[:8]}{ext}"
    with open(os.path.join(UPLOAD_DIR, fname), "wb") as f:
        f.write(data)
    return {"file": f"/uploads/{fname}", "size": len(data)}


@app.post("/api/terrains/{ref}/photos", status_code=201)
def upload_photo(ref: str, file: UploadFile = File(...),
                 caption: str = Form(""), _: dict = Depends(admin_only)):
    con = db()
    row = con.execute("SELECT ref FROM terrains WHERE ref=?", (ref,)).fetchone()
    if not row:
        con.close()
        raise HTTPException(status_code=404, detail="Terrain introuvable")
    saved = save_upload(ref, file, ("image/",))
    cur = con.execute(
        "INSERT INTO photos(terrain_ref,file,original,caption,size,created)"
        " VALUES(?,?,?,?,?,?)",
        (ref, saved["file"], file.filename, caption.strip(), saved["size"],
         datetime.now(timezone.utc).isoformat()),
    )
    con.commit()
    pid = cur.lastrowid
    con.close()
    return {"id": pid, "url": saved["file"]}


@app.get("/api/terrains/{ref}/photos")
def list_photos(ref: str):
    con = db()
    out = rows(con, "SELECT * FROM photos WHERE terrain_ref=? ORDER BY id", (ref,))
    con.close()
    return out


@app.get("/api/photos")
def all_photos(_: dict = Depends(admin_only)):
    con = db()
    out = rows(con, "SELECT photos.*, terrains.name AS terrain_name FROM photos"
                    " LEFT JOIN terrains ON terrains.ref=photos.terrain_ref"
                    " ORDER BY photos.id DESC")
    con.close()
    return out


@app.delete("/api/photos/{pid}")
def delete_photo(pid: int, _: dict = Depends(admin_only)):
    con = db()
    row = con.execute("SELECT file FROM photos WHERE id=?", (pid,)).fetchone()
    if not row:
        con.close()
        raise HTTPException(status_code=404, detail="Photo introuvable")
    try:
        os.remove(os.path.join(UPLOAD_DIR, os.path.basename(row["file"])))
    except OSError:
        pass
    con.execute("DELETE FROM photos WHERE id=?", (pid,))
    con.commit()
    con.close()
    return {"id": pid, "deleted": True}


@app.get("/api/terrains/{ref}/contour")
def terrain_contour(ref: str):
    """Contour de la parcelle issu du dernier KML joint, en [[lat,lon]]."""
    import xml.etree.ElementTree as ET
    con = db()
    row = con.execute(
        "SELECT file FROM documents WHERE (terrain=(SELECT name FROM terrains WHERE ref=?)"
        " OR terrain=?) AND (file LIKE '%.kml') ORDER BY id DESC LIMIT 1",
        (ref, ref)).fetchone()
    con.close()
    if not row:
        raise HTTPException(status_code=404, detail="Aucun contour KML")
    path = os.path.join(UPLOAD_DIR, os.path.basename(row["file"]))
    try:
        root = ET.parse(path).getroot()
        ns = {"k": "http://www.opengis.net/kml/2.2"}
        coords = None
        for tag in (".//k:Polygon//k:coordinates", ".//coordinates"):
            el = root.find(tag, ns) if "k:" in tag else root.find(tag)
            if el is not None and el.text and el.text.strip():
                coords = el.text.strip()
                break
        if not coords:
            raise ValueError("pas de coordonnées")
        pts = []
        for pair in coords.replace("\n", " ").split():
            parts = pair.split(",")
            lon, lat = float(parts[0]), float(parts[1])
            pts.append([lat, lon])
        if len(pts) < 3:
            raise ValueError("contour trop court")
    except Exception:
        raise HTTPException(status_code=422, detail="KML illisible")
    return {"polygon": pts}


@app.post("/api/terrains/{ref}/documents", status_code=201)
def upload_document(ref: str, file: UploadFile = File(...),
                    type: str = Form("Pièce"), client_email: str = Form(""),
                    _: dict = Depends(admin_only)):
    con = db()
    t = con.execute("SELECT name FROM terrains WHERE ref=?", (ref,)).fetchone()
    if not t:
        con.close()
        raise HTTPException(status_code=404, detail="Terrain introuvable")
    client_email = client_email.strip().lower()
    if client_email:
        u = con.execute("SELECT email FROM users WHERE email=?", (client_email,)).fetchone()
        if not u:
            con.close()
            raise HTTPException(status_code=422, detail="Client introuvable")
    ctype = (file.content_type or "").lower()
    name_low = (file.filename or "").lower()
    is_kml = name_low.endswith(".kml") or ctype == "application/vnd.google-earth.kml+xml"
    if not (ctype.startswith("image/") or ctype == "application/pdf" or is_kml):
        con.close()
        raise HTTPException(status_code=422, detail="PDF, image ou KML uniquement")
    saved = save_upload(ref, file, ("",) if is_kml else ("image/", "application/"))
    cur = con.execute(
        "INSERT INTO documents(name,terrain,type,etat,file,client_email) VALUES(?,?,?,?,?,?)",
        (file.filename, t["name"], type.strip() or "Pièce", "Disponible", saved["file"],
         client_email or None))
    con.commit()
    did = cur.lastrowid
    con.close()
    return {"id": did, "url": saved["file"], "client_email": client_email or None}


def add_months(dt: datetime, months: int) -> datetime:
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    last_day = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return dt.replace(year=year, month=month, day=min(dt.day, last_day))


def on_facture_payee(con, fid: int):
    """Répercute le paiement d'une facture sur la demande de vérification ou
    l'abonnement auxquels elle est liée (jamais de rétrogradation d'un statut déjà avancé)."""
    f = con.execute("SELECT * FROM factures WHERE id=?", (fid,)).fetchone()
    if not f:
        return
    f = dict(f)
    now = datetime.now(timezone.utc)
    if f.get("verif_request_id"):
        con.execute(
            "UPDATE demandes_verification SET status='Payée', updated=? "
            "WHERE id=? AND status='Demandée'",
            (now.isoformat(), f["verif_request_id"]))
    if f.get("abonnement_id"):
        ab = con.execute("SELECT * FROM abonnements WHERE id=?",
                         (f["abonnement_id"],)).fetchone()
        if ab and ab["statut_paiement"] != "Payé":
            date_fin = add_months(now, ab["duree_mois"] or 0)
            con.execute(
                "UPDATE abonnements SET statut_paiement='Payé', date_debut=?, "
                "date_fin=?, updated=? WHERE id=?",
                (now.date().isoformat(), date_fin.date().isoformat(),
                 now.isoformat(), ab["id"]))
    con.commit()


class FactureIn(BaseModel):
    demande_id: int
    montant: str
    montant_xof: int = 0


@app.post("/api/factures", status_code=201)
def create_facture(body: FactureIn, _: dict = Depends(admin_only)):
    if len(body.montant.strip()) < 2:
        raise HTTPException(status_code=422, detail="Montant requis")
    con = db()
    d = con.execute("SELECT * FROM demandes WHERE id=?", (body.demande_id,)).fetchone()
    if not d:
        con.close()
        raise HTTPException(status_code=404, detail="Demande introuvable")
    cur = con.execute(
        "INSERT INTO factures(demande_id,client_email,objet,niveau,montant,montant_xof,status,created)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (d["id"], d["email"], d["objet"], d["niveau"], body.montant.strip(),
         max(0, body.montant_xof), "Émise", datetime.now(timezone.utc).isoformat()),
    )
    con.commit()
    fid = cur.lastrowid
    con.close()
    return {"id": fid, "status": "Émise"}


@app.get("/api/mes-factures")
def mes_factures(user: dict = Depends(current_user)):
    con = db()
    out = rows(con, "SELECT * FROM factures WHERE client_email=? ORDER BY id DESC",
               (user["email"],))
    con.close()
    return out


@app.get("/api/factures")
def list_factures(_: dict = Depends(admin_only)):
    con = db()
    out = rows(con, "SELECT * FROM factures ORDER BY id DESC")
    con.close()
    return out


@app.put("/api/factures/{fid}")
def update_facture(fid: int, body: StatutIn, _: dict = Depends(admin_only)):
    if body.status not in ("Émise", "Payée", "Annulée"):
        raise HTTPException(status_code=422, detail="Statut invalide")
    con = db()
    con.execute("UPDATE factures SET status=? WHERE id=?", (body.status, fid))
    con.commit()
    if body.status == "Payée":
        on_facture_payee(con, fid)
    con.close()
    return {"id": fid, "status": body.status}


# --- paiement en ligne : CinetPay (Mobile Money, carte locale) et Stripe (carte internationale) ---
CINETPAY_INIT_URL = "https://api-checkout.cinetpay.com/v2/payment"
CINETPAY_CHECK_URL = "https://api-checkout.cinetpay.com/v2/payment/check"


def get_facture_for_payment(con, fid: int, user: dict) -> dict:
    row = con.execute("SELECT * FROM factures WHERE id=?", (fid,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Facture introuvable")
    f = dict(row)
    if user["role"] != "admin" and f["client_email"] != user["email"]:
        raise HTTPException(status_code=403, detail="Accès refusé")
    if f["status"] == "Payée":
        raise HTTPException(status_code=409, detail="Facture déjà payée")
    if not f.get("montant_xof"):
        raise HTTPException(status_code=422,
                            detail="Montant non défini pour le paiement en ligne, contactez l'administration")
    return f


def record_paiement(con, fid: int, provider: str, provider_ref: str, montant_xof: int):
    now = datetime.now(timezone.utc).isoformat()
    con.execute(
        "INSERT INTO paiements(facture_id,provider,provider_ref,montant_xof,status,created,updated)"
        " VALUES(?,?,?,?,?,?,?)",
        (fid, provider, provider_ref, montant_xof, "pending", now, now),
    )
    con.commit()


@app.post("/api/factures/{fid}/pay/cinetpay")
def pay_cinetpay(fid: int, user: dict = Depends(current_user)):
    apikey = os.environ.get("CINETPAY_APIKEY", "")
    site_id = os.environ.get("CINETPAY_SITE_ID", "")
    if not apikey or not site_id:
        raise HTTPException(status_code=503, detail="Paiement Mobile Money / carte locale non configuré")
    con = db()
    f = get_facture_for_payment(con, fid, user)
    base_url = os.environ.get("INZONE_URL", "http://localhost:8001").rstrip("/")
    trans_id = f"INZ{fid}T{int(time.time())}"
    payload = {
        "apikey": apikey,
        "site_id": site_id,
        "transaction_id": trans_id,
        "amount": f["montant_xof"],
        "currency": "XOF",
        "description": f"Facture inZONE n°{fid}",
        "notify_url": base_url + "/api/payments/cinetpay/notify",
        "return_url": base_url + f"/inzone-espace-client.html?paiement=retour&facture={fid}#abo",
        "channels": "ALL",
        "customer_email": f["client_email"],
    }
    try:
        r = httpx.post(CINETPAY_INIT_URL, json=payload, timeout=20)
        data = r.json()
    except Exception:
        con.close()
        raise HTTPException(status_code=502, detail="CinetPay injoignable, réessayez")
    if data.get("code") != "201":
        con.close()
        raise HTTPException(status_code=502, detail=data.get("message") or "Initialisation du paiement refusée")
    record_paiement(con, fid, "cinetpay", trans_id, f["montant_xof"])
    con.close()
    return {"url": data["data"]["payment_url"]}


@app.post("/api/payments/cinetpay/notify")
async def cinetpay_notify(request: Request):
    trans_id = ""
    try:
        form = await request.form()
        trans_id = form.get("cpm_trans_id", "")
    except Exception:
        pass
    if not trans_id:
        try:
            trans_id = (await request.json()).get("cpm_trans_id", "")
        except Exception:
            pass
    if not trans_id:
        return {"ok": False}
    apikey = os.environ.get("CINETPAY_APIKEY", "")
    site_id = os.environ.get("CINETPAY_SITE_ID", "")
    if not apikey or not site_id:
        return {"ok": False}
    try:
        r = httpx.post(CINETPAY_CHECK_URL,
                       json={"apikey": apikey, "site_id": site_id, "transaction_id": trans_id},
                       timeout=20)
        status = (r.json().get("data") or {}).get("status", "")
    except Exception:
        return {"ok": False}
    con = db()
    row = con.execute("SELECT * FROM paiements WHERE provider='cinetpay' AND provider_ref=?",
                      (trans_id,)).fetchone()
    if not row:
        con.close()
        return {"ok": False}
    row = dict(row)
    now = datetime.now(timezone.utc).isoformat()
    if status == "ACCEPTED":
        con.execute("UPDATE paiements SET status='accepted', updated=? WHERE id=?", (now, row["id"]))
        con.execute("UPDATE factures SET status='Payée' WHERE id=?", (row["facture_id"],))
        on_facture_payee(con, row["facture_id"])
    else:
        con.execute("UPDATE paiements SET status=?, updated=? WHERE id=?",
                    (status.lower() or "refused", now, row["id"]))
    con.commit()
    con.close()
    return {"ok": True}


@app.post("/api/factures/{fid}/pay/stripe")
def pay_stripe(fid: int, user: dict = Depends(current_user)):
    secret = os.environ.get("STRIPE_SECRET_KEY", "")
    if not secret:
        raise HTTPException(status_code=503, detail="Paiement par carte internationale non configuré")
    stripe.api_key = secret
    con = db()
    f = get_facture_for_payment(con, fid, user)
    base_url = os.environ.get("INZONE_URL", "http://localhost:8001").rstrip("/")
    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            payment_method_types=["card"],
            customer_email=f["client_email"],
            line_items=[{
                "quantity": 1,
                "price_data": {
                    "currency": "xof",
                    "unit_amount": f["montant_xof"],
                    "product_data": {
                        "name": f"Facture inZONE n°{fid} — {f['niveau'] or f['objet'] or 'Prestation'}",
                    },
                },
            }],
            success_url=base_url + f"/inzone-espace-client.html?paiement=succes&facture={fid}#abo",
            cancel_url=base_url + f"/inzone-espace-client.html?paiement=annule&facture={fid}#abo",
            metadata={"facture_id": str(fid)},
        )
    except Exception as e:
        con.close()
        raise HTTPException(status_code=502, detail="Stripe injoignable : " + str(e))
    record_paiement(con, fid, "stripe", session.id, f["montant_xof"])
    con.close()
    return {"url": session.url}


@app.post("/api/payments/stripe/webhook")
async def stripe_webhook(request: Request):
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if not secret:
        return {"ok": False}
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, secret)
    except Exception:
        raise HTTPException(status_code=400, detail="Signature invalide")
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        fid = (session.get("metadata") or {}).get("facture_id")
        if fid:
            con = db()
            now = datetime.now(timezone.utc).isoformat()
            con.execute(
                "UPDATE paiements SET status='accepted', updated=? WHERE provider='stripe' AND provider_ref=?",
                (now, session.get("id", "")))
            con.execute("UPDATE factures SET status='Payée' WHERE id=?", (int(fid),))
            con.commit()
            on_facture_payee(con, int(fid))
            con.close()
    return {"ok": True}


def facture_pdf_bytes(f: dict) -> bytes:
    lines = ["inZONE - Facture proforma no %d" % f["id"],
             "Africand Consulting, Abidjan",
             "Client : %s" % f["client_email"],
             "Objet : %s - %s" % (f["niveau"] or "Prestation", f["objet"] or ""),
             "Montant : %s" % f["montant"],
             "Statut : %s" % f["status"],
             "Reglement par virement. Merci."]
    content = b""
    for i, ln in enumerate(lines):
        y = 780 - i * 28
        ln = ln.encode("latin-1", "replace").replace(b"(", b"[").replace(b")", b"]")
        content += f"BT /F1 13 Tf 72 {y} Td (".encode() + ln + b") Tj ET\n"
    objs = [b"<</Type/Catalog/Pages 2 0 R>>",
            b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 4 0 R"
            b"/Resources<</Font<</F1 5 0 R>>>>>>",
            b"<</Length %d>>stream\n" % len(content) + content + b"endstream",
            b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>"]
    out = b"%PDF-1.4\n"
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj".encode() + o + b"endobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n".encode()
    for o in offs:
        out += f"{o:010d} 00000 n \n".encode()
    out += (f"trailer\n<</Size {len(objs)+1}/Root 1 0 R>>\n"
            f"startxref\n{xref}\n%%EOF").encode()
    return out


@app.get("/api/factures/{fid}/pdf")
def facture_pdf(fid: int, user: dict = Depends(current_user)):
    con = db()
    f = con.execute("SELECT * FROM factures WHERE id=?", (fid,)).fetchone()
    con.close()
    if not f:
        raise HTTPException(status_code=404, detail="Facture introuvable")
    f = dict(f)
    if user["role"] != "admin" and f["client_email"] != user["email"]:
        raise HTTPException(status_code=403, detail="Accès refusé")
    from fastapi.responses import Response
    return Response(content=facture_pdf_bytes(f), media_type="application/pdf",
                    headers={"Content-Disposition":
                             f"attachment; filename=facture-{fid}.pdf"})


@app.put("/api/steps/{sid}")
def update_step(sid: int, body: StatutIn, _: dict = Depends(admin_only)):
    con = db()
    con.execute("UPDATE steps SET status=? WHERE id=?", (body.status, sid))
    con.commit()
    con.close()
    return {"id": sid, "status": body.status}


class BulletinIn(BaseModel):
    num: str
    date: str
    title: str
    source: str


@app.post("/api/bulletins", status_code=201)
def create_bulletin(body: BulletinIn, _: dict = Depends(admin_only)):
    con = db()
    cur = con.execute(
        "INSERT INTO bulletins(num,date,title,source,status) VALUES(?,?,?,?,?)",
        (body.num, body.date, body.title, body.source, "Publié"))
    con.commit()
    bid = cur.lastrowid
    con.close()
    return {"id": bid, "status": "Publié"}


class TarifIn(BaseModel):
    tarif: str


@app.put("/api/tarifs/{niveau}")
def update_tarif(niveau: str, body: TarifIn, _: dict = Depends(admin_only)):
    con = db()
    con.execute("UPDATE tarifs SET tarif=? WHERE niveau=?", (body.tarif, niveau))
    con.commit()
    con.close()
    return {"niveau": niveau, "tarif": body.tarif}


class SignupIn(BaseModel):
    name: str
    email: str
    password: str
    company: str = ""
    country: str = ""


SIGNUP_ATTEMPTS: dict = {}


@app.post("/api/signup", status_code=201)
def signup(body: SignupIn, request: Request):
    ip = request.client.host if request.client else "?"
    now = time.time()
    hits = [t for t in SIGNUP_ATTEMPTS.get(ip, []) if now - t < 3600]
    if len(hits) >= 5:
        raise HTTPException(status_code=429,
                            detail="Trop d'inscriptions, réessayez dans une heure")
    name, email, pwd = (body.name.strip(), body.email.strip().lower(),
                        body.password)
    if len(name) < 2:
        raise HTTPException(status_code=422, detail="Nom requis")
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=422, detail="Email invalide")
    if len(pwd) < 8:
        raise HTTPException(status_code=422,
                            detail="Mot de passe : 8 caractères minimum")
    con = db()
    if con.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
        con.close()
        raise HTTPException(status_code=409, detail="Compte déjà existant, connectez-vous")
    make_user(con, email, pwd, "client", name,
              body.company.strip(), body.country.strip())
    con.commit()
    row = con.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    con.close()
    hits.append(now)
    SIGNUP_ATTEMPTS[ip] = hits
    user = dict(row)
    return {"token": make_token(user), "role": "client", "name": user["name"],
            "avatar": user.get("avatar", "")}


class ForgotIn(BaseModel):
    email: str


class ResetIn(BaseModel):
    token: str
    password: str


def send_reset_link(email: str, token: str):
    link = os.environ.get("INZONE_URL", "http://localhost:8001").rstrip("/")
    body = (f"Réinitialisation de votre mot de passe inZONE.\n\n"
            f"Lien valable 1 heure :\n{link}/inzone-espace-client.html#reset-{token}\n")
    host = os.environ.get("SMTP_HOST", "")
    if host:
        import smtplib
        from email.message import EmailMessage
        msg = EmailMessage()
        msg["From"] = os.environ.get("SMTP_FROM", "inzone@africand.com")
        msg["To"] = email
        msg["Subject"] = "inZONE — réinitialisation du mot de passe"
        msg.set_content(body)
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587"))) as s:
            s.starttls()
            if os.environ.get("SMTP_USER"):
                s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASS", ""))
            s.send_message(msg)
    else:
        with open(os.path.join(BASE, "reset-links.log"), "a") as f:
            f.write(f"{email} :: {body}\n")


@app.post("/api/forgot")
def forgot(body: ForgotIn):
    email = body.email.strip().lower()
    con = db()
    exists = con.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone()
    if exists:
        token = secrets.token_urlsafe(24)
        con.execute("INSERT OR REPLACE INTO reset_tokens(email,token,exp) VALUES(?,?,?)",
                    (email, token, int(time.time()) + 3600))
        con.commit()
        try:
            send_reset_link(email, token)
        except Exception:
            pass
    con.close()
    return {"ok": True}  # même réponse si le compte n'existe pas


@app.post("/api/reset")
def reset(body: ResetIn):
    if len(body.password) < 8:
        raise HTTPException(status_code=422,
                            detail="Mot de passe : 8 caractères minimum")
    con = db()
    row = con.execute("SELECT * FROM reset_tokens WHERE token=?",
                      (body.token.strip(),)).fetchone()
    if not row or row["exp"] < time.time():
        con.close()
        raise HTTPException(status_code=422, detail="Lien invalide ou expiré")
    salt = secrets.token_hex(16)
    con.execute("UPDATE users SET pwd_hash=?, salt=? WHERE email=?",
                (hash_pwd(body.password, salt), salt, row["email"]))
    con.execute("DELETE FROM reset_tokens WHERE email=?", (row["email"],))
    con.commit()
    con.close()
    return {"ok": True}


class UserIn(BaseModel):
    email: str
    password: str
    name: str
    company: str = ""
    country: str = ""


@app.post("/api/users", status_code=201)
def create_user(body: UserIn, _: dict = Depends(admin_only)):
    con = db()
    try:
        make_user(con, body.email.strip().lower(), body.password, "client",
                  body.name.strip(), body.company.strip(), body.country.strip())
        con.commit()
    except sqlite3.IntegrityError:
        con.close()
        raise HTTPException(status_code=409, detail="Email déjà utilisé")
    con.close()
    return {"email": body.email, "role": "client"}


# ---------- abonnements ----------
@app.get("/api/abonnements/tarifs")
def abonnements_tarifs():
    return {
        "plans": {f"{f}|{d}": p for (f, d), p in PLANS.items()},
        "verifs_incluses": {f"{f}|{d}": v for (f, d), v in VERIFS_INCLUSES.items()},
        "tarif_fondateur": TARIF_FONDATEUR,
        "tarif_fondateur_max": TARIF_FONDATEUR_MAX,
        "prix_verif_sup": PRIX_VERIF_SUP,
        "eur_to_xof": EUR_TO_XOF,
    }


class AbonnementIn(BaseModel):
    formule: str
    duree_mois: int


@app.post("/api/abonnements", status_code=201)
def create_abonnement(body: AbonnementIn, user: dict = Depends(current_user)):
    key = (body.formule, body.duree_mois)
    if key not in PLANS:
        raise HTTPException(status_code=422, detail="Formule ou durée invalide")
    con = db()
    tarif_fondateur = 0
    prix = PLANS[key]
    if body.formule == "Veille" and body.duree_mois == 12:
        n_fondateur = con.execute(
            "SELECT COUNT(*) FROM abonnements WHERE tarif_fondateur=1").fetchone()[0]
        if n_fondateur < TARIF_FONDATEUR_MAX:
            tarif_fondateur = 1
            prix = TARIF_FONDATEUR
    now = datetime.now(timezone.utc).isoformat()
    cur = con.execute(
        "INSERT INTO abonnements(client_email,formule,duree_mois,prix_eur,tarif_fondateur,"
        "statut_paiement,verifs_incluses_total,verifs_incluses_utilisees,created,updated)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (user["email"], body.formule, body.duree_mois, prix, tarif_fondateur,
         "En attente", VERIFS_INCLUSES[key], 0, now, now))
    aid = cur.lastrowid
    montant_xof = eur_to_xof(prix)
    fcur = con.execute(
        "INSERT INTO factures(demande_id,client_email,objet,niveau,montant,montant_xof,"
        "status,created,abonnement_id) VALUES(?,?,?,?,?,?,?,?,?)",
        (None, user["email"], f"Abonnement {body.formule}, {body.duree_mois} mois",
         body.formule, label_prix(prix), montant_xof, "Émise", now, aid))
    fid = fcur.lastrowid
    con.execute("UPDATE abonnements SET facture_id=? WHERE id=?", (fid, aid))
    con.commit()
    con.close()
    return {"id": aid, "facture_id": fid, "prix_eur": prix, "montant_xof": montant_xof}


class DevisIn(BaseModel):
    message: str = ""


@app.post("/api/abonnements/devis", status_code=201)
def devis_sur_mesure(body: DevisIn, user: dict = Depends(current_user)):
    con = db()
    con.execute(
        "INSERT INTO demandes(name,email,objet,niveau,message,status,created) VALUES(?,?,?,?,?,?,?)",
        (user.get("name", ""), user["email"], "Formule sur mesure", "Mission sur mesure",
         body.message.strip(), "Nouvelle", datetime.now(timezone.utc).isoformat()))
    con.commit()
    con.close()
    return {"ok": True}


@app.get("/api/abonnements/moi")
def mes_abonnements(user: dict = Depends(current_user)):
    con = db()
    out = rows(con, "SELECT * FROM abonnements WHERE client_email=? ORDER BY id DESC",
               (user["email"],))
    actif = abonnement_actif(con, user["email"])
    con.close()
    return {"historique": out, "actif": actif}


@app.get("/api/abonnements")
def list_abonnements(_: dict = Depends(admin_only)):
    con = db()
    out = rows(con, "SELECT * FROM abonnements ORDER BY id DESC")
    con.close()
    return out


class AbonnementPatch(BaseModel):
    statut_paiement: str = ""
    date_debut: str = ""
    date_fin: str = ""


@app.put("/api/abonnements/{aid}")
def update_abonnement(aid: int, body: AbonnementPatch, _: dict = Depends(admin_only)):
    sets, vals = [], []
    if body.statut_paiement:
        sets.append("statut_paiement=?")
        vals.append(body.statut_paiement)
    if body.date_debut:
        sets.append("date_debut=?")
        vals.append(body.date_debut)
    if body.date_fin:
        sets.append("date_fin=?")
        vals.append(body.date_fin)
    if not sets:
        raise HTTPException(status_code=422, detail="Rien à mettre à jour")
    con = db()
    con.execute(f"UPDATE abonnements SET {', '.join(sets)} WHERE id=?", (*vals, aid))
    con.commit()
    con.close()
    return {"id": aid, "updated": sets}


# ---------- vérifications sur site (demandes) ----------
class VerifDemandeIn(BaseModel):
    terrain_ref: str
    projet: str = ""
    secteur: str = ""
    delai: str = ""


@app.post("/api/verifications/demande", status_code=201)
def demander_verification(body: VerifDemandeIn, user: dict = Depends(current_user)):
    con = db()
    t = con.execute("SELECT name FROM terrains WHERE ref=?", (body.terrain_ref,)).fetchone()
    if not t:
        con.close()
        raise HTTPException(status_code=404, detail="Terrain introuvable")
    ab = abonnement_actif(con, user["email"])
    if not ab:
        con.close()
        raise HTTPException(status_code=403, detail="Abonnement requis")
    now = datetime.now(timezone.utc).isoformat()
    incluse = 1 if ab["verifs_incluses_utilisees"] < ab["verifs_incluses_total"] else 0
    cur = con.execute(
        "INSERT INTO demandes_verification(terrain_ref,client_email,projet,secteur,delai,"
        "status,incluse,created,updated) VALUES(?,?,?,?,?,?,?,?,?)",
        (body.terrain_ref, user["email"], body.projet.strip(), body.secteur.strip(),
         body.delai.strip(), "Demandée", incluse, now, now))
    vid = cur.lastrowid
    if incluse:
        con.execute("UPDATE abonnements SET verifs_incluses_utilisees=verifs_incluses_utilisees+1 "
                    "WHERE id=?", (ab["id"],))
        fcur = con.execute(
            "INSERT INTO factures(demande_id,client_email,objet,niveau,montant,montant_xof,"
            "status,created,verif_request_id) VALUES(?,?,?,?,?,?,?,?,?)",
            (None, user["email"], f"Vérification sur site, {t['name']}", "Vérification",
             "Incluse dans votre formule (0 €)", 0, "Payée", now, vid))
        con.execute("UPDATE demandes_verification SET status='Payée', facture_id=? WHERE id=?",
                    (fcur.lastrowid, vid))
    else:
        montant_xof = eur_to_xof(PRIX_VERIF_SUP)
        fcur = con.execute(
            "INSERT INTO factures(demande_id,client_email,objet,niveau,montant,montant_xof,"
            "status,created,verif_request_id) VALUES(?,?,?,?,?,?,?,?,?)",
            (None, user["email"], f"Vérification sur site, {t['name']}", "Vérification",
             label_prix(PRIX_VERIF_SUP), montant_xof, "Émise", now, vid))
        con.execute("UPDATE demandes_verification SET facture_id=? WHERE id=?",
                    (fcur.lastrowid, vid))
    con.commit()
    con.close()
    return {"id": vid, "incluse": bool(incluse), "status": "Payée" if incluse else "Demandée"}


@app.get("/api/verifications/demandes")
def list_verif_demandes(user: dict = Depends(current_user)):
    con = db()
    if user["role"] == "admin":
        out = rows(con, "SELECT * FROM demandes_verification ORDER BY id DESC")
    else:
        out = rows(con,
                   "SELECT * FROM demandes_verification WHERE client_email=? ORDER BY id DESC",
                   (user["email"],))
    con.close()
    return out


@app.put("/api/verifications/demandes/{vid}")
def update_verif_demande(vid: int, body: StatutIn, _: dict = Depends(admin_only)):
    if body.status not in VERIF_STATUTS:
        raise HTTPException(status_code=422, detail="Statut invalide")
    con = db()
    con.execute("UPDATE demandes_verification SET status=?, updated=? WHERE id=?",
               (body.status, datetime.now(timezone.utc).isoformat(), vid))
    con.commit()
    con.close()
    return {"id": vid, "status": body.status}


# ---------- engagement de non-contournement et mise en relation ----------
@app.post("/api/me/ncc-accept")
def ncc_accept(user: dict = Depends(current_user)):
    con = db()
    if not user.get("ncc_accepted_at"):
        now = datetime.now(timezone.utc).isoformat()
        con.execute("UPDATE users SET ncc_accepted_at=? WHERE email=?", (now, user["email"]))
        con.commit()
        accepted_at = now
    else:
        accepted_at = user["ncc_accepted_at"]
    con.close()
    return {"ncc_accepted_at": accepted_at}


class MiseEnRelationIn(BaseModel):
    terrain_ref: str


@app.post("/api/mises-en-relation", status_code=201)
def demander_mise_en_relation(body: MiseEnRelationIn, user: dict = Depends(current_user)):
    con = db()
    t = con.execute("SELECT 1 FROM terrains WHERE ref=?", (body.terrain_ref,)).fetchone()
    if not t:
        con.close()
        raise HTTPException(status_code=404, detail="Terrain introuvable")
    if not abonnement_actif(con, user["email"]):
        con.close()
        raise HTTPException(status_code=403, detail="Abonnement actif requis")
    if not user.get("ncc_accepted_at"):
        con.close()
        raise HTTPException(status_code=403,
                            detail="Engagement de non-contournement non accepté")
    now = datetime.now(timezone.utc)
    ncc_expire = add_months(now, 24)
    cur = con.execute(
        "INSERT INTO mises_en_relation(terrain_ref,client_email,status,issue,"
        "ncc_accepted_at,ncc_expire_at,created,updated) VALUES(?,?,?,?,?,?,?,?)",
        (body.terrain_ref, user["email"], "Demandée", "En cours",
         user["ncc_accepted_at"], ncc_expire.isoformat(), now.isoformat(), now.isoformat()))
    con.commit()
    mid = cur.lastrowid
    con.close()
    return {"id": mid, "ncc_expire_at": ncc_expire.isoformat()}


@app.get("/api/mises-en-relation")
def list_mises_en_relation(user: dict = Depends(current_user)):
    con = db()
    if user["role"] == "admin":
        out = rows(con, "SELECT * FROM mises_en_relation ORDER BY id DESC")
    else:
        out = rows(con,
                   "SELECT * FROM mises_en_relation WHERE client_email=? ORDER BY id DESC",
                   (user["email"],))
    con.close()
    return out


def commission_apporteur(con, cible: str, type_apporteur: str, montant_encaisse: float) -> dict:
    row = con.execute(
        "SELECT a.*, ap.nom AS apporteur_nom FROM apports a "
        "JOIN apporteurs ap ON ap.id=a.apporteur_id "
        "WHERE a.type=? AND a.cible=? ORDER BY a.created ASC LIMIT 1",
        (type_apporteur, cible)).fetchone()
    if not row:
        return {"apporteur": None, "du": 0}
    row = dict(row)
    if row["convention_signee"] != "oui":
        return {"apporteur": row["apporteur_nom"], "du": 0, "raison": "convention non signée"}
    cle = ("apporteur_terrain_pct" if type_apporteur == "Terrains"
           else "apporteur_client_commission_pct")
    taux_row = con.execute("SELECT valeur FROM bareme WHERE cle=?", (cle,)).fetchone()
    taux = taux_row["valeur"] if taux_row else 0
    return {"apporteur": row["apporteur_nom"], "du": round(montant_encaisse * taux / 100, 2)}


class MiseEnRelationPatch(BaseModel):
    status: str = ""
    issue: str = ""
    commission_due: str = ""
    commission_due_eur: float = -1
    commission_encaissee: str = ""
    commission_encaissee_eur: float = -1


@app.put("/api/mises-en-relation/{mid}")
def update_mise_en_relation(mid: int, body: MiseEnRelationPatch, _: dict = Depends(admin_only)):
    con = db()
    row = con.execute("SELECT * FROM mises_en_relation WHERE id=?", (mid,)).fetchone()
    if not row:
        con.close()
        raise HTTPException(status_code=404, detail="Mise en relation introuvable")
    row = dict(row)
    t = con.execute("SELECT commission_signed FROM terrains WHERE ref=?",
                    (row["terrain_ref"],)).fetchone()
    if body.issue and (not t or t["commission_signed"] != "oui"):
        con.close()
        raise HTTPException(status_code=403,
                            detail="Accord de commission non signé pour ce terrain. "
                                   "La mise en relation est bloquée : signez l'accord d'abord.")
    sets, vals = [], []
    if body.status:
        sets.append("status=?")
        vals.append(body.status)
    if body.issue:
        if body.issue not in ("En cours", "Vente conclue", "Sans suite"):
            con.close()
            raise HTTPException(status_code=422, detail="Issue invalide")
        sets.append("issue=?")
        vals.append(body.issue)
    if body.commission_due:
        sets.append("commission_due=?")
        vals.append(body.commission_due)
    if body.commission_due_eur >= 0:
        sets.append("commission_due_eur=?")
        vals.append(body.commission_due_eur)
    if body.commission_encaissee:
        sets.append("commission_encaissee=?")
        vals.append(body.commission_encaissee)
    if body.commission_encaissee_eur >= 0:
        sets.append("commission_encaissee_eur=?")
        vals.append(body.commission_encaissee_eur)
    if not sets:
        con.close()
        raise HTTPException(status_code=422, detail="Rien à mettre à jour")
    sets.append("updated=?")
    vals.append(datetime.now(timezone.utc).isoformat())
    con.execute(f"UPDATE mises_en_relation SET {', '.join(sets)} WHERE id=?", (*vals, mid))
    con.commit()
    apporteurs_du = {}
    if body.commission_encaissee_eur >= 0:
        apporteurs_du["terrain"] = commission_apporteur(
            con, row["terrain_ref"], "Terrains", body.commission_encaissee_eur)
        apporteurs_du["client"] = commission_apporteur(
            con, row["client_email"], "Clients", body.commission_encaissee_eur)
    con.close()
    return {"id": mid, "updated": sets, "apporteurs_du": apporteurs_du}


# ---------- notes de veille ----------
@app.post("/api/notes-veille", status_code=201)
def creer_note_veille(titre: str = Form(...), mois: str = Form(...), texte: str = Form(""),
                      pdf: Optional[UploadFile] = File(None), _: dict = Depends(admin_only)):
    con = db()
    pdf_url = None
    if pdf is not None and pdf.filename:
        saved = save_upload("veille", pdf, ("application/pdf",))
        pdf_url = saved["file"]
    con.execute(
        "INSERT INTO notes_veille(titre,mois,texte,pdf_file,created) VALUES(?,?,?,?,?)",
        (titre.strip(), mois.strip(), texte.strip(), pdf_url,
         datetime.now(timezone.utc).isoformat()))
    con.commit()
    con.close()
    return {"ok": True}


@app.get("/api/notes-veille")
def list_notes_veille(user: dict = Depends(current_user)):
    con = db()
    if user["role"] != "admin" and not abonnement_actif(con, user["email"]):
        con.close()
        raise HTTPException(status_code=403, detail="Abonnement requis")
    out = rows(con, "SELECT * FROM notes_veille ORDER BY id DESC")
    con.close()
    return out


# ---------- agents de terrain (admin uniquement) ----------
class AgentIn(BaseModel):
    nom: str
    secteur: str = ""
    contact: str = ""


@app.get("/api/agents")
def list_agents(_: dict = Depends(admin_only)):
    con = db()
    out = rows(con, "SELECT * FROM agents ORDER BY id")
    con.close()
    return out


@app.post("/api/agents", status_code=201)
def create_agent(body: AgentIn, _: dict = Depends(admin_only)):
    con = db()
    cur = con.execute("INSERT INTO agents(nom,secteur,contact,created) VALUES(?,?,?,?)",
                      (body.nom.strip(), body.secteur.strip(), body.contact.strip(),
                       datetime.now(timezone.utc).isoformat()))
    con.commit()
    agid = cur.lastrowid
    con.close()
    return {"id": agid}


TACHE_TYPES = ("Terrain signalé", "Visite de constat", "Mise à jour", "Prime de vente")
TACHE_STATUTS = ("Soumise", "Validée", "Refusée", "Payée")


class TacheIn(BaseModel):
    terrain_ref: str
    type: str
    montant: int = 0


@app.post("/api/agents/{agent_id}/taches", status_code=201)
def create_tache(agent_id: int, body: TacheIn, _: dict = Depends(admin_only)):
    if body.type not in TACHE_TYPES:
        raise HTTPException(status_code=422, detail="Type de tâche invalide")
    con = db()
    if body.type == "Terrain signalé":
        dup = con.execute(
            "SELECT 1 FROM taches_agents WHERE terrain_ref=? AND type='Terrain signalé' "
            "AND statut IN ('Soumise','Validée','Payée')", (body.terrain_ref,)).fetchone()
        if dup:
            con.close()
            raise HTTPException(status_code=422, detail="Terrain déjà signalé")
    now = datetime.now(timezone.utc).isoformat()
    cur = con.execute(
        "INSERT INTO taches_agents(agent_id,terrain_ref,type,statut,montant,created,updated)"
        " VALUES(?,?,?,?,?,?,?)",
        (agent_id, body.terrain_ref, body.type, "Soumise", body.montant, now, now))
    con.commit()
    tid = cur.lastrowid
    con.close()
    return {"id": tid}


@app.get("/api/taches-agents")
def list_taches(agent_id: int = 0, mois: str = "", _: dict = Depends(admin_only)):
    con = db()
    q = "SELECT * FROM taches_agents WHERE 1=1"
    args = []
    if agent_id:
        q += " AND agent_id=?"
        args.append(agent_id)
    if mois:
        q += " AND created LIKE ?"
        args.append(mois + "%")
    q += " ORDER BY id DESC"
    out = rows(con, q, tuple(args))
    con.close()
    return out


@app.put("/api/taches-agents/{tid}")
def update_tache(tid: int, body: StatutIn, _: dict = Depends(admin_only)):
    if body.status not in TACHE_STATUTS:
        raise HTTPException(status_code=422, detail="Statut invalide")
    con = db()
    con.execute("UPDATE taches_agents SET statut=?, updated=? WHERE id=?",
               (body.status, datetime.now(timezone.utc).isoformat(), tid))
    con.commit()
    con.close()
    return {"id": tid, "statut": body.status}


# ---------- apporteurs d'affaires (admin uniquement) ----------
class ApporteurIn(BaseModel):
    nom: str
    type: str
    contact: str = ""


@app.get("/api/apporteurs")
def list_apporteurs(_: dict = Depends(admin_only)):
    con = db()
    out = rows(con, "SELECT * FROM apporteurs ORDER BY id")
    con.close()
    return out


@app.post("/api/apporteurs", status_code=201)
def create_apporteur(body: ApporteurIn, _: dict = Depends(admin_only)):
    if body.type not in ("Clients", "Terrains"):
        raise HTTPException(status_code=422, detail="Type d'apporteur invalide")
    con = db()
    cur = con.execute("INSERT INTO apporteurs(nom,type,contact,created) VALUES(?,?,?,?)",
                      (body.nom.strip(), body.type, body.contact.strip(),
                       datetime.now(timezone.utc).isoformat()))
    con.commit()
    apoid = cur.lastrowid
    con.close()
    return {"id": apoid}


class ApportIn(BaseModel):
    apporteur_id: int
    type: str
    cible: str


@app.get("/api/apports")
def list_apports(_: dict = Depends(admin_only)):
    con = db()
    out = rows(con, "SELECT * FROM apports ORDER BY id DESC")
    con.close()
    return out


@app.post("/api/apports", status_code=201)
def create_apport(body: ApportIn, _: dict = Depends(admin_only)):
    if body.type not in ("Clients", "Terrains"):
        raise HTTPException(status_code=422, detail="Type d'apport invalide")
    con = db()
    cutoff = add_months(datetime.now(timezone.utc), -12).isoformat()
    dup = con.execute(
        "SELECT 1 FROM apports WHERE type=? AND cible=? AND created>=?",
        (body.type, body.cible, cutoff)).fetchone()
    if dup:
        con.close()
        raise HTTPException(status_code=422, detail="Déjà apporté")
    cur = con.execute(
        "INSERT INTO apports(apporteur_id,type,cible,created) VALUES(?,?,?,?)",
        (body.apporteur_id, body.type, body.cible.strip(),
         datetime.now(timezone.utc).isoformat()))
    con.commit()
    apid = cur.lastrowid
    con.close()
    return {"id": apid}


class ApportPatch(BaseModel):
    convention_signee: str = ""
    convention_signed_at: str = ""


@app.put("/api/apports/{apid}")
def update_apport(apid: int, body: ApportPatch, _: dict = Depends(admin_only)):
    if body.convention_signee and body.convention_signee not in ("oui", "non"):
        raise HTTPException(status_code=422, detail="Valeur invalide")
    sets, vals = [], []
    if body.convention_signee:
        sets.append("convention_signee=?")
        vals.append(body.convention_signee)
    if body.convention_signed_at:
        sets.append("convention_signed_at=?")
        vals.append(body.convention_signed_at)
    if not sets:
        raise HTTPException(status_code=422, detail="Rien à mettre à jour")
    con = db()
    con.execute(f"UPDATE apports SET {', '.join(sets)} WHERE id=?", (*vals, apid))
    con.commit()
    con.close()
    return {"id": apid, "updated": sets}


@app.get("/api/bareme")
def get_bareme(_: dict = Depends(admin_only)):
    con = db()
    out = {r["cle"]: r["valeur"] for r in con.execute("SELECT * FROM bareme").fetchall()}
    con.close()
    return out


@app.put("/api/bareme")
def put_bareme(body: dict, _: dict = Depends(admin_only)):
    con = db()
    for cle, valeur in body.items():
        if cle not in BAREME_SEED:
            continue
        con.execute("UPDATE bareme SET valeur=? WHERE cle=?", (float(valeur), cle))
    con.commit()
    out = {r["cle"]: r["valeur"] for r in con.execute("SELECT * FROM bareme").fetchall()}
    con.close()
    return out


# ---------- indicateurs admin ----------
@app.get("/api/admin/kpis")
def admin_kpis(_: dict = Depends(admin_only)):
    con = db()
    today = datetime.now(timezone.utc).date().isoformat()
    mois = today[:7]
    abonnes_payants = con.execute(
        "SELECT COUNT(*) FROM abonnements WHERE statut_paiement='Payé' AND date_fin>=?",
        (today,)).fetchone()[0]
    nouveaux_terrains = con.execute(
        "SELECT COUNT(*) FROM terrains WHERE created LIKE ?", (mois + "%",)).fetchone()[0]
    mer_signees = con.execute(
        "SELECT COUNT(*) FROM mises_en_relation m JOIN terrains t ON t.ref=m.terrain_ref "
        "WHERE t.commission_signed='oui'").fetchone()[0]
    revenus = con.execute(
        "SELECT COALESCE(SUM(prix_eur*1.0/duree_mois),0) FROM abonnements "
        "WHERE statut_paiement='Payé' AND date_fin>=?", (today,)).fetchone()[0]
    commissions_dues = con.execute(
        "SELECT COALESCE(SUM(commission_due_eur),0) FROM mises_en_relation").fetchone()[0]
    commissions_encaissees = con.execute(
        "SELECT COALESCE(SUM(commission_encaissee_eur),0) FROM mises_en_relation").fetchone()[0]
    con.close()
    return {
        "abonnes_payants": abonnes_payants,
        "nouveaux_terrains_mois": nouveaux_terrains,
        "mises_en_relation_signees": mer_signees,
        "revenus_recurrents_mensuels_eur": round(revenus, 2),
        "commissions_dues_eur": round(commissions_dues, 2),
        "commissions_encaissees_eur": round(commissions_encaissees, 2),
    }


if __name__ == "__main__":
    import uvicorn

    init_db()
    uvicorn.run(app, host="127.0.0.1", port=8001)
