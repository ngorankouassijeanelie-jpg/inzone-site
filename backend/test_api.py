"""Tests API inZONE — base SQLite temporaire, rien n'est touché en dev.

Lancement :  backend/venv/bin/python -m pytest backend/test_api.py -q
(depuis la racine inzone-site : backend/venv/bin/python -m pytest backend -q)
"""
import io
import os
import sys
import tempfile

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app as api


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    d = tmp_path_factory.mktemp("inz")
    api.DB = str(d / "test.db")
    api.UPLOAD_DIR = str(d / "uploads")
    os.makedirs(api.UPLOAD_DIR, exist_ok=True)
    api.init_db()
    with TestClient(api.app) as c:
        yield c


@pytest.fixture(scope="module")
def admin(client):
    r = client.post("/api/login", json={"email": "contact@africand.com",
                                        "password": "demonstration"})
    assert r.status_code == 200
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture(scope="module")
def user(client):
    r = client.post("/api/login", json={"email": "investisseur@exemple.ma",
                                        "password": "demonstration"})
    assert r.status_code == 200
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_health(client):
    assert client.get("/api/health").json()["ok"] is True


def test_login_wrong(client):
    r = client.post("/api/login", json={"email": "contact@africand.com",
                                        "password": "faux"})
    assert r.status_code == 401


def test_login_no_token(client):
    assert client.get("/api/verifications").status_code == 401


def test_rbac_client_forbidden(client, user):
    assert client.get("/api/users", headers=user).status_code == 403
    assert client.get("/api/demandes", headers=user).status_code == 403


def test_signup_cycle(client):
    r = client.post("/api/signup", json={"name": "Testeur", "email": "t@exemple.ci",
                                          "password": "motdepasse1"})
    assert r.status_code == 201 and r.json()["role"] == "client"
    r = client.post("/api/signup", json={"name": "Testeur", "email": "t@exemple.ci",
                                          "password": "motdepasse1"})
    assert r.status_code == 409
    r = client.post("/api/signup", json={"name": "X", "email": "x@exemple.ci",
                                          "password": "123"})
    assert r.status_code == 422


def test_me_update(client, user):
    r = client.put("/api/me", json={"company": "Soc Test"}, headers=user)
    assert r.status_code == 200
    me = client.get("/api/me", headers=user).json()
    assert me["company"] == "Soc Test"


def test_catalogue_public(client):
    assert len(client.get("/api/terrains").json()) >= 3
    assert len(client.get("/api/zones").json()) == 8
    assert len(client.get("/api/zones-projets").json()) == 9
    assert len(client.get("/api/bulletins").json()) >= 5
    assert len(client.get("/api/tarifs").json()) == 5
    t = client.get("/api/terrains/INZ-GBA-001").json()
    assert t["name"] == "Grand-Bassam"
    assert client.get("/api/terrains/INCONNU").status_code == 404


def test_terrain_crud(client, admin):
    r = client.post("/api/terrains", json={"name": "T Epreuve", "zone": "Z",
                                           "surface_ha": 2, "price_m2": 10000,
                                           "status": "Annoncé"}, headers=admin)
    assert r.status_code == 201
    ref = r.json()["ref"]
    assert client.put(f"/api/terrains/{ref}", json={"status": "Mauvais"},
                      headers=admin).status_code == 422
    r = client.put(f"/api/terrains/{ref}", json={"status": "Analyse standard"},
                   headers=admin)
    assert r.status_code == 200
    assert client.get(f"/api/terrains/{ref}").json()["status"] == "Analyse standard"
    assert client.delete(f"/api/terrains/{ref}", headers=admin).json()["deleted"] is True
    assert client.get(f"/api/terrains/{ref}").status_code == 404


def test_photos_guards(client, admin):
    r = client.post("/api/terrains", json={"name": "T Photo", "status": "Annoncé"},
                    headers=admin)
    ref = r.json()["ref"]
    img = ("f.png", io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * 100), "image/png")
    r = client.post(f"/api/terrains/{ref}/photos", files={"file": img},
                    headers=admin)
    assert r.status_code == 201
    pid = r.json()["id"]
    txt = ("f.txt", io.BytesIO(b"hello"), "text/plain")
    r = client.post(f"/api/terrains/{ref}/photos", files={"file": txt},
                    headers=admin)
    assert r.status_code == 422
    assert client.get(f"/api/terrains/{ref}/photos").json()[0]["id"] == pid
    assert client.delete(f"/api/photos/{pid}", headers=admin).json()["deleted"] is True
    assert client.delete(f"/api/terrains/{ref}", headers=admin).status_code == 200


