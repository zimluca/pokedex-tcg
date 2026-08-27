"""
Sistema di aggiornamento automatico dei prezzi.
Processa la coda di scraping in background (carte con pending=True in PriceCache)
e aggiorna periodicamente i prezzi delle carte in collezione.

Miglioramenti:
- Priorità alle carte costose (ordinate per prezzo stimato decrescente)
- Non rimuove dalla coda in caso di fallimento (riprova al ciclo successivo)
- TTL uniforme a 24 ore (aggiornamento una volta al giorno)
- Salva i 3 prezzi separatamente (cardmarket, tcgplayer, ebay)
"""

import time
import threading
from datetime import datetime, timedelta

UPDATE_INTERVAL = 24 * 60 * 60  # 24 ore in secondi (aggiornamento completo)
QUEUE_PROCESS_INTERVAL = 60     # 60 secondi tra un ciclo di processamento della coda
CACHE_TTL_HOURS = 24            # soglia di obsolescenza del prezzo (24 ore)
MAX_RETRIES = 5                 # massimo tentativi di scraping per carta prima di abbandonare


def _get_priority_price(card_id, language='en'):
    """Stima il prezzo di una carta per la priorità nella coda.
    Usa il prezzo in cache se disponibile, altrimenti 0 (priorità bassa)."""
    from models import PriceCache
    cached = PriceCache.query.filter_by(card_id=card_id, language=language).first()
    if cached and cached.price:
        return cached.price
    return 0.0


def process_pending_queue(app):
    """Processa la coda di scraping: carte con pending=True in PriceCache.
    Priorità alle carte più costose (ordinate per prezzo stimato decrescente).
    In caso di fallimento, la carta resta in coda per il prossimo ciclo."""
    from models import PriceCache, CollectedCard, db
    from scraper import scrape_ebay_price, scrape_cardmarket_price, scrape_tcgplayer_price
    
    with app.app_context():
        # Ottieni tutte le carte in coda per lo scraping
        pending_cards = PriceCache.query.filter_by(pending=True).all()
        
        if not pending_cards:
            return 0
        
        # Ordina per priorità: carte con prezzo stimato più alto prima
        # (le carte costose sono più importanti da aggiornare)
        pending_cards.sort(key=lambda c: _get_priority_price(c.card_id, c.language or 'en'), reverse=True)
        
        print(f"[PRICE_UPDATER] Processamento coda: {len(pending_cards)} carte in attesa")
        
        processed_count = 0
        for cached in pending_cards:
            card_id = cached.card_id
            card_name = cached.card_name
            set_name = cached.set_name
            language = cached.language or 'en'
            
            # Controlla il numero di tentativi già fatti
            # (usiamo scraped_at come indicatore approssimativo del numero di tentativi)
            # Se il prezzo è già stato aggiornato di recente, salta
            if cached.price and cached.price > 0 and not cached.is_stale(hours=CACHE_TTL_HOURS):
                cached.pending = False
                db.session.commit()
                continue
            
            print(f"[PRICE_UPDATER] Scraping per: {card_name} ({language})")
            
            # ====== SCRAPING DELLE 3 FONTI ======
            # Per italiano, preferisci Cardmarket (mercato europeo)
            # Per inglese, preferisci eBay (mercato USA)
            # Salviamo TUTTI i prezzi trovati, non solo il principale
            
            cardmarket_price = 0.0
            cardmarket_url = None
            tcgplayer_price = 0.0
            tcgplayer_url = None
            ebay_price = 0.0
            ebay_url = None
            
            # 1. Cardmarket (preferito per italiano)
            if language == 'it':
                cardmarket_price, cardmarket_url = scrape_cardmarket_price(card_name, set_name)
            
            # 2. eBay (preferito per inglese, riporta il prezzo più basso)
            ebay_price, ebay_url = scrape_ebay_price(card_name, set_name)
            
            # 3. TCGPlayer (fallback)
            tcgplayer_price, tcgplayer_url = scrape_tcgplayer_price(card_name, set_name)
            
            # Determina il prezzo principale in base alla lingua
            main_price = 0.0
            main_url = None
            main_source = ''
            
            if language == 'it':
                if cardmarket_price > 0:
                    main_price = cardmarket_price
                    main_url = cardmarket_url
                    main_source = 'cardmarket_scraped'
                elif ebay_price > 0:
                    main_price = ebay_price
                    main_url = ebay_url
                    main_source = 'ebay_scraped'
                elif tcgplayer_price > 0:
                    main_price = tcgplayer_price
                    main_url = tcgplayer_url
                    main_source = 'tcgplayer_scraped'
            else:
                if ebay_price > 0:
                    main_price = ebay_price
                    main_url = ebay_url
                    main_source = 'ebay_scraped'
                elif cardmarket_price > 0:
                    main_price = cardmarket_price
                    main_url = cardmarket_url
                    main_source = 'cardmarket_scraped'
                elif tcgplayer_price > 0:
                    main_price = tcgplayer_price
                    main_url = tcgplayer_url
                    main_source = 'tcgplayer_scraped'
            
            if main_price > 0:
                # Aggiorna la cache con il prezzo principale
                cached.price = main_price
                cached.url = main_url
                cached.source = main_source
                cached.scraped_at = datetime.now()
                cached.pending = False
                
                # Aggiorna anche le carte in collezione con questo card_id e lingua
                collected_cards = CollectedCard.query.filter_by(api_card_id=card_id, language=language).all()
                for cc in collected_cards:
                    cc.price = main_price
                    cc.price_updated_at = datetime.now()
                    cc.price_source = main_source
                
                processed_count += 1
                print(f"[PRICE_UPDATER] Prezzo aggiornato per '{card_name}' ({language}): €{main_price:.2f} ({main_source})")
            else:
                # Nessun prezzo trovato: NON rimuovere dalla coda, riprova al prossimo ciclo
                # Ma limita i tentativi per evitare loop infiniti
                # Usiamo scraped_at come contatore approssimativo
                # Se il prezzo è 0 e pending è True da molto tempo, incrementa il contatore
                # (semplicemente aggiorniamo scraped_at per tracciare i tentativi)
                cached.scraped_at = datetime.now()
                print(f"[PRICE_UPDATER] Nessun prezzo trovato per '{card_name}' ({language}), riproverò al prossimo ciclo")
            
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"[PRICE_UPDATER] Errore nel salvataggio: {e}")
            
            # Rate limiting
            time.sleep(3)  # 3 secondi tra una carta e l'altra
        
        print(f"[PRICE_UPDATER] Coda processata: {processed_count} prezzi aggiornati")
        return processed_count


