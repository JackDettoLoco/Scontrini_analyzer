"""Classificatore deterministico: nome prodotto -> categoria.

Due strati, nell'ordine:
1. Rete curata (parole chiave italiane di base, offline).
2. Dizionario LLM (dati/categorie_llm.json, generato col modello locale
   per prodotti non coperti dalla rete): vince il match più lungo; le
   voci del dizionario con categoria "Altro" sono ignorate (troppo
   aggressive) e quelle che collidono con la rete curata perdono.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIZIONARIO = ROOT / "dati" / "categorie_llm.json"
OVERRIDE = ROOT / "dati" / "override_categorie.json"  # assegnazioni manuali dalla webapp

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

BASELINE: list[tuple[str, list[str]]] = [
    ("Frutta e Verdura", [
        "ARANCIO", "ARANCE", "ARANGE", "ARANCIA", "BANANA", "BANANE", "MELA",
        "MELE", "MELAGRANA", "UVA", "ANANAS", "POMELO", "KIWI", "MANGO",
        "PAPAYA", "MELONI", "MELONE", "PESCA", "PESCHE", "PERE", "PRUGNE",
        "FRAGOLE", "FRAGOLI", "MELANZANA", "MELANZANE", "PEPERONI",
        "PEPERONE", "CETRIOLI", "CETRIOLO", "POMODORO", "POMODORINI", "CAROTA",
        "CAROTE", "PATATA", "PATATE", "PATATO", "CIPOLLA", "CIPOLLE",
        "CIPOLLOTTI", "CIPOLLOTTA", "AGLIO", "PORRO", "PORRI", "CAVO", "CAVOLI",
        "CAVOLINI", "ZUCCHINE", "ZUCCHINO", "ZUCCA", "SPINACIO", "SPINACI",
        "INSALATA", "INSALATTI", "LATTUGA", "LATTUCCIA", "SEDANO", "FUNGHI",
        "PLEUROTUS", "PIOPPI", "CARCIOFI", "CARCIOFO", "BROCCOLO",
        "BROCCOLI", "FAGIOLI", "FASOLATO", "PETALI", "VALERIANA", "ZUCHE",
        "RADA", "MAIS",
    ]),
    ("Carne e Polli", [
        "POLLO", "POLLA", "MANZO", "BUE", "VITELLO", "CONIGLIO", "ANATRA",
        "ANATRI", "ANATRE", "SPALLA", "BISTECCA", "BISTECHE", "BRASATE",
        "BRASATE", "MACINATO", "MACINA", "SALSICCIA", "SALSICCIE", "COTOLETTE",
        "COTOLETTO", "PETTO", "COSCE", "COSCI", "POLLETTO", "GALLINE", "GALLINA",
        "BACONE", "BACON",
    ]),
    ("Pesce e Frutti di Mare", [
        "PESCE", "PESCI", "TONNO", "TONNE", "SARDINE", "SARDINELLE", "ACCIUGHE",
        "ACCIUGA", "SALMONE", "GAMBERI", "GAMBERO", "GAMBETTI", "SCAMPI",
        "FILETTI", "FILETTO", "MUSSELI",
    ]),
    ("Latticini e Formaggi", [
        "LATTE", "FORMAGGI", "FORMAGGIO", "MOZZA", "MOZZARELLA", "MOZZARELLI",
        "SCAMORZA", "SCAMORZZA", "SCAMORZE", "RICOTTA", "YOG", "YOGHURT",
        "YOGURT", "CREMA", "CREME", "BURRO", "GADO", "GRATT", "PADANO",
        "PECORINO", "PROVOL", "PROVOLA", "GOUDA", "GORGONZOLA", "ARBOREA",
        "MUKKI", "PODERE", "CREMINA", "GRATTUGIATO",
    ]),
    ("Uova", ["UOVA", "UOVO", "UOVAX"]),
    ("Pane e Forno", ["PANE", "PIADINA", "PIZZA", "PIZZE", "FOCACCIA", "FOCACCIE",
                     "FILONE", "SCOTTONO", "SCOTTONI", "SCHITTA"]),
    ("Pasta, Riso e Cereali", [
        "PASTA", "SPAGHETTI", "RIGATONI", "FUSILLI", "ELICOIDALI", "PENNE",
        "LASAGNA", "TORTIGLIONI", "TORTIGLIONI", "CANNELLONI", "CANNELLINO",
        "ORECCHIETTE", "RAVIOLI", "RISOTTO", "RISO", "FARINA", "FARRO", "CEREALI",
        "CEREALI", "FLOK", "MUESLI", "CRACKER", "BISCOTTI", "BUCKWHEAT",
        "COTTO", "GOOD",
    ]),
    ("Salumi", ["SALUMI", "SALUMI", "PROSCIUTTO", "TAVOLATA", "TAVOLATE",
                "TAVOLATO", "MORTADELLA", "PETTINATO", "PETTINATA", "SPINA"]),
    ("Dolci e Merendine", [
        "DOLCI", "DOLCE", "MERENDINE", "MERENDA", "MERENDINA", "FROLLINI",
        "FROLLINO", "FROLLA", "CANNELLINI", "CANNELLINO", "PANDORO", "PANDORO",
        "TIRAMISU", "TIRAMISU", "BRIOCHE", "CASSATA", "MARM", "PISTAC", "PISTA",
        "MARMARITA",
    ]),
    ("Vini e Superalcolici", ["VINO", "VINI", "ROSA", "ROSA", "SPOLETTA",
                              "SPUMANTE", "PROSECCO", "PROSECO", "GRAPPA",
                              "GRAPPA", "GRAPPO", "LIQUORI", "LISCIVIA"]),
    ("Birra e Bevande", [
        "BIRRA", "BIRRE", "SODA", "SODAS", "ARANCIALI", "ARANCIALI", "NETTARE",
        "NETTARI", "VALFRUTTA", "VALFRU", "ANALCOLICHE", "BEVANDA", "BEVANDE",
        "ACQUA", "CIOCCOL", "CIOCCO", "TEA", "TISAN", "LIMONATE",
    ]),
    ("Surgelati", ["SURGELATI", "SURGELATI", "GELATO", "GELATI", "GELATO"]),
    ("Curio e Freschismi", ["PIADINA", "TORTINO"]),
    ("Cura della Persona", [
        "SHAMPOO", "SHAMPOO", "SMETTONI", "SMETTONI", "SMETTONO", "DEO",
        "DENTIFRICIO", "DENTIFRIZIO", "DENTALE", "COSMETICI", "COSMETICHE",
        "TRUCCO", "TRUCCO",
    ]),
    ("Igiene e Detersivi", [
        "DETERSIVI", "DETERSIVO", "DETERGENTE", "DETERGENTE", "SAPONE", "SAPONI",
        "ASSORBIODORI", "ASSORB", "STIRATO", "STIRATO", "STIRA", "SUGHERO",
    ]),
    ("Prodotti per Animali", ["CIBO", "CIBI", "MANGIME", "MANGIMI", "UMIDO",
                               "GRANULO", "GRANULATO", "CROCCANTINI", "ADULT",
                               "MEDIUM", "CANE", "CANI", "GATTO", "GATTI"]),
]


def _rx_token(parola: str) -> str:
    return r"(?<![A-Za-z])" + re.escape(parola) + r"(?![A-Za-z])"


def _costruisci() -> list[tuple[re.Pattern, str]]:
    """Pattern ordinati: la rete curata prima (più lunga vince), poi il
    dizionario LLM (solo voci con categoria concreta, non "Altro")."""
    dizi: dict[str, str] = {}
    if DIZIONARIO.exists():
        dizi = json.loads(DIZIONARIO.read_text())
    # rete curata (tutti i suoi token)
    pattern: list[tuple[re.Pattern, str]] = []
    baseline_tokens: dict[str, str] = {}
    for cat, parole in BASELINE:
        for p in parole:
            rx = re.compile(_rx_token(p))
            pattern.append((rx, cat))
            baseline_tokens.setdefault(p.upper(), cat)
    # dizionario LLM: aggiungi solo parole chiave che NON collidono con la rete
    for key, cat in dizi.items():
        if cat == "Altro":
            continue
        parole = [p for p in re.split(r"[-_ ]+", key) if p]
        if not parole:
            continue
        if any(p.upper() in baseline_tokens for p in parole):
            continue
        rx = "".join(_rx_token(p) + r"\s*" for p in parole)
        pattern.append((re.compile(rx), cat))
    pattern.sort(key=lambda t: len(t[0].pattern), reverse=True)
    return pattern


COMPILE = [_costruisci()]
CANON = {c.upper(): c for c in CATEGORIE}


def _override() -> dict[str, str]:
    """Asegnazioni manuali fatte dalla webapp: {NOME_PRODOTTO: categoria}."""
    if OVERRIDE.exists():
        try:
            d = json.loads(OVERRIDE.read_text())
            return {k.upper(): v for k, v in d.items()}
        except Exception:  # noqa: BLE001
            return {}
    return {}


def categoria_prodotto(nome: str) -> str:
    """Restituisce la categoria del prodotto (deterministica).

    Ordine: override manuali (webapp) -> rete curata/dizionario LLM."""
    n = nome.upper()
    ov = _override()
    if n in ov:
        return ov[n]
    for rx, cat in COMPILE[0]:
        if rx.search(n):
            return CANON.get(cat.upper(), cat)
    return "Altro"


if __name__ == "__main__":
    import sys

    for arg in sys.argv[1:]:
        print(arg, "->", categoria_prodotto(arg))
