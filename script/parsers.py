"""Parsers deterministici per i JSON di righe estratti con docling.

Regola di verità: ogni blocco "RICEVUTA DI PAGAMENTO" = una transazione (spesa).
Il file contiene una lista di righe di testo nell'ordine del documento; le
righe dei prodotti hanno il formato "NOME *<flag IVA> prezzo".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

RICEVUTA_BLOCK = re.compile(r"RICEVUTA\s+DI\s+PAGAMENTO")
DATA_STAMPA = re.compile(r"(\d{2})-(\d{2})-(\d{4})\s+(\d{2}:\d{2})\s+DOCUMENTO")
NEGOZIO_RE = re.compile(r"ESSELUNGA\s+S\.p\.A\.[^A-Z0-9]*([A-Z](?:[A-Z\s\-]*[A-Z])?)\s*(?:P\.I|$|\n)")
IMPORTO = re.compile(r"^(\d{1,4}(?:,\d{2})?)$")
# "NOME *a 2,18" oppure "NOME c 3,58" (flag IVA: a=4%, c=10%, d=22%, NS)
PROD_PREZZO = re.compile(r"^(.+?)\s+\*?([acdNS]{1,2})\s*(\d{1,4},\d{2})\s*$")
# "SCONTO FIDATY 40% 6,36-S"
SCONTO = re.compile(r"^(SCONTO[^%]*%)\s*(\d{1,4},\d{2})\s*-S\s*$")
NON_PRODOTTI = {"TOTALE EURO", "PAGAMENTO CARTA DI CREDITO", "IVA EURO"}


@dataclass
class Scontrino:
    data_ora: Optional[str]  # "2026-09-30 17:16"
    negozio: Optional[str]
    importo: Optional[float]
    metodo_pagamento: Optional[str]
    # ogni prodotto e' (nome, prezzo_pieno, prezzo_netto)
    # prezzo_netto = quanto e' stato davvero pagato (pieno - sconti FIDATY/promo)
    prodotti: list[tuple[str, float, float]]  # (nome, prezzo_pieno, prezzo_netto)
    extra_righe: list[str]


def split_scontrini(righe: list[str]) -> list[tuple[list[str], list[str]]]:
    """Divide le righe nei segmenti (corpo_scontrino, ricevuta)."""
    idx = [i for i, r in enumerate(righe) if RICEVUTA_BLOCK.search(r)]
    if not idx:
        return [(righe, [])]
    out = []
    prev = 0
    for i, start in enumerate(idx):
        end = idx[i + 1] if i + 1 < len(idx) else len(righe)
        out.append((righe[prev:start], righe[start:end]))
        prev = start
    return out


def _parse_ricevuta(testo: list[str]) -> dict:
    """Estrae data/ora, metodo di pagamento e totale da una ricevuta."""
    m = "\n".join(testo)
    info: dict = {}
    dm = re.search(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}:\d{2})", m)
    if dm:
        info["data_ora"] = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)} {dm.group(4)}"
    metodo = _metodo_pagamento(testo)
    if metodo:
        info["metodo"] = metodo
    tot = re.findall(r"TOTALE\s*(?:\n|\s*)(\d{1,4},\d{2})", m)
    if tot:
        info["importo"] = float(tot[-1].replace(",", "."))
    else:
        # formato antico: la riga "EURO" seguita dal numero (es. "EURO 8,86")
        ant = re.findall(r"EURO\s+(\d{1,4},\d{2})", m)
        if ant:
            info["importo"] = float(ant[0].replace(",", "."))
    if "importo" not in info:
        # ultimo tentativo: il totale del scontrino stampato subito dopo il blocco
        pass
    return info


def _metodo_pagamento(testo: list[str]) -> Optional[str]:
    for line in testo:
        s = line.strip()
        mm = re.search(r"\b(MASTERCARD|VISA[^A-Z]*|BANCOMAT|POSTE|AMEX)\b", s, re.I)
        if mm and not s.startswith(("S/E-", "CASSA", "OPER", "COD", "AID", "ACQ", "EURO", "Acquisto")):
            return mm.group(1).upper()


def _parse_prodotti(righe: list[str]) -> list[tuple[str, float, float]]:
    """Estrae i prodotti dalle righe del corpo dello scontrino.

    Ritorna (nome, prezzo_pieno, prezzo_netto). Il prezzo pieno e' quello a
    scaffale (grosso); il prezzo netto e' quanto si e' davvero pagato, ottenuto
    sottraendo gli sconti FIDATY/promo (righe "SCONTO ... %") che seguono la
    riga del prodotto. Sconti a livello di ricevuta (buoni, pagamento) NON
    sono attribuiti ai prodotti.
    """
    out: list[list] = []  # [nome, prezzo_pieno, prezzo_netto]
    for line in righe:
        s = line.strip()
        if s in ("PAGAMENTO CARTA DI CREDITO", "TOTALE EURO") or s.startswith("di cui IVA"):
            break  # fine sezione prodotti
        if not s or IMPORTO.match(s):
            continue
        m = PROD_PREZZO.match(s)
        if m and not m.group(1).startswith(("SCONTO", "IVA", "NPSACCH")):
            nome = m.group(1).strip()
            prezzo = float(m.group(3).replace(",", "."))
            if nome and re.search(r"[A-Za-z]", nome):
                out.append([nome, prezzo, prezzo])  # netto parte dal pieno
            continue
        sm = SCONTO.match(s)
        if sm:
            val = float(sm.group(2).replace(",", "."))
            if out:  # attribuisce lo sconto all'ultimo prodotto
                out[-1][2] = max(out[-1][2] - val, 0.0)
    return [(n, p, pn) for n, p, pn in out]


def _parse_corpo_solo(righe: list[str]) -> dict:
    """Quando il PDF NON contiene la RICEVUTA DI PAGAMENTO, la transazione
    viene dai campi dello scontrino stesso (TOTALE EURO, data stampata)."""
    info: dict = {}
    for i, r in enumerate(righe):
        if r.startswith("TOTALE EURO"):
            info["taglio"] = i
    if "taglio" not in info:
        return info
    # totale: il valore su/righe vicino a TOTALE EURO
    m = re.search(r"TOTALE EURO\s*(\d{1,4},\d{2})", " ".join(righe[info["taglio"]:info["taglio"] + 2]))
    if m:
        info["importo"] = float(m.group(1).replace(",", "."))
    dm = re.search(r"(\d{2})-(\d{2})-(\d{4})\s+(\d{2}:\d{2})\s+DOCUMENTO", "\n".join(righe))
    if dm:
        info["data_ora"] = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)} {dm.group(4)}"
    for r in righe[info["taglio"]:info["taglio"] + 4]:
        if re.match(r"^PAGAMENTO\s+([A-Z][A-Z\s/]{2,30})", r) and "SCONTO" not in r:
            info["metodo"] = r.split(" ", 1)[1]
            break
    return info


def parse_estrazione(json_path: Path) -> list[Scontrino]:
    """Converte le righe di un PDF in una lista di scontrini (transazioni)."""
    righe = __import__("json").loads(json_path.read_text(encoding="utf-8"))
    out: list[Scontrino] = []
    for corpo, ricevuta in split_scontrini(righe):
        s = Scontrino(
            data_ora=None,
            negozio=None,
            importo=None,
            metodo_pagamento=None,
            prodotti=_parse_prodotti(corpo),
            extra_righe=list(corpo),
        )
        body = "\n".join(corpo)
        m = DATA_STAMPA.search(body)
        if m:
            s.data_ora = f"{m.group(3)}-{m.group(2)}-{m.group(1)} {m.group(4)}"
        rx_neg = re.compile(r"Esselunga di ([A-Za-z\u00e0-\u00fc\u00e8]+(?: [A-Za-z\u00e0-\u00fc\u00e8]+)?)")
        nm = rx_neg.search(body) or rx_neg.search(json_path.stem)
        s.negozio = ("Esselunga di " + nm.group(1)).strip() if nm else None
        if ricevuta:
            info = _parse_ricevuta(ricevuta)
            s.data_ora = info.get("data_ora") or s.data_ora
            s.metodo_pagamento = info.get("metodo")
            s.importo = info.get("importo")
            if s.importo is None:
                # ricevuta in formato antico senza totale: lo prende dal corpo
                solo = _parse_corpo_solo(corpo)
                s.data_ora = solo.get("data_ora") or s.data_ora
                s.metodo_pagamento = solo.get("metodo") or s.metodo_pagamento
                s.importo = solo.get("importo")
        else:
            # nessun blocco ricevuta: la transazione è lo scontrino stesso
            solo = _parse_corpo_solo(corpo)
            s.data_ora = solo.get("data_ora") or s.data_ora
            s.metodo_pagamento = solo.get("metodo")
            s.importo = solo.get("importo")
        if s.importo is None:
            continue  # segmento senza totale = blocco di chiusura
        out.append(s)
    return out


if __name__ == "__main__":
    import sys
    from pathlib import Path as P

    p = P(sys.argv[1])
    for s in parse_estrazione(p):
        print(s.data_ora, s.negozio, s.importo, s.metodo_pagamento)
        for pr, prz, pn in s.prodotti[:8]:
            print("   ", pr, prz, "(netto", pn, ")")
