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
    r = client.post("/api/login", json={"email": "jeaneliengoran@africandconsulting.com",
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
    r = client.post("/api/login", json={"email": "jeaneliengoran@africandconsulting.com",
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


def test_documents_targeting(client, admin, user):
    r = client.post("/api/terrains", json={"name": "T Doc Cible", "zone": "Z",
                                           "status": "Annoncé"}, headers=admin)
    ref = r.json()["ref"]
    pdf = ("d.pdf", io.BytesIO(b"%PDF-1.4 " + b"0" * 50), "application/pdf")
    r = client.post(f"/api/terrains/{ref}/documents", files={"file": pdf},
                    data={"type": "Rapport", "client_email": "investisseur@exemple.ma"},
                    headers=admin)
    assert r.status_code == 201 and r.json()["client_email"] == "investisseur@exemple.ma"
    did = r.json()["id"]
    assert any(d["id"] == did for d in client.get("/api/documents", headers=user).json())
    autre = client.post("/api/signup", json={"name": "Autre", "email": "autre@exemple.ci",
                                             "password": "motdepasse1"}).json()
    autre_hdr = {"Authorization": "Bearer " + autre["token"]}
    assert not any(d["id"] == did for d in client.get("/api/documents", headers=autre_hdr).json())
    assert any(d["id"] == did for d in client.get("/api/documents", headers=admin).json())
    pdf2 = ("d2.pdf", io.BytesIO(b"%PDF-1.4 " + b"0" * 50), "application/pdf")
    r = client.post(f"/api/terrains/{ref}/documents", files={"file": pdf2},
                    data={"client_email": "inconnu@x.ci"}, headers=admin)
    assert r.status_code == 422
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


def test_paiement_non_configure(client, admin, user):
    r = client.post("/api/demandes", json={"name": "Investisseur exemple",
                                           "email": "investisseur@exemple.ma",
                                           "objet": "GBA paiement"})
    did = r.json()["id"]
    r = client.post("/api/factures", json={"demande_id": did, "montant": "2 300 000 FCFA",
                                           "montant_xof": 2300000}, headers=admin)
    fid = r.json()["id"]
    assert client.post(f"/api/factures/{fid}/pay/cinetpay", headers=user).status_code == 503
    assert client.post(f"/api/factures/{fid}/pay/stripe", headers=user).status_code == 503


def test_paiement_guards(client, admin, user, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_dummy")
    monkeypatch.setenv("CINETPAY_APIKEY", "dummy")
    monkeypatch.setenv("CINETPAY_SITE_ID", "dummy")
    r = client.post("/api/demandes", json={"name": "Investisseur exemple",
                                           "email": "investisseur@exemple.ma",
                                           "objet": "GBA paiement 2"})
    did = r.json()["id"]
    r = client.post("/api/factures", json={"demande_id": did, "montant": "100 €"},
                    headers=admin)
    fid = r.json()["id"]
    # montant_xof non défini -> 422 avant tout appel réseau vers CinetPay/Stripe
    assert client.post(f"/api/factures/{fid}/pay/stripe", headers=user).status_code == 422
    assert client.post(f"/api/factures/{fid}/pay/cinetpay", headers=user).status_code == 422
    r2 = client.post("/api/factures", json={"demande_id": did, "montant": "2 300 000 FCFA",
                                            "montant_xof": 2300000}, headers=admin)
    fid2 = r2.json()["id"]
    signup = client.post("/api/signup", json={"name": "Intrus", "email": "intrus@exemple.ci",
                                              "password": "motdepasse1"}).json()
    intrus_hdr = {"Authorization": "Bearer " + signup["token"]}
    assert client.post(f"/api/factures/{fid2}/pay/stripe", headers=intrus_hdr).status_code == 403


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


def _activer_abonnement(formule="Veille", duree_mois=6, email="investisseur@exemple.ma"):
    """Active un abonnement payé directement en base, sans passer par le paiement en ligne."""
    import sqlite3
    con = sqlite3.connect(api.DB)
    incl = {("Veille", 6): 0, ("Veille", 12): 0,
            ("Veille Pro", 6): 1, ("Veille Pro", 12): 2}[(formule, duree_mois)]
    con.execute(
        "INSERT INTO abonnements(client_email,formule,duree_mois,prix_eur,statut_paiement,"
        "date_debut,date_fin,verifs_incluses_total,verifs_incluses_utilisees,created,updated)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (email, formule, duree_mois, 1400, "Payé", "2026-10-01", "2099-01-01",
         incl, 0, "2026-10-01T00:00:00+00:00", "2026-10-01T00:00:00+00:00"))
    con.commit()
    con.close()


def test_terrain_public_whitelist(client, admin, user):
    r = client.post("/api/terrains", json={"name": "T Verrou", "zone": "Z",
                                           "status": "Annoncé", "gps": "5.3,-3.9"},
                    headers=admin)
    ref = r.json()["ref"]
    client.put(f"/api/terrains/{ref}/commission",
               json={"commission_signed": "oui", "commission_taux": 2,
                     "commission_payeur": "Propriétaire"}, headers=admin)
    liste = client.get("/api/terrains").json()
    row = next(t for t in liste if t["ref"] == ref)
    assert "gps" not in row and "commission_signed" not in row
    detail = client.get(f"/api/terrains/{ref}").json()
    assert detail["locked"] is True
    assert "gps" not in detail and "description" not in detail and "commission_signed" not in detail
    assert detail["point_cle"] == ""
    client.put(f"/api/terrains/{ref}", json={"exemple": 1}, headers=admin)
    detail = client.get(f"/api/terrains/{ref}").json()
    assert detail["locked"] is False
    assert "gps" not in detail and "commission_signed" not in detail
    client.put(f"/api/terrains/{ref}", json={"exemple": 0}, headers=admin)
    assert client.get(f"/api/terrains/{ref}", headers=user).json()["locked"] is True
    _activer_abonnement(email="investisseur@exemple.ma")
    assert client.get(f"/api/terrains/{ref}", headers=user).json()["locked"] is False
    assert client.delete(f"/api/terrains/{ref}", headers=admin).status_code == 200


def _hdr_pour(email, name="Test", role="client"):
    """Jeton signé directement pour un compte de test, sans passer par signup/login
    (qui sont tous deux limités en débit par IP et partagés entre les tests du module)."""
    return {"Authorization": "Bearer " + api.make_token(
        {"email": email, "role": role, "name": name})}


def test_abonnement_flow(client, admin):
    client.post("/api/users", json={"email": "abonne@exemple.ci", "password": "motdepasse1",
                                    "name": "Abonne"}, headers=admin)
    hdr = _hdr_pour("abonne@exemple.ci", "Abonne")
    r = client.post("/api/abonnements", json={"formule": "Veille", "duree_mois": 6}, headers=hdr)
    assert r.status_code == 201
    fid = r.json()["facture_id"]
    assert r.json()["prix_eur"] == 1400
    assert client.get("/api/abonnements/moi", headers=hdr).json()["actif"] is None
    assert client.put(f"/api/factures/{fid}", json={"status": "Payée"},
                      headers=admin).status_code == 200
    moi = client.get("/api/abonnements/moi", headers=hdr).json()
    assert moi["actif"] is not None and moi["actif"]["statut_paiement"] == "Payé"
    import sqlite3
    con = sqlite3.connect(api.DB)
    con.execute("UPDATE abonnements SET date_fin='2020-01-01' WHERE client_email='abonne@exemple.ci'")
    con.commit()
    con.close()
    moi = client.get("/api/abonnements/moi", headers=hdr).json()
    assert moi["actif"] is None
    assert len(moi["historique"]) == 1


def test_tarif_fondateur(client, user):
    # Le tarif fondateur se compte globalement (10 premiers abonnements Veille/12 mois,
    # tous clients confondus), pas par client : le même compte peut donc souscrire
    # plusieurs fois de suite pour les besoins du test.
    for _ in range(10):
        r = client.post("/api/abonnements", json={"formule": "Veille", "duree_mois": 12},
                        headers=user)
        assert r.json()["prix_eur"] == 1800
    r = client.post("/api/abonnements", json={"formule": "Veille", "duree_mois": 12},
                    headers=user)
    assert r.json()["prix_eur"] == 2400


def test_verification_pro_incluse(client, admin):
    client.post("/api/users", json={"email": "pro@exemple.ci", "password": "motdepasse1",
                                    "name": "Pro"}, headers=admin)
    hdr = _hdr_pour("pro@exemple.ci", "Pro")
    _activer_abonnement(formule="Veille Pro", duree_mois=6, email="pro@exemple.ci")
    r = client.post("/api/terrains", json={"name": "T Pro", "status": "Annoncé"}, headers=admin)
    ref = r.json()["ref"]
    r = client.post("/api/verifications/demande",
                    json={"terrain_ref": ref, "projet": "Entrepôt", "secteur": "Logistique",
                          "delai": "Flexible"}, headers=hdr)
    assert r.status_code == 201 and r.json()["incluse"] is True and r.json()["status"] == "Payée"
    r = client.post("/api/verifications/demande",
                    json={"terrain_ref": ref, "projet": "Entrepôt 2", "secteur": "Logistique",
                          "delai": "Flexible"}, headers=hdr)
    assert r.json()["incluse"] is False and r.json()["status"] == "Demandée"
    demandes = client.get("/api/verifications/demandes", headers=hdr).json()
    assert len(demandes) == 2
    assert client.delete(f"/api/terrains/{ref}", headers=admin).status_code == 200


def test_mise_en_relation_gating(client, admin):
    client.post("/api/users", json={"email": "mer@exemple.ci", "password": "motdepasse1",
                                    "name": "Mer"}, headers=admin)
    hdr = _hdr_pour("mer@exemple.ci", "Mer")
    r = client.post("/api/terrains", json={"name": "T Mer", "status": "Annoncé"}, headers=admin)
    ref = r.json()["ref"]
    assert client.post("/api/mises-en-relation", json={"terrain_ref": ref},
                       headers=hdr).status_code == 403
    _activer_abonnement(email="mer@exemple.ci")
    assert client.post("/api/mises-en-relation", json={"terrain_ref": ref},
                       headers=hdr).status_code == 403
    assert client.post("/api/me/ncc-accept", headers=hdr).status_code == 200
    r = client.post("/api/mises-en-relation", json={"terrain_ref": ref}, headers=hdr)
    assert r.status_code == 201
    assert len(client.get("/api/mises-en-relation", headers=admin).json()) >= 1
    mine = client.get("/api/mises-en-relation", headers=hdr).json()
    assert all(m["client_email"] == "mer@exemple.ci" for m in mine) and len(mine) == 1
    assert client.delete(f"/api/terrains/{ref}", headers=admin).status_code == 200


def test_commission_admin_only(client, admin, user):
    r = client.post("/api/terrains", json={"name": "T Com", "status": "Annoncé"}, headers=admin)
    ref = r.json()["ref"]
    assert client.get(f"/api/terrains/{ref}/commission", headers=user).status_code == 403
    assert client.put(f"/api/terrains/{ref}/commission", json={"commission_signed": "non"},
                      headers=user).status_code == 403
    assert client.put(f"/api/terrains/{ref}/commission",
                      json={"commission_signed": "oui", "commission_taux": 5},
                      headers=admin).status_code == 422
    r = client.put(f"/api/terrains/{ref}/commission",
                   json={"commission_signed": "oui", "commission_taux": 2,
                         "commission_payeur": "Propriétaire"}, headers=admin)
    assert r.status_code == 200
    assert client.get(f"/api/terrains/{ref}/commission", headers=admin).json()["commission_taux"] == 2
    assert client.delete(f"/api/terrains/{ref}", headers=admin).status_code == 200


def test_agent_double_paiement(client, admin):
    r = client.post("/api/terrains", json={"name": "T Agent", "status": "Annoncé"}, headers=admin)
    ref = r.json()["ref"]
    aid = client.post("/api/agents", json={"nom": "Agent K", "secteur": "Abidjan"},
                      headers=admin).json()["id"]
    r = client.post(f"/api/agents/{aid}/taches",
                    json={"terrain_ref": ref, "type": "Terrain signalé", "montant": 20000},
                    headers=admin)
    assert r.status_code == 201
    tid = r.json()["id"]
    r = client.post(f"/api/agents/{aid}/taches",
                    json={"terrain_ref": ref, "type": "Terrain signalé", "montant": 20000},
                    headers=admin)
    assert r.status_code == 422
    assert client.put(f"/api/taches-agents/{tid}", json={"status": "Refusée"},
                      headers=admin).status_code == 200
    r = client.post(f"/api/agents/{aid}/taches",
                    json={"terrain_ref": ref, "type": "Terrain signalé", "montant": 20000},
                    headers=admin)
    assert r.status_code == 201
    assert client.delete(f"/api/terrains/{ref}", headers=admin).status_code == 200


def test_apporteur_premier_arrive(client, admin):
    r = client.post("/api/terrains", json={"name": "T Apport", "status": "Annoncé"}, headers=admin)
    ref = r.json()["ref"]
    client.put(f"/api/terrains/{ref}/commission",
               json={"commission_signed": "oui", "commission_taux": 2,
                     "commission_payeur": "Propriétaire"}, headers=admin)
    a1 = client.post("/api/apporteurs", json={"nom": "Apporteur 1", "type": "Terrains"},
                     headers=admin).json()["id"]
    a2 = client.post("/api/apporteurs", json={"nom": "Apporteur 2", "type": "Terrains"},
                     headers=admin).json()["id"]
    r = client.post("/api/apports", json={"apporteur_id": a1, "type": "Terrains", "cible": ref},
                    headers=admin)
    assert r.status_code == 201
    apid = r.json()["id"]
    assert client.post("/api/apports", json={"apporteur_id": a2, "type": "Terrains", "cible": ref},
                       headers=admin).status_code == 422
    assert client.get("/api/apports", headers=admin).status_code == 200
    assert client.get("/api/apports").status_code == 401
    import sqlite3
    con = sqlite3.connect(api.DB)
    con.execute(
        "INSERT INTO mises_en_relation(terrain_ref,client_email,status,issue,created,updated)"
        " VALUES(?,?,?,?,?,?)",
        (ref, "investisseur@exemple.ma", "Demandée", "En cours",
         "2026-10-01T00:00:00+00:00", "2026-10-01T00:00:00+00:00"))
    mid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    con.commit()
    con.close()
    r = client.put(f"/api/mises-en-relation/{mid}",
                   json={"issue": "Vente conclue", "commission_encaissee_eur": 1000},
                   headers=admin)
    assert r.status_code == 200
    assert r.json()["apporteurs_du"]["terrain"]["du"] == 0
    assert r.json()["apporteurs_du"]["terrain"]["raison"] == "convention non signée"
    assert client.put(f"/api/apports/{apid}", json={"convention_signee": "oui"},
                      headers=admin).status_code == 200
    r = client.put(f"/api/mises-en-relation/{mid}",
                   json={"commission_encaissee_eur": 1000}, headers=admin)
    assert r.json()["apporteurs_du"]["terrain"]["du"] == 150
    assert client.delete(f"/api/terrains/{ref}", headers=admin).status_code == 200


def test_apporteur_client_premier_abonnement(client, admin):
    """Le taux apporteur_client_premier_pct (12%) s'applique au premier versement de
    commission pour un client apporté ; les suivants retombent sur apporteur_client_commission_pct (10%)."""
    email = "apporteur-client-test@exemple.ma"
    a = client.post("/api/apporteurs", json={"nom": "Apporteur Client", "type": "Clients"},
                    headers=admin).json()["id"]
    r = client.post("/api/apports", json={"apporteur_id": a, "type": "Clients", "cible": email},
                    headers=admin)
    assert r.status_code == 201
    apid = r.json()["id"]
    assert client.put(f"/api/apports/{apid}", json={"convention_signee": "oui"},
                      headers=admin).status_code == 200

    refs = []
    mids = []
    for i in range(2):
        ref = client.post("/api/terrains", json={"name": f"T Client Apport {i}", "status": "Annoncé"},
                          headers=admin).json()["ref"]
        refs.append(ref)
        import sqlite3
        con = sqlite3.connect(api.DB)
        con.execute(
            "INSERT INTO mises_en_relation(terrain_ref,client_email,status,issue,created,updated)"
            " VALUES(?,?,?,?,?,?)",
            (ref, email, "Demandée", "En cours",
             "2026-10-01T00:00:00+00:00", "2026-10-01T00:00:00+00:00"))
        mids.append(con.execute("SELECT last_insert_rowid()").fetchone()[0])
        con.commit()
        con.close()

    r1 = client.put(f"/api/mises-en-relation/{mids[0]}",
                    json={"commission_encaissee_eur": 10000}, headers=admin)
    assert r1.json()["apporteurs_du"]["client"]["du"] == 1200

    r2 = client.put(f"/api/mises-en-relation/{mids[1]}",
                    json={"commission_encaissee_eur": 10000}, headers=admin)
    assert r2.json()["apporteurs_du"]["client"]["du"] == 1000

    for ref in refs:
        assert client.delete(f"/api/terrains/{ref}", headers=admin).status_code == 200
