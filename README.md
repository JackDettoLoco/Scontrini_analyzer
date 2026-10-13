# Spesa Esselunga

Dashboard locale (FastAPI + Chart.js) che legge i **scontrini PDF** di Esselunga,
estrae transazioni, prodotti e sconti e mostra la spesa interattivamente:
per periodo, per categoria, per negozio, top prodotti e andamenti.

- **Solo locale**: la web app si lega a `127.0.0.1` (nessuna esposizione pubblica).
- **CPU-only**: l'estrazione PDF usa `docling` in modalità *nativa* (nessun modello,
  nessuna GPU — la GPU è riservata al llama-server).

---

## Cosa fa

1. **Estrae** i PDF in `scontrini/` in righe di testo (`dati/estrazione/*.json`),
   ricostruendo riga per riga dalle coordinate dei testi.
2. **Parsa** ogni scontrino: transazioni (una per "RICEVUTA DI PAGAMENTO"),
   prodotti (nome, prezzo pieno e **prezzo netto** = quanto è davvero stato pagato)
   e categoria (classificatore deterministico: dizionario LLM + regole di base).
3. **Calcola gli sconti** (FIDATY/promo per prodotto, buoni e sconti di pagamento).
4. **Spara il DB** SQLite (`dati/spese.db`) e una dashboard interattiva.
5. **Rileva i scontrini nuovi** al via e su richiesta, e permette la
   **riassegnazione categorie** da pagina web.

---

## Struttura

```
scontrini/                 # PDF originali (IMMUTABILI: non rinominare/muovere/cancellare)
dati/estrazione/*.json     # righe di testo estratte dai PDF (derivati, rigenerabili)
dati/spese.db              # DB SQLite (auto-rigenerato all'avvio; non tracciato in git)
dati/categorie_llm.json    # dizionario keyword->categoria (generato dal modello locale)
dati/override_categorie.json# riassegnazioni manuali fatte dalla pagina categorie
dati/sconti.json           # dettaglio sconti per ricevuta
script/                    # pipeline (parser, classificatore, estrazione sconti, ...)
webapp/app.py              # FastAPI (dashboard + API)
webapp/static/             # frontend (index.html, categorie.html, chart.js inlinati)
start.sh                   # avvia la web app
requirements.txt           # dipendenze
```

Nota: `scontrini/` e `dati/estrazione/` **non fanno parte del repository**
(sono ignorati da git per privacy): i tuoi PDF vanno copiati in `scontrini/`
prima del primo avvio; l'estrazione la genera l'app.

---

## Requisiti

- **Python 3.9+**
- **Pacchetti**: `fastapi`, `uvicorn`, `docling` (per i PDF), `httpx`
  (vedi `requirements.txt`).

Due modi per avere l'ambiente:

### A. Ambiente conda (metodo di default)
```bash
source /opt/conda/etc/profile.d/conda.sh
conda activate docling
```
(il nome e il percorso sono configurabili, vedi "Configurazione").

### B. PIP / venv
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## Avvio

```bash
./start.sh
# Dashboard: http://127.0.0.1:8790
```

`start.sh` cerca l'ambiente conda (default `docling`) e, in mancanza, usa il
python nel PATH. All'avvio l'app:

- rigenera il DB dai file `dati/estrazione/*.json` (rapido, nessun PDF);
- rileva **scontrini nuovi** in `scontrini/` e li elabora in background (docling).

---

## Uso

| Pagina | URL | Cosa fa |
|---|---|---|
| **Dashboard** | `http://127.0.0.1:8790/` | KPI, grafici per periodo/categoria/negozio, top prodotti, sconti. Slider per il lasso temporale e chip per filtrare per categoria. |
| **Categorie** | `http://127.0.0.1:8790/categorie` | Riassegna la categoria a ogni prodotto (dropdown), con ricerca, filtro e creazione di categorie nuove. Salvataggio automatico. |
| **Scontrino** | `http://127.0.0.1:8790/scontrino/{id}` | Dettaglio di una singola ricevuta (prodotti con l'effettivo pagato, sconti). |

### Filtri della dashboard
- **Selettore negozio** (ogni grafico mostra un negozio; "Tutti" = aggrega).
- **Slider di periodo** (due maniglie: da/a) → filtra KPI, grafici e sconti.
- **Chip categorie** (una o più) → filtra KPI, grafici e sconti.

### API (per script)
`/api/riepilogo?negozio=&da=&a=&cat=`, `/api/negozi`, `/api/categorie`,
`/api/prodotti`, `/api/sovrascritte`, `POST /api/assegna`, `POST /api/ricarica`,
`/api/stato`, `/api/sconti?da=&a=&cat=`, `/api/periodo`, `/file/{nome}`.

---

## Configurazione

Valori leggiti da variabili d'ambiente (con default, così il comportamento non
cambia se non le imposti):

