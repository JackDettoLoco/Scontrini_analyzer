#!/usr/bin/env bash
# Avvia la web app locale (dashboard spesa Esselunga) su 127.0.0.1.
#
# Cerca l'ambiente Python con i pacchetti necessari (docling, fastapi, uvicorn):
#   1) conda  -> se il file CONDA_SH esiste lo carica, poi attiva CONDA_ENV
#   2) fallback -> il python gia' nel PATH (se i pacchetti sono gia' installati)
#
# Variabili d'ambiente (opzionali):
#   CONDA_SH    percorso di conda.sh   (default /opt/conda/etc/profile.d/conda.sh)
#   CONDA_ENV   nome ambiente conda    (default docling)
#   ESSEL_PORT  porta web              (default 8790)
#   ESSEL_HOST  host                   (default 127.0.0.1, solo locale)
set -e
cd "$(dirname "$0")"

export ESSEL_PORT="${ESSEL_PORT:-8790}"
export ESSEL_HOST="${ESSEL_HOST:-127.0.0.1}"
CONDA_SH="${CONDA_SH:-/opt/conda/etc/profile.d/conda.sh}"
CONDA_ENV="${CONDA_ENV:-docling}"

USO_CONDA=0
if [ -f "$CONDA_SH" ]; then
  # shellcheck disable=SC1091
  . "$CONDA_SH"
  if command -v conda >/dev/null 2>&1; then
    conda activate "$CONDA_ENV" && USO_CONDA=1
  fi
fi
if [ "$USO_CONDA" -eq 0 ] && command -v conda >/dev/null 2>&1; then
  conda activate "$CONDA_ENV" && USO_CONDA=1
fi

if [ "$USO_CONDA" -eq 1 ]; then
  PY=python
else
  PY="${PYTHON:-python3}"
  echo "(nessun conda trovato: uso $PY; se manca un pacchetto: $PY -m pip install -r requirements.txt)"
fi

echo "Dashboard: http://$ESSEL_HOST:$ESSEL_PORT"
exec "$PY" webapp/app.py