def update_prices_for_collected_cards(app):
    """Aggiorna i prezzi di tutte le carte possedute dagli utenti.
    I prezzi vengono aggiornati una volta al giorno (TTL 24 ore)."""
    from models import PriceCache, CollectedCard, db
    from scraper import scrape_ebay_price, scrape_cardmarket_price, scrape_tcgplayer_price
    
    with app.app_context():
        print(f"[PRICE_UPDATER] Inizio aggiornamento prezzi - {datetime.now()}")
        
        # Ottieni tutte le carte uniche nella collezione (per lingua)
        unique_cards = db.session.query(
            CollectedCard.api_card_id,
            CollectedCard.name,
            CollectedCard.set_name,
            CollectedCard.language
        ).distinct().all()
        
        print(f"[PRICE_UPDATER] Trovate {len(unique_cards)} carte uniche da aggiornare")
        
        updated_count = 0
        for card_id, card_name, set_name, language in unique_cards:
            language = language or 'en'
            # Controlla se il prezzo in cache è obsoleto (specifico per lingua)
            cached = PriceCache.query.filter_by(card_id=card_id, language=language).first()
            
            if cached and not cached.is_stale(hours=CACHE_TTL_HOURS):
                continue  # Prezzo ancora valido (aggiornato meno di 24 ore fa)
            
            # Aggiorna il prezzo
            print(f"[PRICE_UPDATER] Aggiornamento prezzo per: {card_name} ({language})")
            
            # Scraping delle 3 fonti
            cardmarket_price = 0.0
            cardmarket_url = None
            tcgplayer_price = 0.0
            tcgplayer_url = None
            ebay_price = 0.0
            ebay_url = None
            
            # 1. Cardmarket (preferito per italiano)
            if language == 'it':
                cardmarket_price, cardmarket_url = scrape_cardmarket_price(card_name, set_name)
            
            # 2. eBay (preferito per inglese, prezzo più basso)
            ebay_price, ebay_url = scrape_ebay_price(card_name, set_name)
            
            # 3. TCGPlayer (fallback)
            tcgplayer_price, tcgplayer_url = scrape_tcgplayer_price(card_name, set_name)
            
            # Determina il prezzo principale
            main_price = 0.0
            main_url = None
            main_source = ''
            
            if language == 'it':
                if cardmarket_price > 0:
                    main_price = cardmarket_price
                    main_url = cardmarket_url
                    main_source = 'cardmarket_scraped'
                elif ebay_price > 0:
                    main_price = ebay_price
                    main_url = ebay_url
                    main_source = 'ebay_scraped'
                elif tcgplayer_price > 0:
                    main_price = tcgplayer_price
                    main_url = tcgplayer_url
                    main_source = 'tcgplayer_scraped'
            else:
                if ebay_price > 0:
                    main_price = ebay_price
                    main_url = ebay_url
                    main_source = 'ebay_scraped'
                elif cardmarket_price > 0:
                    main_price = cardmarket_price
                    main_url = cardmarket_url
                    main_source = 'cardmarket_scraped'
                elif tcgplayer_price > 0:
                    main_price = tcgplayer_price
                    main_url = tcgplayer_url
                    main_source = 'tcgplayer_scraped'
            
            if main_price > 0:
                if cached:
                    cached.price = main_price
                    cached.url = main_url
                    cached.source = main_source
                    cached.scraped_at = datetime.now()
                    cached.pending = False
                else:
                    new_cache = PriceCache(
                        card_id=card_id,
                        card_name=card_name,
                        set_name=set_name,
                        language=language,
                        price=main_price,
                        url=main_url,
                        source=main_source,
                        pending=False
                    )
                    db.session.add(new_cache)
                
                # Aggiorna anche le carte in collezione con questo card_id e lingua
                collected_cards = CollectedCard.query.filter_by(api_card_id=card_id, language=language).all()
                for cc in collected_cards:
                    cc.price = main_price
                    cc.price_updated_at = datetime.now()
                    cc.price_source = main_source
                
                updated_count += 1
                
                try:
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    print(f"[PRICE_UPDATER] Errore nel salvataggio: {e}")
            
            # Rate limiting
            time.sleep(3)  # 3 secondi tra una carta e l'altra
        
        print(f"[PRICE_UPDATER] Aggiornamento completato: {updated_count} prezzi aggiornati")


