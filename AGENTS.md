# Regole del progetto — Archivio scontrini Esselunga

## Obiettivo del progetto
Gestire, leggere e analizzare i scontrini PDF della tessera Esselunga
dei propri negozi di riferimento, sporgati in `scontrini/`.

## Struttura del progetto
- `scontrini/` — archivio dei PDF originali (fonte di verità)
- I dati derivati (CSV, report, script) si creano in cartelle dedicate alla radice
  (es. `dati/`, `report/`, `script/`), **mai dentro `scontrini/`**

## Regole di sicurezza (assolute)
1. **Nessuna cancellazione**: non eliminare, sovrascrivere o spostare alcun file di
   altre cartelle del PC; operare **solo all'interno della cartella `esselunga/`**.
   Niente `rm`, niente `git rm`, niente riscrittura distruttiva di file altrui.
2. **Gli scontrini in `scontrini/` non si toccano**: mai cancellati, rinominati,
   spostati o modificati. Sono fonte di verità immutabile.
3. **Il progetto è un repository git**: ogni modifica (nuovi scontrini, regole, dati
   derivati, script, regole di questo file) va salvata con un **commit** descrittivo
   in italiano. Il commit è il record degli stati; niente operazioni che non siano
   tracciabili nel log git.

## Regole su `scontrini/`
1. **I PDF originali sono read-only**: non rinominare, non modificare, non cancellare mai i file esistenti.
2. Ogni scontrino ha una riga di acquisto: nessun scontrino duplicato con stesso nome.
3. I nuovi file seguono la convenzione:
   `YYYY-MM-DD - Esselunga di <negozio> - <importo> EUR.pdf`
   (data = data della transazione, importo = totale speso con due decimali e punto come separatore).
4. Prima di aggiungere un PDF, verificare che l'importo nel nome corrisponda
   all'ultimo `TOTALE` presente nel testo del file (sezione RICEVUTA DI PAGAMENTO).

## Lettura dei PDF
- **Strumenti in un ambiente conda dedicato**: prima di usare Python/docling eseguire sempre
  `source /opt/conda/etc/profile.d/conda.sh && conda activate docling`
  (l'ambiente `docling` si trova in `/opt/conda/envs/docling`).
- **GPU riservata a llama-server**: docling deve girare **sempre su CPU**,
  perché la GPU è necessaria al llama-server che gira in parallelo. La GPU è
  l'impostazione di default (`device="auto"`): va forzata esplicitamente
  con `AcceleratorOptions(device="cpu")`, altrimenti i modelli di docling
  occupano la GPU e il llama-server va in OOM (e viceversa).
- Usare **docling** per estrarre testo/struttura dai scontrini (layout, sezioni, tabelle);
  `pdftotext <file> -` è ammesso solo come fallback rapido.
- Pattern consigliato (docling 2.13x, API con `format_options`):
  ```python
  from docling.datamodel.base_models import InputFormat
  from docling.datamodel.pipeline_options import PdfPipelineOptions
  from docling.document_converter import DocumentConverter, PdfFormatOption

  from docling.datamodel.accelerator_options import AcceleratorOptions

  conv = DocumentConverter(format_options={
      InputFormat.PDF: PdfFormatOption(
          pipeline_options=PdfPipelineOptions(
              accelerator_options=AcceleratorOptions(device="cpu"),
              do_table_structure=False,
          )
      )
  })
  res = conv.convert("scontrini/<file>.pdf")
  res.document.save_as_markdown("dati/<output>.md")
  ```
  La conversione di uno scontrino (1-2 pagine) richiede ~10 s di wall-time su CPU;
  i pesi dei modelli (layout RTDETR + RapidOCR) vengono scaricati automaticamente
  al primo avvio in `site-packages/rapidocr/models` e `artifacts/`.
  Nota: `DocumentConverter` non accetta `pipeline_options=` direttamente; i nomi pubblici
  (es. `DocumentConverter`) vanno importati dai moduli sottostanti (`docling.document_converter`,
  `docling.datamodel.pipeline_options`) se l'`__init__` del package non li espone.
- Struttura tipica: intestazione (P.I., negozio), elenco prodotti con eventuali
  `SCONTO xx%`, poi sezioni `RICEVUTA DI PAGAMENTO` con data/ora, metodo di pagamento
  e `TOTALE`.
- Un file può contenere più transazioni (es. due scontrini su carta): l'importo
  del nome è il totale dell'ultima transazione registrata.

## Convenzioni generali
- **Lingua**: italiano per comunicazioni, commenti nei codici, nomi di cartelle e report.
- **Valori monetari**: sempre in euro, due decimali, separatore di migliaia solo nei report umani.
- **Nessuna credenziale o dato bancario completo**: nei file derivati non includere
  numeri di carta/COD.AUT. dei scontrini; il metodo di pagamento basta (es. "carta Fidaty", "Mastercard").
- **Idempotenza**: gli script di estrazione/analisi possono essere rieseguiti
  liberamente senza effetti collaterali (sovrascrivono i propri output in `dati/` o `report/`).
