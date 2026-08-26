"""
Sistema di aggiornamento automatico dei prezzi ogni 2 ore.
Esegue scraping in background per mantenere i prezzi aggiornati.
"""

import time
import threading
from datetime import datetime, timedelta

UPDATE_INTERVAL = 2 * 60 * 60  # 2 ore in secondi


def update_prices_for_collected_cards(app):
    """Aggiorna i prezzi di tutte le carte possedute dagli utenti."""
    from models import PriceCache, CollectedCard, db
    from scraper import scrape_ebay_price, scrape_cardmarket_price
    
    with app.app_context():
        print(f"[PRICE_UPDATER] Inizio aggiornamento prezzi - {datetime.now()}")
        
        # Ottieni tutte le carte uniche nella collezione
        unique_cards = db.session.query(
            CollectedCard.api_card_id,
            CollectedCard.name,
            CollectedCard.set_name
        ).distinct().all()
        
        print(f"[PRICE_UPDATER] Trovate {len(unique_cards)} carte uniche da aggiornare")
        
        updated_count = 0
        for card_id, card_name, set_name in unique_cards:
            # Controlla se il prezzo in cache è obsoleto
            cached = PriceCache.query.filter_by(card_id=card_id).first()
            
            if cached and not cached.is_stale(hours=2):
                continue  # Prezzo ancora valido
            
            # Aggiorna il prezzo
            print(f"[PRICE_UPDATER] Aggiornamento prezzo per: {card_name}")
            
            # Prova eBay prima (più affidabile)
            price, url = scrape_ebay_price(card_name, set_name)
            source = 'ebay_scraped'
            
            # Fallback su Cardmarket
            if price == 0.0:
                price, url = scrape_cardmarket_price(card_name, set_name)
                source = 'cardmarket_scraped'
            
            if price > 0:
                if cached:
                    cached.price = price
                    cached.url = url
                    cached.source = source
                    cached.scraped_at = datetime.now()
                else:
                    new_cache = PriceCache(
                        card_id=card_id,
                        card_name=card_name,
                        set_name=set_name,
                        price=price,
                        url=url,
                        source=source
                    )
                    db.session.add(new_cache)
                
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
    """Daemon che esegue l'aggiornamento prezzi ogni 2 ore."""
    while True:
        try:
            update_prices_for_collected_cards(app)
        except Exception as e:
            print(f"[PRICE_UPDATER] Errore durante l'aggiornamento: {e}")
            import traceback
            traceback.print_exc()
        
        print(f"[PRICE_UPDATER] Prossimo aggiornamento tra 2 ore")
        time.sleep(UPDATE_INTERVAL)


def start_price_updater(app):
    """Avvia il daemon di aggiornamento prezzi in background."""
    updater_thread = threading.Thread(target=lambda: price_updater_daemon(app), daemon=True)
    updater_thread.start()
    print("[PRICE_UPDATER] Daemon di aggiornamento prezzi avviato")