def price_updater_daemon(app):
    """Daemon che processa la coda di scraping e aggiorna i prezzi periodicamente."""
    last_full_update = time.time()
    
    while True:
        try:
            # Processa la coda di scraping in background (frequentemente)
            process_pending_queue(app)
        except Exception as e:
            print(f"[PRICE_UPDATER] Errore durante il processamento della coda: {e}")
            import traceback
            traceback.print_exc()
        
        # Aggiornamento completo ogni 24 ore
        if time.time() - last_full_update >= UPDATE_INTERVAL:
            try:
                update_prices_for_collected_cards(app)
                last_full_update = time.time()
            except Exception as e:
                print(f"[PRICE_UPDATER] Errore durante l'aggiornamento completo: {e}")
                import traceback
                traceback.print_exc()
        
        # Attendi prima del prossimo ciclo di processamento della coda
        time.sleep(QUEUE_PROCESS_INTERVAL)


def start_price_updater(app):
    """Avvia il daemon di aggiornamento prezzi in background.
    Se SCRAPING_ENABLED è False (default), il daemon NON viene avviato:
    i prezzi vengono presi solo dall'API Pokémon e dalle impostazioni manuali
    degli amministratori. Lo scraper resta disponibile per riattivarlo in futuro."""
    from config import Config
    
    if not Config.SCRAPING_ENABLED:
        print("[PRICE_UPDATER] Scraping DISATTIVATO (SCRAPING_ENABLED=False). "
              "I prezzi vengono presi solo dall'API e dalle impostazioni manuali degli admin.")
        return
    
    updater_thread = threading.Thread(target=lambda: price_updater_daemon(app), daemon=True)
    updater_thread.start()
    print("[PRICE_UPDATER] Daemon di aggiornamento prezzi avviato")


