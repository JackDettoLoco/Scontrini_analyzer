#!/usr/bin/env python3
"""Genera il dizionario di classificazione categoria -> keywords col modello locale.

Fase 1 (LLM): da tutti i nomi di prodotto estratti, fa al modello la mappa
keyword->categoria. Fase 2 (deterministica): il risultato è salvato in
dati/categorie_llm.json e applicato da classifier.py su ogni prodotto.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATEGORIE_FILE = ROOT / "dati" / "categorie_llm.json"
CATEGORIE = [
    "Frutta e Verdura",
    "Carne e Polli",
    "Pesce e Frutti di Mare",
    "Latticini e Formaggi",
    "Uova",
    "Pane e Forno",
    "Pasta, Riso e Cereali",
    "Salumi",
    "Dolci e Merendine",
    "Vini e Superalcolici",
    "Birra e Bevande",
    "Surgelati",
    "Curio e Freschismi",
    "Cura della Persona",
    "Igiene e Detersivi",
    "Prodotti per Animali",
    "Altro",
]

# Configurazione LLM: variabili d'ambiente con default al setup locale
BASE_URL = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:18081/v1")
MODEL = os.environ.get("LLM_MODEL", "qwen38-27b-ridge-3.7bpw-160k")

def _carica_chiave() -> str:
    """Chiave LLM: da LLM_API_KEY, altrimenti da ~/.config/qwen38-pi/api-key."""
    k = os.environ.get("LLM_API_KEY", "").strip()
    if k:
        return k
    p = Path.home().joinpath(".config/qwen38-pi/api-key")
    if p.exists():
        return p.read_text().strip()
    raise RuntimeError("Nessuna chiave LLM: imposta LLM_API_KEY o crea ~/.config/qwen38-pi/api-key")

API_KEY = _carica_chiave()


def chat(testo: str, system: str = "") -> str:
    import httpx

    r = httpx.post(
        f"{BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}"},
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": testo},
            ],
            "temperature": 0,
            "max_tokens": 8192,
        },
        timeout=300,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def raccogli_prodoti() -> list[str]:
    """Raccoglie tutti i nomi di prodotto dai JSON estratti."""
    import parsers  # locale a questo script

    nomi: set[str] = set()
    for j in sorted(ROOT.joinpath("dati/estrazione").glob("*.json")):
        for scontrino in parsers.parse_estrazione(j):
            for nome, _prezzo, _prezzo_netto in scontrino.prodotti:
                # rimuovi i flag fiscali (*d, *c, *NS) e i numeri
                n = re.sub(r"^\*?\s*[cdNS]*\s*", "", nome).strip()
                n = re.sub(r"\d+[.,]?\d*", "", n).strip(" .-")
                if n:
                    nomi.add(n.upper())
    return sorted(nomi)


def genera_dict(nomi: list[str]) -> dict[str, str]:
    """Chiede al modello la mappa keyword->categoria per blocchi di nomi."""
    dizi: dict[str, str] = {}
    chunk = 30
    for i in range(0, len(nomi), chunk):
        blocco = nomi[i : i + chunk]
        lista = "\n".join(blocco)
        prompt = (
            "Classifichi i prodotti della spesa di un supermercato Esselunga.\n"
            "Dalla lista di nomi di prodotti (già in MAIUSCOLO, talvolta con abbreviazioni e codici) "
            "estrai le PAROLE CHIAVE che li identificano (una o due per prodotto, maiuscole, "
            "senza spazi interni se possibile) e assegnaci una categoria tra: "
            + ", ".join(CATEGORIE)
            + ".\nRispondi SOLO con un oggetto JSON valido: chiave = parola chiave, valore = categoria.\n"
            "Niente altro testo.\nPRODOTTI:\n" + lista
        )
        for tent in range(3):
            risposta = chat(prompt)
            m = re.search(r"\{.*\}", risposta, re.S)
            if not m:
                print(f"blocco {i // chunk + 1}: retry {tent+1} (niente JSON)", flush=True)
                continue
            try:
                d = json.loads(m.group(0))
            except ValueError:
                print(f"blocco {i // chunk + 1}: retry {tent+1} (JSON non valido)", flush=True)
                continue
            n_ok = 0
            for key, cat in d.items():
                key = str(key).upper().strip().replace(" ", "-").replace("_", "-")
                cat = str(cat).title().strip()
                if key and cat in CATEGORIE:
                    dizi[key] = cat
                    n_ok += 1
            print(f"blocco {i // chunk + 1}: {n_ok} nuove parole chiave (tot {len(dizi)})", flush=True)
            break
        time.sleep(1)
    # normalizza le categorie
    canon = {c.upper(): c for c in CATEGORIE}
    return {k: (canon[v.upper()] if v.upper() in canon else "Altro") for k, v in dizi.items()}


def main() -> int:
    nomi = raccogli_prodoti()
    print(f"Prodotti unici: {len(nomi)}")
    dizi = genera_dict(nomi)
    CATEGORIE_FILE.write_text(json.dumps(dizi, indent=2, ensure_ascii=False))
    print(f"Dizionario salvato: {len(dizi)} parole chiave in {CATEGORIE_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
