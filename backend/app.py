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

import jwt
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "inzone.db")
UPLOAD_DIR = os.path.join(BASE, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
SECRET = os.environ.get("INZONE_SECRET", "dev-secret-a-changer-en-prod")
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
        """
    )
    for col in ("description TEXT", "acces TEXT", "sol TEXT", "riverains TEXT",
                "reseaux TEXT", "source_prix TEXT", "gps TEXT",
                "lat REAL", "lon REAL"):
        try:
            c.execute(f"ALTER TABLE terrains ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass
    try:
        c.execute("ALTER TABLE documents ADD COLUMN file TEXT")
    except sqlite3.OperationalError:
        pass
    for col in ("criteria TEXT", "alerts TEXT"):
        try:
            c.execute(f"ALTER TABLE users ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass
    con.commit()
    if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        seed(con)
    backfill_projets(con)
    con.close()


def hash_pwd(pwd: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pwd.encode(), salt.encode(), 200_000).hex()


def make_user(con, email, pwd, role, name, company="", country=""):
    salt = secrets.token_hex(16)
    con.execute(
        "INSERT INTO users(email,pwd_hash,salt,role,name,company,country,created)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (email, hash_pwd(pwd, salt), salt, role, name, company, country,
         datetime.now(timezone.utc).isoformat()),
    )


def seed(con):
    c = con.cursor()
    make_user(con, "contact@africand.com", "demonstration", "admin",
              "Africand Consulting", "Africand Consulting", "Côte d'Ivoire")
    make_user(con, "investisseur@exemple.ma", "demonstration", "client",
              "Investisseur exemple", "Société exemple", "Maroc")
    c.executemany(
        "INSERT INTO terrains VALUES(?,?,?,?,?,?,?,?)",
        [
            ("INZ-GBA-001", "Grand-Bassam", "Grand-Bassam", 6.0, 60000,
             "Analyse standard", "Fiche complète",
             "Adapté à la logistique et à l'industrie légère"),
            ("INZ-ATT-002", "Attinguié", "Attinguié PK31", 8.46, None,
             "Analyse en cours", "Fiche en préparation", "À confirmer sur site"),
            ("INZ-ANY-003", "Anyama", "Anyama", 6.0, None,
             "Annoncé", "Données vendeur", "À analyser"),
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


# ---------- auth ----------
LOGIN_ATTEMPTS: dict = {}
if SECRET == "dev-secret-a-changer-en-prod":
    print("ATTENTION : INZONE_SECRET non défini, secret de développement utilisé.")
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


def rows(con, q, args=()):
    return [dict(r) for r in con.execute(q, args).fetchall()]


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
    return {"token": make_token(user), "role": user["role"], "name": user["name"]}


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    return {"email": user["email"], "role": user["role"], "name": user["name"],
            "company": user["company"], "country": user.get("country", ""),
            "criteria": user.get("criteria", ""), "alerts": user.get("alerts", "")}


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
    out = rows(con, "SELECT email,name,company,country,role,created FROM users ORDER BY id")
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


@app.get("/api/terrains")
def terrains():
    con = db()
    out = rows(con, "SELECT * FROM terrains")
    con.close()
    return out


@app.get("/api/terrains/{ref}")
def terrain(ref: str):
    con = db()
    row = con.execute("SELECT * FROM terrains WHERE ref=?", (ref,)).fetchone()
    con.close()
    if not row:
        raise HTTPException(status_code=404, detail="Terrain introuvable")
    return dict(row)


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
    out = rows(con, "SELECT * FROM documents ORDER BY id")
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


STATUTS = ("Annoncé", "Analyse en cours", "Analyse standard", "Vérifié premium")


@app.post("/api/terrains", status_code=201)
def create_terrain(body: TerrainIn, _: dict = Depends(admin_only)):
    name = body.name.strip()
    if len(name) < 2:
        raise HTTPException(status_code=422, detail="Nom du terrain requis")
    if body.status not in STATUTS:
        raise HTTPException(status_code=422, detail="Statut invalide")
    base = "".join(ch for ch in (body.zone or name) if ch.isalnum())[:3].upper() or "GEN"
    con = db()
    n = con.execute("SELECT COUNT(*) FROM terrains").fetchone()[0] + 1
    ref = f"INZ-{base}-{n:03d}"
    while con.execute("SELECT 1 FROM terrains WHERE ref=?", (ref,)).fetchone():
        n += 1
        ref = f"INZ-{base}-{n:03d}"
    con.execute(
        "INSERT INTO terrains(ref,name,zone,surface_ha,price_m2,status,level,point_cle,"
        "description,acces,sol,riverains,reseaux,source_prix,gps)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (ref, name, body.zone.strip(), body.surface_ha or None,
         body.price_m2 or None, body.status, "", body.point_cle.strip(),
         body.description.strip(), body.acces.strip(), body.sol.strip(),
         body.riverains.strip(), body.reseaux.strip(),
         body.source_prix.strip(), body.gps.strip()),
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


@app.put("/api/terrains/{ref}")
def update_terrain(ref: str, body: TerrainPatch, _: dict = Depends(admin_only)):
    sets, vals = [], []
    if body.status:
        if body.status not in STATUTS:
            raise HTTPException(status_code=422, detail="Statut invalide")
        sets.append("status=?")
        vals.append(body.status)
    for f in ("name", "zone", "point_cle", "description", "acces", "sol",
              "riverains", "reseaux", "source_prix", "gps"):
        v = getattr(body, f)
        if v:
            sets.append(f"{f}=?")
            vals.append(v.strip())
    if body.surface_ha >= 0:
        sets.append("surface_ha=?")
        vals.append(body.surface_ha or None)
    if body.price_m2 >= 0:
        sets.append("price_m2=?")
        vals.append(body.price_m2 or None)
    if not sets:
        raise HTTPException(status_code=422, detail="Rien à mettre à jour")
    con = db()
    con.execute(f"UPDATE terrains SET {', '.join(sets)} WHERE ref=?", (*vals, ref))
    con.commit()
    con.close()
    return {"ref": ref, "updated": sets}


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
                    type: str = Form("Pièce"), _: dict = Depends(admin_only)):
    con = db()
    t = con.execute("SELECT name FROM terrains WHERE ref=?", (ref,)).fetchone()
    if not t:
        con.close()
        raise HTTPException(status_code=404, detail="Terrain introuvable")
    ctype = (file.content_type or "").lower()
    name_low = (file.filename or "").lower()
    is_kml = name_low.endswith(".kml") or ctype == "application/vnd.google-earth.kml+xml"
    if not (ctype.startswith("image/") or ctype == "application/pdf" or is_kml):
        con.close()
        raise HTTPException(status_code=422, detail="PDF, image ou KML uniquement")
    saved = save_upload(ref, file, ("",) if is_kml else ("image/", "application/"))
    cur = con.execute(
        "INSERT INTO documents(name,terrain,type,etat,file) VALUES(?,?,?,?,?)",
        (file.filename, t["name"], type.strip() or "Pièce", "Disponible", saved["file"]))
    con.commit()
    did = cur.lastrowid
    con.close()
    return {"id": did, "url": saved["file"]}


class FactureIn(BaseModel):
    demande_id: int
    montant: str


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
        "INSERT INTO factures(demande_id,client_email,objet,niveau,montant,status,created)"
        " VALUES(?,?,?,?,?,?,?)",
        (d["id"], d["email"], d["objet"], d["niveau"], body.montant.strip(),
         "Émise", datetime.now(timezone.utc).isoformat()),
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
    con.close()
    return {"id": fid, "status": body.status}


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
    return {"token": make_token(user), "role": "client", "name": user["name"]}


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


if __name__ == "__main__":
    import uvicorn

    init_db()
    uvicorn.run(app, host="127.0.0.1", port=8001)
