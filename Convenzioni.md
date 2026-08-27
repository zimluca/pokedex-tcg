# Regole e Convenzioni del Progetto: Pokédex TCG

## Obiettivo e Architettura
- **Progetto:** App web per tracciare e stimare una collezione di carte Pokémon.
- **Stack Tecnologico:** Backend in Python (Flask), Database in SQLite, Frontend in HTML puro con Tailwind CSS via CDN.
- **Stile UI:** L'interfaccia deve richiamare un Pokédex moderno e hi-tech, con menù laterale per le espansioni.

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
- **Scansione:** Futura implementazione dell'aggiunta carte tramite fotocamera (Computer Vision).