def test_kml_contour(client, admin):
    r = client.post("/api/terrains", json={"name": "T KML", "zone": "Z",
                                           "status": "Annoncé"}, headers=admin)
    ref = r.json()["ref"]
    kml = (b'<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2">'
           b"<Placemark><Polygon><outerBoundaryIs><LinearRing><coordinates>"
           b"-3.7,5.2,0 -3.6,5.2,0 -3.6,5.1,0 -3.7,5.2,0"
           b"</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark></kml>")
    r = client.post(f"/api/terrains/{ref}/documents",
                    files={"file": ("p.kml", io.BytesIO(kml),
                                     "application/vnd.google-earth.kml+xml")},
                    data={"type": "Plan KML"}, headers=admin)
    assert r.status_code == 201
    poly = client.get(f"/api/terrains/{ref}/contour").json()["polygon"]
    assert len(poly) == 4 and poly[0] == [5.2, -3.7]
    assert client.delete(f"/api/terrains/{ref}", headers=admin).status_code == 200


def test_demandes_flow(client, admin, user):
    r = client.post("/api/demandes", json={"name": "Cli", "email": "cli@exemple.ci",
                                           "objet": "X", "niveau": "Y"})
    assert r.status_code == 201
    did = r.json()["id"]
    ds = client.get("/api/demandes", headers=admin).json()
    assert any(d["id"] == did for d in ds)
    r = client.post(f"/api/demandes/{did}/traiter", headers=admin)
    assert r.json()["status"] == "Traitée"
    bad = client.post("/api/demandes", json={"name": "X", "email": "pas-un-mail"})
    assert bad.status_code == 422


def test_factures_flow(client, admin, user):
    r = client.post("/api/demandes", json={"name": "Investisseur exemple",
                                           "email": "investisseur@exemple.ma",
                                           "objet": "GBA"})
    did = r.json()["id"]
    r = client.post("/api/factures", json={"demande_id": did, "montant": "100 €"},
                    headers=admin)
    assert r.status_code == 201
    fid = r.json()["id"]
    assert client.post("/api/factures", json={"demande_id": did, "montant": "1"},
                       headers=user).status_code == 403
    mine = client.get("/api/mes-factures", headers=user).json()
    assert any(f["id"] == fid for f in mine)
    pdf = client.get(f"/api/factures/{fid}/pdf", headers=user)
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    r = client.put(f"/api/factures/{fid}", json={"status": "Payée"}, headers=admin)
    assert r.json()["status"] == "Payée"


def test_rubriques(client, admin):
    rs = client.get("/api/rubriques", headers=admin).json()
    assert len(rs) == 6
    assert client.get("/api/rubriques").status_code == 401
    r = client.put("/api/rubriques/1", json={"etat": "Ouverte"}, headers=admin)
    assert r.json()["etat"] == "Ouverte"


def test_bulletins_admin(client, admin):
    r = client.post("/api/bulletins", json={"num": "T", "date": "D",
                                            "title": "T", "source": "S"},
                    headers=admin)
    assert r.status_code == 201
    assert any(b["title"] == "T" for b in client.get("/api/bulletins").json())


def test_forgot_reset(client):
    r = client.post("/api/signup", json={"name": "Reset", "email": "r@exemple.ci",
                                          "password": "motdepasse1"})
    assert r.status_code == 201
    assert client.post("/api/forgot", json={"email": "r@exemple.ci"}).status_code == 200
    assert client.post("/api/forgot", json={"email": "inconnu@x.ci"}).status_code == 200
    import sqlite3
    con = sqlite3.connect(api.DB)
    tok = con.execute("SELECT token FROM reset_tokens WHERE email='r@exemple.ci'").fetchone()[0]
    con.close()
    assert client.post("/api/reset", json={"token": tok, "password": "court"}).status_code == 422
    assert client.post("/api/reset", json={"token": tok,
                                           "password": "nouveaupasse1"}).status_code == 200
    r = client.post("/api/login", json={"email": "r@exemple.ci",
                                        "password": "nouveaupasse1"})
    assert r.status_code == 200
    assert client.post("/api/reset", json={"token": tok,
                                           "password": "autrepass1"}).status_code == 422
