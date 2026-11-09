# Regole e Convenzioni del Progetto: Pokédex TCG

## Obiettivo e Architettura
- **Progetto:** App web per tracciare e stimare una collezione di carte Pokémon.
- **Stack Tecnologico:** Backend in Python (Flask), Database in SQLite, Frontend in HTML puro con Tailwind CSS via CDN.
- **Stile UI:** Dashboard professionale in stile SaaS/fintech: tema dark (blu notte), card con angoli arrotondati e ombre morbide.

## UI / Design System
- **Framework CSS:** Bootstrap 5.3 + Bootstrap Icons via CDN; tema dark tramite `data-bs-theme="dark"`.
- **CSS dell'app:** `static/css/app.css` (variabili `--app-*`); i template non contengono CSS inline.
- **JavaScript:** `static/js/app.js` (IIFE, nessuna dipendenza oltre a Bootstrap/Chart.js). La configurazione (URL degli endpoint, utente, lingua) arriva da `<script id="app-config" type="application/json">` generato dal template.
- **Template:** `base.html` (shell: navbar + sidebar), `index.html` (dashboard/collezione), `news.html` (Mercato & News).
- **Responsività:** sidebar fissa su desktop (≥992px) e offcanvas con hamburger su mobile; griglia carte `row-cols-2 → 5`.
- **Grafici:** Chart.js via CDN; il contenitore è `<div id="market-chart">` dentro la scheda della carta.
- **Dati di mercato:** `/api/card/<id>` restituisce anche `market` (history 30 giorni, EMA7/EMA30, Z-Score, momentum, trend). **Nota:** lo storico è attualmente simulato (`market.simulated = true`) in attesa dei dati storici reali.


## Regole di Sistema (Windows)
- **Comandi Python:** Non usare mai `python` o `pip` da soli. 
- **Esecuzione:** Usa ESCLUSIVAMENTE `py -3.12`.
- **Installazione:** Installa i pacchetti usando ESCLUSIVAMENTE `py -3.12 -m pip`.

## Fonti Dati
- **API Base:** Usa `https://api.pokemontcg.io/v2/` per scaricare carte e set.
- **Prezzi:** Usa ESCLUSIVAMENTE i dati di Cardmarket (in Euro, €). Estrai `cardmarket.prices.trendPrice` o `averageSellPrice`.
- **Rate Limiting:** Aggiungi sempre `headers={'User-Agent': 'Mozilla/5.0'}` alle chiamate API e usa la cache locale per i dati statici (come la lista dei set).

## Roadmap Futura (Da tenere a mente)
- **Multi-utente:** Predisporre il database per un futuro sistema di Login (ogni utente avrà la sua collezione).
- **Scansione:** Implementata: riconoscimento delle carte dalla fotocamera tramite Google Gemini (AI Vision) e aggiunta automatica alla collezione (`POST /api/scan-card`).