| Variabile | Default | Descrizione |
|---|---|---|
| `ESSEL_HOST` | `127.0.0.1` | Host di ascolto (default: solo locale). |
| `ESSEL_PORT` | `8790` | Porta web. |
| `CONDA_SH` | `/opt/conda/etc/profile.d/conda.sh` | Percorso di `conda.sh` (per `start.sh`). |
| `CONDA_ENV` | `docling` | Nome ambiente conda (per `start.sh`). |
| `LLM_BASE_URL` | `http://127.0.0.1:18081/v1` | Endpoint LLM (per `script/genera_dizionario.py`). |
| `LLM_MODEL` | `qwen38-27b-ridge-3.7bpw-160k` | Modello LLM. |
| `LLM_API_KEY` | (da `~/.config/qwen38-pi/api-key`) | Chiave per il LLM. |

Esempio:
```bash
ESSEL_PORT=9000 CONDA_ENV=docling ./start.sh
```

---

## Come funziona la classificazione e gli sconti

- **Categoria**: per ogni prodotto, in ordine di priorità — override manuale
  (`dati/override_categorie.json`) > regole di base > dizionario LLM. Le categorie
  sono *aperte*: dalla pagina categorie se ne possono creare di nuove.
- **Prezzo**: ogni prodotto ha un prezzo *pieno* (a scaffale) e un **prezzo netto**
  (quanto è davvero stato pagato = pieno − sconti FIDATY/promo della sua riga).
  I grafici usano il **netto**.
- **Sconti**: FIDATY/promo (attribuiti al prodotto), buoni e sconto di pagamento
  (a livello di ricevuta). Il totale sconti è quanto risparmi sul listino.

---

## Come è stato costruito

Questo progetto è stato sviluppato **interamente da un agente AI in locale**,
senza alcun servizio cloud:

- **Agente**: [pi](https://github.com/badlogic/pi-mono) (pi-coding-agent),
  che ha letto le regole in `AGENTS.md` e ha iterato: lettura dei PDF, parser,
  classificazione, dashboard, grafici, riassegnazioni manuali, documentazione.
- **Modello**: Qwen 3.8 (27B) in quantizzazione *ridge 3.7bpw* con contesto 160k
  (`qwen38-27b-ridge-3.7bpw-160k`), servito in locale con **llama.cpp**
  (`llama-server`) su una **RTX 4080 Super**.
- **Split GPU/CPU**: il LLM girava sulla GPU; l'estrazione PDF (docling) e
tutta la pipeline Python su CPU, così i due non si contendevano la memoria.
- **Classificazione**: il dizionario keyword→categoria è stato generato dal
  modello locale (`script/genera_dizionario.py`), poi rifinito con regole
deterministiche e riassegnazioni manuali dalla pagina web (le voci "Altro" portate da 441 a 15
in due giri, con ricerche web per i prodotti non ovvi).

Il risultato: un pipeline completo (estrazione, parsing, DB, dashboard) scritto
e debuggato dall'agente, con l'umano che fornisce solo input, regole e feedback.

## ⚠️ Privacy

Questo repository è **anonimizzato**: non contiene scontrini, dati estratti,
database o altri dati personali (vedi `.gitignore`). Metti i tuoi PDF in
`scontrini/` e i dati derivati generati dall'app restano sul tuo disco
(`dati/estrazione/`, `dati/spese.db`, ...), **mai in git**.

Non caricare mai su GitHub: `scontrini/*.pdf`, `dati/estrazione/`,
`dati/spese.db`, `dati/sconti.json`.

---

## Script di manutenzione (opzionali)

In `script/`:
- `converter_tutti.py` — riconverte i PDF in JSON (con `--force` per rifare tutti).
- `estrai_sconti.py` — rigenera `dati/sconti.json`.
- `genera_dizionario.py` — rigenera il dizionario di categorie dal modello locale.
- `riassegna_altro.py`, `cerca_voci.py` — helper per le riassegnazioni.
