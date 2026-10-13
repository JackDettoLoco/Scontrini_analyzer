#!/usr/bin/env python3
"""Web app locale: dashboard spesa Esselunga.

- Solo 127.0.0.1, porta 8790
- Al via: elabora i PDF nuovi (docling CPU) in background e rigenera il DB
- DB: dati/spese.db (sqlite) — transazioni e articoli con categoria
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "script"))

import parsers  # noqa: E402
from converter_tutti import converti_pdf  # noqa: E402
from classifier import categoria_prodotto, OVERRIDE  # noqa: E402
from classifier import CATEGORIE  # noqa: E402
from estrai_sconti import estrai as _estrai_sconti  # noqa: E402

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

DB = ROOT / "dati" / "spese.db"
ESTRAZIONE = ROOT / "dati" / "estrazione"

# Configurazione da variabili d'ambiente (default = comportamento locale)
HOST = os.environ.get("ESSEL_HOST", "127.0.0.1")   # default: solo locale
PORT = int(os.environ.get("ESSEL_PORT", "8790"))

app = FastAPI(title="Spesa Esselunga")


def db() -> sqlite3.Connection:
    return sqlite3.connect(DB)


def costruisci_db() -> None:
    """Rigenera il DB da tutti i Markdown estratti (fonte: scontrini)."""
    DB.parent.mkdir(parents=True, exist_ok=True)
    DB.unlink(missing_ok=True)
    conn = db()
    conn.execute(
        "CREATE TABLE transazioni (id INTEGER PRIMARY KEY, file TEXT, data_ora TEXT, "
        "negozio TEXT, importo REAL, metodo TEXT)"
    )
    conn.execute(
        "CREATE TABLE articoli (transazione_id INTEGER, nome TEXT, prezzo REAL, "
        "prezzo_netto REAL, categoria TEXT)"
    )
    ntr = 0
    for j in sorted(ESTRAZIONE.glob("*.json")):
        file_pdf = j.name.replace(".json", ".pdf")
        for sc in parsers.parse_estrazione(j):
            cur = conn.execute(
                "INSERT INTO transazioni (file, data_ora, negozio, importo, metodo) VALUES (?,?,?,?,?)",
                (file_pdf, sc.data_ora, sc.negozio, sc.importo, sc.metodo_pagamento),
            )
            ntr += 1
            for nome, prezzo, prezzo_netto in sc.prodotti:
                conn.execute(
                    "INSERT INTO articoli (transazione_id, nome, prezzo, prezzo_netto, categoria) "
                    "VALUES (?,?,?,?,?)",
                    (cur.lastrowid, nome, prezzo, prezzo_netto, categoria_prodotto(nome)),
                )
    conn.commit()
    conn.close()
    print(f"DB rigenerato: {ntr} transazioni")


def elabora_nuovi() -> None:
    """Converte i PDF non ancora elaborati (in background, CPU)."""
    pending = sorted(p for p in (ROOT / "scontrini").glob("*.pdf")
                     if not (ESTRAZIONE / (p.stem + ".md")).exists())
    if not pending:
        return
    STATE["da_convertire"] = len(pending)
    for p in pending:
        try:
            converti_pdf(p)
        except Exception as e:  # noqa: BLE001
            print(f"ERRORE conversione {p.name}: {e}", flush=True)
    STATE["da_convertire"] = 0
    costruisci_db()


STATE: dict = {"da_convertire": 0, "sconti": None}


@app.on_event("startup")
def _startup() -> None:
    costruisci_db()
    _rileggi_sconti()
    threading.Thread(target=elabora_nuovi, daemon=True).start()


def _rileggi_sconti() -> None:
    """Rilegge gli scontrini e rigenera il cache degli sconti."""
    try:
        STATE["sconti"] = _estrai_sconti()
    except Exception as e:  # noqa: BLE001
        print(f"ERRORE sconti: {e}", flush=True)
        STATE["sconti"] = {"tipi": [], "ricevute": []}


# ---------------- API ----------------

@app.get("/api/stato")
def stato() -> dict:
    return {
        "da_convertire": STATE["da_convertire"],
        "file_pdf": len(list((ROOT / "scontrini").glob("*.pdf"))),
        "estratti": len(list(ESTRAZIONE.glob("*.json"))),
    }


@app.post("/api/elabora")
def elabora() -> dict:
    """Rielabora i PDF nuovi in background (richiesta da una nuova aggiunta)."""
    threading.Thread(target=elabora_nuovi, daemon=True).start()
    return {"messaggio": "elaborazione avviata"}


def _per_categoria(mesi: dict[str, dict[str, float]]) -> list[dict]:
    """Aggrega le ripartizioni mensili per categoria."""
    agg: dict[str, float] = {}
    for _m, cats in mesi.items():
        for c, v in cats.items():
            agg[c] = agg.get(c, 0.0) + v
    return [
        {"categoria": c, "importo": round(v, 2), "n": 0} for c, v in agg.items()
    ]


@app.get("/api/transazioni")
def transazioni() -> list[dict]:
    rows = db().execute(
        "SELECT id, data_ora, negozio, importo, metodo FROM transazioni ORDER BY data_ora"
    ).fetchall()
    return [
        {"id": r[0], "data": r[1], "negozio": r[2], "importo": r[3], "metodo": r[4]}
        for r in rows
    ]


@app.get("/api/negozi")
def negozi() -> list[str]:
    rows = db().execute("SELECT DISTINCT negozio FROM transazioni ORDER BY negozio").fetchall()
    return [r[0] for r in rows if r[0]]


@app.get("/api/categorie")
def categorie() -> list[str]:
    """Elenco delle categorie presenti (per il filtro a chip)."""
    rows = db().execute(
        "SELECT DISTINCT categoria FROM articoli WHERE categoria IS NOT NULL "
        "ORDER BY categoria COLLATE NOCASE"
    ).fetchall()
    return [r[0] for r in rows]


@app.get("/api/periodo")
def periodo() -> dict:
    """Intervallo di date minimo/massimo delle transazioni (per lo slider)."""
    row = db().execute(
        "SELECT MIN(date(data_ora)), MAX(date(data_ora)) FROM transazioni WHERE importo IS NOT NULL"
    ).fetchone()
    return {"min": row[0], "max": row[1]} if row[0] else {"min": None, "max": None}


@app.get("/api/riepilogo")
def riepilogo(negozio: Optional[str] = None, da: Optional[str] = None, a: Optional[str] = None,
              cat: Optional[str] = None) -> dict:
    """Riepilogo filtrabile per negozio, periodo e categorie (una o piu').

    L'importo di ogni ricevuta e' ripartito sulle sue voci per la quota del
    prezzo NETTO (quanto e' stato davvero pagato), con denominatore la somma
    di TUTTE le voci della transazione: la selezione per categoria resta
    corretta anche quando filtra.
    """
    conn = db()
    cats = {c.strip() for c in cat.split(",")} if cat else set()
    cats.discard("")
    # filtro temporale (data_ora e' univoco)
    dfrag, dpar = [], []
    if da:
        dfrag.append("date(data_ora)>=?"); dpar.append(da)
    if a:
        dfrag.append("date(data_ora)<=?"); dpar.append(a)
    WDATE = (" AND " + " AND ".join(dfrag)) if dfrag else ""
    par_all = ([negozio] if negozio else []) + dpar

    # Tutte le transazioni (tutti i negozi: serve a 'Per negozio') con i prodotti.
    rows = conn.execute(
        "SELECT t.id, t.data_ora, t.negozio, t.importo, a.categoria, a.prezzo_netto "
        "FROM transazioni t JOIN articoli a ON a.transazione_id=t.id "
        "WHERE t.importo IS NOT NULL " + WDATE,
        dpar,
    ).fetchall()
    per_tr: dict[int, tuple[str, str, float, list[tuple[str, float]]]] = {}
    for tid, data, neg, imp, cat_, prz in rows:
        cur = per_tr.setdefault(tid, (data or "", neg or "", imp or 0.0, []))
        cur[3].append((cat_, prz or 0.0))

    def riparti(items, imp):
        """Ripartisce imp sulle categorie per quota di prezzo NETTO.

        Aggrega prima i prezzi per categoria (una ricevuta ha spesso piu' voci
        nella stessa categoria) e il denominatore resta il totale di TUTTE le
        voci, cosi' il filtro per categoria resta corretto.
        """
        tot_cat: dict[str, float] = {}
        for c, p in items:
            if p and p > 0:
                tot_cat[c] = tot_cat.get(c, 0.0) + p
        if not tot_cat or not imp:
            return {}
        tot_p = sum(tot_cat.values())
        if not tot_p:
            return {}
        return {c: imp * p / tot_p for c, p in tot_cat.items()}

    mesi: dict[str, dict[str, float]] = {}
    neg_tot: dict[str, float] = {}
    neg_cnt: dict[str, int] = {}
    trend_list: list[dict] = []
    scontr_list: list[dict] = []
    tot_sel = 0.0
    n_sel = 0
    for tid, (data, neg, imp, items) in per_tr.items():
        m = (data or "").replace("-", "")[:6]
        per = riparti(items, imp)
        sel = {c: v for c, v in per.items() if (not cats or c in cats)}
        s = sum(sel.values())
        in_neg = (not negozio) or (neg == negozio)
        if s and in_neg:
            n_sel += 1
            tot_sel += s
            trend_list.append({"data": data, "importo": round(s, 2)})
            scontr_list.append({"id": tid, "data": data, "negozio": neg, "importo": round(s, 2)})
            for c, v in sel.items():
                mesi.setdefault(m, {})
                mesi[m][c] = mesi[m].get(c, 0.0) + v
        if s and neg:  # 'Per negozio': tutti i negozi (il selettore non filtra questo grafico)
            neg_tot[neg] = neg_tot.get(neg, 0.0) + s
            neg_cnt[neg] = neg_cnt.get(neg, 0) + 1

    scontr_list.sort(key=lambda x: -x["importo"])
    top5 = scontr_list[:5]

    # Prodotti: filtrati per negozio, periodo e categorie.
    wcat = ""
    pcat: list[str] = []
    if cats:
        wcat = " AND a.categoria IN (%s)" % ",".join("?" for _ in cats)
        pcat = list(cats)
    par_prod = ([negozio] if negozio else []) + dpar + pcat
    wneg = (f" AND t.negozio=?" if negozio else "")
    top_prod = conn.execute(
        "SELECT a.nome, COUNT(*) FROM articoli a JOIN transazioni t ON t.id=a.transazione_id "
        "WHERE a.prezzo > 0" + wneg + WDATE + wcat
        + " GROUP BY a.nome ORDER BY COUNT(*) DESC LIMIT 20", par_prod
    ).fetchall()
    top_unico = conn.execute(
        "SELECT a.nome, AVG(a.prezzo_netto) FROM articoli a JOIN transazioni t ON t.id=a.transazione_id "
        "WHERE a.prezzo > 0" + wneg + WDATE + wcat
        + " GROUP BY a.nome ORDER BY AVG(a.prezzo_netto) DESC LIMIT 20", par_prod
    ).fetchall()
    top_spesa = conn.execute(
        "SELECT a.nome, SUM(a.prezzo_netto) FROM articoli a JOIN transazioni t ON t.id=a.transazione_id "
        "WHERE a.prezzo > 0" + wneg + WDATE + wcat
        + " GROUP BY a.nome ORDER BY SUM(a.prezzo_netto) DESC LIMIT 20", par_prod
    ).fetchall()

    return {
        "totale": round(tot_sel, 2),
        "n_transazioni": n_sel,
        "media": (tot_sel / n_sel) if n_sel else 0,
        "per_mese": mesi,
        "per_categoria": _per_categoria(mesi),
        "per_negozi": [
            {"negozio": n, "transazioni": neg_cnt.get(n, 0), "importo": round(v, 2)}
            for n, v in sorted(neg_tot.items())
        ],
        "top_prodotti": [{"nome": n, "n": c} for n, c in top_prod],
        "top_prodotti_unico": [{"nome": n, "prezzo": round(v, 2)} for n, v in top_unico],
        "top_prodotti_spesa": [{"nome": n, "spesa": round(v, 2)} for n, v in top_spesa],
        "top_scontrini": top5,
        "trend": trend_list,
        "periodo": {"da": da, "a": a, "categorie": sorted(cats) if cats else []},
    }


# ---------------- gestione categorie ----------------

@app.get("/api/prodotti")
def prodotti() -> list[dict]:
    """Tutti i prodotti distinti con conteggio e categoria attuale."""
    rows = db().execute(
        "SELECT nome, categoria, COUNT(*) n FROM articoli GROUP BY nome, categoria "
        "ORDER BY nome COLLATE NOCASE"
    ).fetchall()
    return [{"nome": n, "categoria": c, "n": k} for n, c, k in rows]


@app.post("/api/assegna")
def assegna(categorie: dict[str, str]) -> dict:
    """Salva le assegnazioni manuali prodotto -> categoria (override).

    Corpo: {"NOME PRODOTTO": "categoria", ...}
    """
    # le categorie nuove sono ammesse: la stringa basta (nessun elenco chiuso)
    clean = {
        k: v.strip() for k, v in categorie.items()
        if isinstance(v, str) and v.strip()
    }
    override = {}
    if OVERRIDE.exists():
        try:
            override = json.loads(OVERRIDE.read_text())
        except Exception:  # noqa: BLE001
            override = {}
    override.update(clean)
    OVERRIDE.parent.mkdir(parents=True, exist_ok=True)
    OVERRIDE.write_text(json.dumps(override, ensure_ascii=False, indent=2))
    return {"salvate": len(clean)}


@app.get("/api/sovrascritte")
def sovrascritte() -> list[str]:
    """Nomi dei prodotti riassegnati manualmente dall'utente."""
    if OVERRIDE.exists():
        try:
            return list(json.loads(OVERRIDE.read_text()).keys())
        except Exception:  # noqa: BLE001
            return []
    return []


@app.post("/api/ricarica")
def ricarica() -> dict:
    """Rigenera il DB (applica le nuove categorie) — il pulsante refresh."""
    costruisci_db()
    _rileggi_sconti()
    return {"messaggio": "database rigenerato"}


@app.get("/api/sconti")
def sconti(da: Optional[str] = None, a: Optional[str] = None, cat: Optional[str] = None) -> dict:
    """Riepilogo degli sconti (tipi, per mese, per negozio, per ricevuta).

    Filtrabile per periodo e categorie: con le categorie, mostra le ricevute
    che contengono almeno una voce della selezione (sconto intero della ricevuta).
    """
    d = STATE.get("sconti") or {"tipi": [], "ricevute": []}
    tipi = d.get("tipi", [])
    ricevute = d.get("ricevute", [])
    if da or a:
        ricevute = [r for r in ricevute
                    if (not da or (r["data"] or "") >= da)
                    and (not a or (r["data"] or "") <= a)]
    cats = {c.strip() for c in cat.split(",")} if cat else set()
    cats.discard("")
    if cats:
        q = ",".join("?" for _ in cats)
        files = set(r[0] for r in db().execute(
            "SELECT DISTINCT t.file FROM transazioni t JOIN articoli a ON a.transazione_id=t.id "
            "WHERE a.categoria IN (%s)" % q, list(cats)).fetchall())
        ricevute = [r for r in ricevute
                    if (r.get("file") or "").replace(".json", ".pdf").replace(".md", ".pdf") in files]
    tot_tipo = {t: 0.0 for t in tipi}
    tot_mese = {}
    tot_neg = {}
    per_ricevuta = []
    for r in ricevute:
        for t in tipi:
            tot_tipo[t] += r["dettaglio"].get(t, 0.0)
        m = (r["data"] or "")[:7]
        tot_mese[m] = tot_mese.get(m, 0.0) + r["risparmio"]
        if r["negozio"]:
            tot_neg[r["negozio"]] = tot_neg.get(r["negozio"], 0.0) + r["risparmio"]
        per_ricevuta.append({
            "data": r["data"], "negozio": r["negozio"],
            "netto": r["netto"], "risparmio": r["risparmio"], "dettaglio": r["dettaglio"],
        })
    per_ricevuta.sort(key=lambda x: (x["data"] or ""))
    return {
        "tipi": tipi,
        "totale": round(sum(r["risparmio"] for r in ricevute), 2),
        "per_tipo": [{"tipo": t, "importo": round(tot_tipo[t], 2)} for t in tipi],
        "per_mese": [{"mese": m, "importo": round(v, 2)} for m, v in sorted(tot_mese.items())],
        "per_negozio": [{"negozio": n, "importo": round(v, 2)} for n, v in tot_neg.items()],
        "n_ricevute": len(ricevute),
        "ricevute": per_ricevuta,
    }


# ---------------- pagina scontrino ----------------

def _pagina_scontrino(tid: int) -> str:
    conn = db()
    t = conn.execute(
        "SELECT id, file, data_ora, negozio, importo, metodo FROM transazioni WHERE id=?",
        (tid,),
    ).fetchone()
    if not t:
        return "<h1>Scontrino non trovato</h1><a href='/'>torna alla dashboard</a>"
    tid, file, data, negozio, importo, metodo = t
    art = conn.execute(
        "SELECT nome, prezzo_netto, categoria FROM articoli WHERE transazione_id=? ORDER BY nome",
        (tid,),
    ).fetchall()
    # mostro l'effettivo pagato per prodotto (prezzo netto, sconti di prodotto inclusi)
    righe = "".join(
        f"<tr><td>{nome}</td><td class='num'>{netto:,.2f} €</td><td><span class='cat'>{cat}</span></td></tr>"
        for nome, netto, cat in art
    )
    pdf = f"/file/{file}" if file else None
    return f"""<!DOCTYPE html>
<html lang="it"><head><meta charset="UTF-8"><title>Scontrino {tid}</title>
<style>
body {{ font-family: system-ui; background:#0f172a; color:#e2e8f0; margin:0; padding:1.5rem; }}
.head {{ display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:1rem; }}
.kpi {{ background:#1e293b; border-radius:12px; padding:.8rem 1.2rem; }}
.kpi .lbl {{ color:#94a3b8; font-size:.75rem; text-transform:uppercase; }}
.kpi .val {{ font-size:1.2rem; font-weight:700; }}
table {{ border-collapse:collapse; width:100%; max-width:760px; margin-top:1.2rem; }}
th, td {{ padding:.4rem .6rem; text-align:left; border-bottom:1px solid #334155; font-size:.9rem; }}
th {{ color:#94a3b8; font-weight:500; }}
.num {{ text-align:right; font-variant-numeric: tabular-nums; }}
.cat {{ background:#334155; border-radius:6px; padding:.1rem .4rem; font-size:.75rem; }}
a {{ color:#34d399; }}
total {{ color:#eab308; }}
</style></head><body>
<div class="head">
  <div class="kpi"><div class="lbl">Scontrino n.</div><div class="val">{tid}</div></div>
  <div class="kpi"><div class="lbl">Data</div><div class="val">{data or '—'}</div></div>
  <div class="kpi"><div class="lbl">Negozio</div><div class="val">{negozio or '—'}</div></div>
  <div class="kpi"><div class="lbl">Metodo</div><div class="val">{metodo or '—'}</div></div>
  <div class="kpi"><div class="lbl">Totale</div><div class="val">{importo:,.2f} €</div></div>
  {f'<a href="{pdf}" target="blank">PDF originale ↗</a>' if pdf else ''}
  <a href="/">← dashboard</a>
</div>
<table><tr><th>Prodotto</th><th class="num">Prezzo</th><th>Categoria</th></tr>
{righe}
<tr><td><strong>Totale scontrino</strong></td><td class="num"><strong>{importo:,.2f} €</strong></td><td></td></tr>
</table>
</body></html>"""


@app.get("/scontrino/{tid}")
def scontrino_detail(tid: int):
    from fastapi.responses import HTMLResponse

    return HTMLResponse(_pagina_scontrino(tid))


@app.get("/file/{nome:path}")
def file_originale(nome: str) -> FileResponse:
    """Serve il PDF originale (solo lettura, mai modificato)."""
    p = (ROOT / "scontrini" / nome).resolve()
    if not str(p).startswith(str(ROOT / "scontrini")) or not p.is_file():
        return FileResponse(ROOT / "webapp" / "static" / "index.html")
    return FileResponse(p, media_type="application/pdf", filename=p.name)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(
        ROOT / "webapp" / "static" / "index.html",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/categorie")
def categorie() -> FileResponse:
    return FileResponse(
        ROOT / "webapp" / "static" / "categorie.html",
        headers={"Cache-Control": "no-cache"},
    )


app.mount("/static", StaticFiles(directory=str(ROOT / "webapp" / "static")), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
