# -*- coding: utf-8 -*-
"""Verifica wiki (REST summary) dei termini dubbi, con retry/pausa anti-429."""
import json, time, urllib.parse, urllib.request

UA = "Marta/1.0 (ricerca prodotti; uso locale)"
CTX = __import__("ssl").create_default_context()

def get(url, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            return urllib.request.urlopen(req, timeout=20, context=CTX).read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429:
                time.sleep(2.5 * (i + 1))
            else:
                break
    return f"[{getattr(last, 'code', '?')}] " if last else ""

def summary(term):
    u = "https://it.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(term)
    d = json.loads(get(u) or "{}")
    return (d.get("extract") or "").replace("\n", " ")

if __name__ == "__main__":
    termini = [
        "Vipiteno",
        "Caciotta",          # per Nadorcott (tipo formaggio?)
        "Dama (disambigua)",
        "Nero d'Avola",
        "Limoncino",
        "Arancia amara",
    ]
    for t in termini:
        print("=" * 70)
        print("TERMINE:", t)
        s = summary(t)
        print("  ", (s[:300] if s else "(niente)"))
        time.sleep(1.2)
