"""Fichiers de démonstration : génère des PNG/PDF d'exemple dans uploads/
et les rattache aux données (photo Grand-Bassam + 2 documents).

Usage :  backend/venv/bin/python backend/seed_files.py
Rejouable sans doublon.
"""
import os
import sqlite3
import struct
import zlib

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "inzone.db")
UP = os.path.join(BASE, "uploads")
os.makedirs(UP, exist_ok=True)


def png(path, w=480, h=320):
    def chunk(t, d):
        return (struct.pack(">I", len(d)) + t + d +
                struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF))

    rows = b""
    for y in range(h):
        rows += b"\x00"
        for x in range(w):
            g = 200 - int(90 * y / h) + ((x // 24 + y // 24) % 2) * 12
            rows += bytes((70, min(255, g), 120))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) +
            chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
    open(path, "wb").write(data)


def pdf(path, lines):
    content = b""
    for i, ln in enumerate(lines):
        y = 780 - i * 26
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
    open(path, "wb").write(out)


png(os.path.join(UP, "demo-gba-photo.png"))
pdf(os.path.join(UP, "demo-fiche-gba.pdf"), [
    "inZONE - Analyse standard INZ-GBA-001",
    "Grand-Bassam, 6 hectares.",
    "Document de demonstration.",
])
pdf(os.path.join(UP, "demo-bulletin-0.pdf"), [
    "inZONE - Bulletin de veille no 0, octobre 2026",
    "PK24, Yamoussoukro, Y4, Attinguie.",
    "Document de demonstration.",
])

con = sqlite3.connect(DB)
c = con.cursor()
if not c.execute("SELECT 1 FROM photos WHERE file='/uploads/demo-gba-photo.png'").fetchone():
    c.execute(
        "INSERT INTO photos(terrain_ref,file,original,caption,size,created)"
        " VALUES(?,?,?,?,?,datetime('now'))",
        ("INZ-GBA-001", "/uploads/demo-gba-photo.png",
         "grand-bassam-vue.png", "Vue du terrain, Grand-Bassam",
         os.path.getsize(os.path.join(UP, "demo-gba-photo.png"))))
    print("photo demo ajoutee")
c.execute("UPDATE documents SET file='/uploads/demo-fiche-gba.pdf'"
          " WHERE name='Analyse standard' AND terrain='Grand-Bassam' AND file IS NULL")
c.execute("UPDATE documents SET file='/uploads/demo-bulletin-0.pdf'"
          " WHERE name LIKE 'Bulletin%' AND file IS NULL")
con.commit()
print("documents avec fichier :",
      c.execute("SELECT COUNT(*) FROM documents WHERE file IS NOT NULL").fetchone()[0])
con.close()
print("OK")
