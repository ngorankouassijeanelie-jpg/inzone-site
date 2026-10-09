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
from datetime import datetime, timezone

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "inzone.db")
SECRET = os.environ.get("INZONE_SECRET", "dev-secret-a-changer-en-prod")
TOKEN_DAYS = 7

app = FastAPI(title="inZONE API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # V1 démo ; restreindre en prod
    allow_methods=["*"],
    allow_headers=["*"],
)


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
        """
    )
    con.commit()
    if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        seed(con)
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


# ---------- auth ----------
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
def login(body: Login):
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
            "company": user["company"]}


# --- catalogue public ---
@app.get("/api/zones")
def zones():
    con = db()
    out = rows(con, "SELECT * FROM zones ORDER BY id")
    con.close()
    return out


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


@app.put("/api/terrains/{ref}")
def update_terrain(ref: str, body: StatutIn, _: dict = Depends(admin_only)):
    con = db()
    con.execute("UPDATE terrains SET status=? WHERE ref=?", (body.status, ref))
    con.commit()
    con.close()
    return {"ref": ref, "status": body.status}


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
