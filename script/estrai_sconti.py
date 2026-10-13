# -*- coding: utf-8 -*-
"""Estrae gli sconti per ricevuta e li serializza in dati/sconti.json.
Categoria tipi:
  - 'Sconto % (promo)': riga "SCONTO nn% importo" (non FIDATY)
  - 'Sconto FIDATY'   : riga "SCONTO FIDATY nn% importo"
  - 'Buono (voucher)' : riga "BUONO ..."
  - 'Sconto pagamento': riga "PAGAMENTO ... SCONTO/FACILE ..."
Il risparmio di ogni ricevuta = somma tipi (concorda con lordo - netto)."""
import json, re, os, glob, sqlite3, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EST  = os.path.join(BASE, "dati", "estrazione")
DB   = os.path.join(BASE, "dati", "spese.db")
OUT  = os.path.join(BASE, "dati", "sconti.json")

def eur(x):
    x = x.replace("€", "").replace("\xa0", "").strip()
    if "," in x and "." not in x:
        x = x.replace(",", ".")
    return float(x)

TIPI = ["Sconto % (promo)", "Sconto FIDATY", "Buono (voucher)", "Sconto pagamento"]

def righe_sconti(testo):
    """Ritorna lista di (tipo, importo) per le righe di sconto del ricevuto."""
    out = []
    for line in testo:
        s = (line if isinstance(line, str) else str(line)).strip()
        if not s:
            continue
        up = s.upper()
        amts = re.findall(r"\d+[.,]\d+", s)
        amt = eur(amts[-1]) if amts else 0.0
        if up.startswith("PAGAMENTO") and ("SCONTO" in up or "FACILE" in up) \
           and "CARTA" not in up and "CONTANTI" not in up and "PRELIEVO" not in up:
            out.append(("Sconto pagamento", amt))
        elif up.startswith("SCONTO FIDATY"):
            out.append(("Sconto FIDATY", amt))
        elif up.startswith("SCONTO") and "%" in up:
            out.append(("Sconto % (promo)", amt))
        elif up.startswith("BUONO"):
            out.append(("Buono (voucher)", amt))
    return out

def estrai() -> dict:
    """Rilegge gli scontrini ed estrae gli sconti (ritorna {tipi, ricevute})."""
    db = sqlite3.connect(DB)
    # file(.pdf) -> (data_ora, negozio, importo)
    mappa = {r[0]: (r[1], r[2], r[3]) for r in
             db.execute("SELECT file, data_ora, negozio, importo FROM transazioni")}
    righe = []
    for f in sorted(glob.glob(os.path.join(EST, "*.json"))):
        nome = os.path.basename(f)
        # la chiave nel DB è il .pdf; normalizzo l'estensione
        chiave = nome.replace(".json", ".pdf").replace(".md", ".pdf")
        testo = json.load(open(f, encoding="utf-8"))
        sconti = righe_sconti(testo)
        if not sconti:
            continue
        per_tipo = {t: 0.0 for t in TIPI}
        n_righe = {t: 0 for t in TIPI}
        for t, a in sconti:
            per_tipo[t] += a
            n_righe[t] += 1
        tot = sum(per_tipo.values())
        info = mappa.get(chiave)
        data, negozio, netto = info if info else (None, None, 0.0)
        righe.append({
            "file": nome,
            "data": (data or "")[:10],
            "negozio": negozio,
            "netto": netto,
            "risparmio": round(tot, 2),
            "dettaglio": {t: round(per_tipo[t], 2) for t in TIPI},
            "n_righe": {t: n_righe[t] for t in TIPI},
        })
    dati = {"tipi": TIPI, "ricevute": righe}
    try:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(dati, fh, ensure_ascii=False, indent=2)
    except Exception:  # noqa: BLE001
        pass
    return dati


def main():
    d = estrai()
    print(f"scritti {len(d['ricevute'])} ricevute con sconti -> {os.path.basename(OUT)}")
    print(f"totale risparmio: €{sum(r['risparmio'] for r in d['ricevute']):.2f}")


if __name__ == "__main__":
    main()
