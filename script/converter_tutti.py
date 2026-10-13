"""Converte i PDF di scontrini/ in righe di testo (dati/estrazione/<nome>.json).

Usa docling (CPU): legge gli items di testo con le loro bounding box e
ricostruisce le righe originali per coordinate Y (i prodotti sono nella
colonna di sinistra, i prezzi a destra; docling li unisce in un unico
blocco, perdendo il layout).

Formato di output (JSON): lista di righe di testo, nell'ordine del
documento. Idempotente: i file già convertiti sono saltati.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCONTRINI = ROOT / "scontrini"
ESTRAZIONE = ROOT / "dati" / "estrazione"
ERRORI = ROOT / "dati" / "estrazione_errori.json"


def costruisci_righe(items: list) -> list[str]:
    """Ricostruisce le righe di testo dagli items con bbox (y, x).

    Items sono oggetti docling con .text e .prov[0].bbox (l, t, r, b,
    origin BOTTOMLEFT). Gruppa per coordinata Y (centro del bbox) e ordina
    gli items della riga per X.
    """
    if not items:
        return []
    centro = []
    for it in items:
        provs = it.prov or []
        if not provs or not it.text:
            continue
        b = provs[0].bbox
        y = (b.t + b.b) / 2  # centro verticale
        x = b.l
        centro.append((y, x, it.text.strip()))
    if not centro:
        return []
    centro.sort(key=lambda t: (-t[0], t[1]))
    # distanza media tra righe consecutive (per il threshold di clustering)
    ys = [c[0] for c in centro]
    gaps = [ys[i] - ys[i + 1] for i in range(len(ys) - 1) if ys[i] - ys[i + 1] > 0.5]
    gaps.sort()
    thr = statistics.median(gaps) * 0.5 if gaps else 3.0
    righe: list[str] = []
    cur_y = None
    cur = []
    for y, x, txt in centro:
        if cur_y is None or abs(y - cur_y) > thr:
            if cur:
                righe.append(" ".join(cur))
            cur = [txt]
            cur_y = y
        else:
            cur.append(txt)
    if cur:
        righe.append(" ".join(cur))
    return righe


def converti_pdf(pdf: Path, fuerza_layout: bool = False) -> Path:
    """Converte un singolo PDF in righe di testo (JSON).

    Usa il pipeline nativo di docling (docling-parse, nessuna GPU, nessun
    modello) che preserva la layer di testo del PDF riga per riga. La riga
    finale è ricostruita dai bbox degli items (gruppo per coordinata Y, poi
    ordinata per X): in questo modo prodotto e prezzo finiscono sulla
    stessa riga come nello scontrino originale.
    """
    from docling.datamodel.base_models import InputFormat
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.pipeline.native_pdf_pipeline import NativePdfPipeline

    conv = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_cls=NativePdfPipeline)})
    res = conv.convert(str(pdf))
    items = [t for t in res.document.texts if t.text]
    righe = costruisci_righe(items)
    out = ESTRAZIONE / (pdf.stem + ".json")
    out.write_text(json.dumps(righe, ensure_ascii=False, indent=0))
    return out


def main(force: bool = False) -> None:
    """Riconversione: sovrascrive i JSON esistenti (output derivati, idempotente)."""
    ESTRAZIONE.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(SCONTRINI.glob("*.pdf"))
    if force:
        pending = pdfs
    else:
        pending = [p for p in pdfs if not (ESTRAZIONE / (p.stem + ".json")).exists()]
    print(f"Totale: {len(pdfs)}, da convertire: {len(pending)}", flush=True)
    errori = {}
    for i, pdf in enumerate(pending):
        t0 = time.time()
        try:
            converti_pdf(pdf)
            print(f"[{i+1}/{len(pending)}] OK {pdf.name} ({time.time()-t0:.1f}s)", flush=True)
        except Exception as e:  # noqa: BLE001
            errori[pdf.name] = str(e)
            print(f"[{i+1}/{len(pending)}] ERRORE {pdf.name}: {e}", flush=True)
    ERRORI.write_text(json.dumps(errori, indent=2, ensure_ascii=False))
    print("FATTO. Errori:", len(errori), flush=True)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="riconverte anche i già presenti")
    args = ap.parse_args()
    main(force=args.force)


if __name__ == "__main__":
    sys.exit(main())
