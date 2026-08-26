import os
import re
import time

from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_login import LoginManager, login_required, current_user
import requests

from models import db, User, Card, CollectedCard, PriceCache
from scraper import scrape_cardmarket_price, scrape_tcgplayer_price, scrape_ebay_price
from config import Config
from auth import auth_bp

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

# Configurazione Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Effettua il login per accedere a questa pagina.'

# Gestione personalizzata per richieste AJAX non autenticate
@login_manager.unauthorized_handler
def unauthorized():
    """Gestisce le richieste non autenticate in modo appropriato per AJAX."""
    if request.is_json or request.headers.get('Content-Type') == 'application/json':
        return jsonify({"error": "Non autenticato", "redirect": url_for('auth.login')}), 401
    return redirect(url_for('auth.login'))

# Registra il blueprint di autenticazione
app.register_blueprint(auth_bp, url_prefix='/auth')


@login_manager.user_loader
def load_user(user_id):
    """Carica l'utente dalla sessione."""
    return User.query.get(int(user_id))

POKEMON_API_BASE = "https://api.pokemontcg.io/v2"
REQUEST_TIMEOUT = 10  # secondi: evita che una richiesta lenta blocchi l'app
MAX_PAGES = 20         # sicurezza anti-loop-infinito in caso di risposte anomale

HEADERS = {'X-Api-Key': 'a72c1fed-a82f-4aa8-8974-106c8f056733'}

sets_cache = None
set_cards_cache = {}  # cache in memoria: set_id -> lista di carte già scaricate


def api_get(url, params=None, max_retries=2):
    """GET con timeout, gestione errori di connessione e retry automatico per rate limit (429)."""
    for attempt in range(max_retries + 1):
        try:
            response = requests.get(url, headers=HEADERS, params=params, timeout=REQUEST_TIMEOUT)
        except requests.exceptions.RequestException as e:
            print(f"Errore di connessione: {e}")
            return None

        if response.status_code == 200:
            return response
        
        # Retry automatico per rate limit
        if response.status_code == 429 and attempt < max_retries:
            wait_time = 1.5
            print(f"Rate limit (429) raggiunto, attendo {wait_time}s prima di riprovare (tentativo {attempt + 1}/{max_retries})...")
            time.sleep(wait_time)
            continue

        print(f"Errore API (HTTP {response.status_code}): {response.text}")
        return None
    
    return None


def get_all_sets():
    global sets_cache
    if sets_cache is not None:
        return sets_cache

    print("[API] Scaricamento lista set...")
    response = api_get(f"{POKEMON_API_BASE}/sets")
    if response is None:
        print("[API] ERRORE: Impossibile scaricare i set")
        sets_cache = None  # al prossimo giro riprova
        return []

    data = response.json()
    sets_cache = sorted(data.get('data', []), key=lambda x: x.get('releaseDate', ''), reverse=True)
    print(f"[API] Set scaricati con successo: {len(sets_cache)}")
    return sets_cache


def extract_tcgplayer_price(tcgplayer):
    """Estrae il prezzo da TCGPlayer come fallback quando Cardmarket non ha dati.
    Cerca in tutti i tipi di carte e campi prezzo disponibili."""
    if not tcgplayer or not isinstance(tcgplayer, dict):
        return 0.0, None
    
    prices = tcgplayer.get('prices', {})
    if not isinstance(prices, dict):
        return 0.0, None
    
    # Lista completa di tutti i possibili tipi di carte TCGPlayer
    # Cerca in TUTTI i tipi disponibili, non solo quelli predefiniti
    all_card_types = list(prices.keys())
    
    # Priorità: prima i tipi comuni, poi tutti gli altri
    priority_types = [
        'holofoil', 'reverseHolofoil', 'normal', 
        'unlimitedHolofoil', '1stEditionHolofoil',
        'unlimited', '1stEdition'
    ]
    
    # Combina: prima i prioritari, poi tutti gli altri
    card_types_to_check = priority_types + [t for t in all_card_types if t not in priority_types]
    
    for card_type in card_types_to_check:
        type_prices = prices.get(card_type, {})
        if not isinstance(type_prices, dict):
            continue
        
        # Cerca in TUTTI i campi prezzo disponibili
        # Prima i campi standard, poi tutti gli altri
        price_fields = ['market', 'mid', 'low', 'high', 'directLow']
        all_price_fields = list(type_prices.keys())
        fields_to_check = price_fields + [f for f in all_price_fields if f not in price_fields]
        
        for key in fields_to_check:
            value = type_prices.get(key)
            if value is not None:
                try:
                    price = float(value)
                    if price > 0:
                        return price, tcgplayer.get('url', None)
                except (ValueError, TypeError):
                    continue
    
    return 0.0, None


def get_cached_price(card_id):
    """Recupera il prezzo dalla cache se disponibile e non obsoleto."""
    cached = PriceCache.query.filter_by(card_id=card_id).first()
    if cached and not cached.is_stale(days=7):
        return cached.price, cached.url, cached.source
    return None, None, None


def cache_price(card_id, card_name, set_name, price, url, source):
    """Salva il prezzo nella cache."""
    try:
        cached = PriceCache.query.filter_by(card_id=card_id).first()
        if cached:
            # Aggiorna esistente
            cached.price = price
            cached.url = url
            cached.source = source
            cached.scraped_at = db.func.now()
        else:
            # Crea nuovo
            cached = PriceCache(
                card_id=card_id,
                card_name=card_name,
                set_name=set_name,
                price=price,
                url=url,
                source=source
            )
            db.session.add(cached)
        
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[CACHE] Errore nel salvataggio: {e}")


def extract_price_info(cardmarket, tcgplayer=None, card_id=None, card_name=None, set_name=None, enable_scraping=False):
    """Restituisce (prezzo, url) usando il primo prezzo disponibile.
    Priorità: Cardmarket API → TCGPlayer API → Cache → Scraping (se abilitato) → 0.0
    Gestisce in modo sicuro valori None, stringhe e numeri."""
    
    cardmarket_price = 0.0
    cardmarket_url = '#'
    
    # 1. Prova prima con Cardmarket API (Europa)
    if cardmarket and isinstance(cardmarket, dict):
        cardmarket_url = cardmarket.get('url', '#')
        prices = cardmarket.get('prices', {})
        if isinstance(prices, dict):
            priority_keys = ['trendPrice', 'averageSellPrice', 'avg1', 'avg7', 'avg30', 'lowPrice', 'suggestedPrice']
            all_keys = list(prices.keys())
            keys_to_check = priority_keys + [k for k in all_keys if k not in priority_keys]
            
            for key in keys_to_check:
                value = prices.get(key)
                if value is not None:
                    try:
                        price = float(value)
                        if price > 0:
                            cardmarket_price = price
                            break
                    except (ValueError, TypeError):
                        continue
    
    if cardmarket_price > 0:
        return cardmarket_price, cardmarket_url
    
    # 2. Prova con TCGPlayer API (USA)
    if tcgplayer:
        tcg_price, tcg_url = extract_tcgplayer_price(tcgplayer)
        if tcg_price > 0:
            return tcg_price, tcg_url if tcg_url else '#'
    
    # 3. Controlla la cache (se abbiamo card_id)
    if card_id:
        cached_price, cached_url, cached_source = get_cached_price(card_id)
        if cached_price and cached_price > 0:
            print(f"[CACHE] Prezzo da cache per '{card_name}': €{cached_price:.2f} ({cached_source})")
            return cached_price, cached_url if cached_url else '#'
    
    # 4. Scraping come ultimo fallback (SOLO se esplicitamente abilitato)
    if enable_scraping and card_name and set_name:
        print(f"[SCRAPER] Tentativo scraping per '{card_name}' ({set_name})...")
        
        # Prova eBay scraping (PRIORITÀ: prezzi reali di vendite recenti)
        scraped_price, scraped_url = scrape_ebay_price(card_name, set_name)
        if scraped_price > 0:
            # Salva in cache
            if card_id:
                cache_price(card_id, card_name, set_name, scraped_price, scraped_url, 'ebay_scraped')
            return scraped_price, scraped_url if scraped_url else '#'
        
        # Fallback: prova Cardmarket scraping
        scraped_price, scraped_url = scrape_cardmarket_price(card_name, set_name)
        if scraped_price > 0:
            # Salva in cache
            if card_id:
                cache_price(card_id, card_name, set_name, scraped_price, scraped_url, 'cardmarket_scraped')
            return scraped_price, scraped_url if scraped_url else '#'
        
        # Ultimo fallback: prova TCGPlayer scraping
        scraped_price, scraped_url = scrape_tcgplayer_price(card_name, set_name)
        if scraped_price > 0:
            if card_id:
                cache_price(card_id, card_name, set_name, scraped_price, scraped_url, 'tcgplayer_scraped')
            return scraped_price, scraped_url if scraped_url else '#'
    
    # 5. Nessun prezzo disponibile
    if cardmarket_url != '#':
        return 0.0, cardmarket_url
    if tcgplayer and isinstance(tcgplayer, dict):
        return 0.0, tcgplayer.get('url', '#')
    
    return 0.0, '#'


def format_card(card, enable_scraping=False):
    """Formatta i dati della carta dall'API in un dizionario semplificato.
    
    Args:
        card: Dati carta dall'API
        enable_scraping: Se True, abilita lo scraping per carte senza prezzo (LENTO!)
    """
    cardmarket = card.get('cardmarket')
    tcgplayer = card.get('tcgplayer')
    card_id = card.get('id', '')
    card_name = card.get('name', '')
    set_name = card.get('set', {}).get('id', '')
    
    # Estrai prezzo e URL (con possibile scraping)
    trend_price, price_url = extract_price_info(
        cardmarket, 
        tcgplayer,
        card_id=card_id,
        card_name=card_name,
        set_name=set_name,
        enable_scraping=enable_scraping
    )
    
    # Determina se il prezzo è disponibile o meno
    price_available = trend_price > 0
    
    return {
        'card_id': card_id,
        'nome_carta': card_name,
        'id_set': set_name,
        'immagine_url': card.get('images', {}).get('small', ''),
        'prezzo_stimato': trend_price,
        'prezzo_disponibile': price_available,
        'cardmarket_url': price_url,
        'numero': card.get('number', ''),
    }


def fetch_all_cards(query):
    """Scarica tutte le carte che corrispondono alla query, gestendo la paginazione.
    Richiede esplicitamente i dati di prezzo da Cardmarket e TCGPlayer.
    Restituisce None in caso di errore di connessione."""
    all_cards = []
    page = 1

    # Parametri per richiedere esplicitamente i prezzi
    params = {
        'q': query,
        'page': page,
        'pageSize': 250,
        'select': 'id,name,number,set,images,cardmarket,tcgplayer'
    }

    while page <= MAX_PAGES:
        params['page'] = page
        response = api_get(f"{POKEMON_API_BASE}/cards", params=params)
        if response is None:
            return None

        data = response.json()
        page_data = data.get('data', [])
        all_cards.extend(page_data)

        total_count = data.get('totalCount', len(all_cards))
        if len(all_cards) >= total_count or not page_data:
            break
        page += 1

    return all_cards


def extract_card_number(numero):
    """Estrae il numero dalla stringa del numero carta in modo sicuro.
    Gestisce formati come '1', '001', 'SV01', 'PROMO 1', ecc."""
    if not numero or not isinstance(numero, str):
        return 0
    
    match = re.search(r'\d+', numero)
    if match:
        try:
            return int(match.group())
        except ValueError:
            return 0
    return 0


def sort_by_number(cards):
    """Ordina le carte per numero estratto in modo sicuro."""
    cards.sort(key=lambda c: extract_card_number(c.get('numero', '')))
    return cards


def calculate_collection_stats(user_id=None):
    """Calcola statistiche della collezione: valore totale e valori per set.
    Se user_id è None, usa l'utente corrente.
    Restituisce (total_value, set_values_dict)."""
    try:
        if user_id is None and current_user.is_authenticated:
            user_id = current_user.id
        
        if not user_id:
            return 0.0, {}
        
        collected_cards = CollectedCard.query.filter_by(user_id=user_id).all()
        total_value = 0.0
        set_values = {}
        
        for card in collected_cards:
            price = card.price if card.price else 0.0
            total_value += price
            
            # Aggrega per set
            set_id = card.set_name
            if set_id not in set_values:
                set_values[set_id] = 0.0
            set_values[set_id] += price
        
        return round(total_value, 2), set_values
    except Exception as e:
        print(f"Errore nel calcolo delle statistiche: {e}")
        return 0.0, {}


def render_cards_page(cards=None, current_set_id=None, error=None):
    """Funzione helper per renderizzare la pagina con le carte.
    Elimina duplicazione di codice tra le varie rotte."""
    sets = get_all_sets()
    
    # Calcola statistiche solo se l'utente è autenticato
    if current_user.is_authenticated:
        total_value, set_values = calculate_collection_stats()
    else:
        total_value, set_values = 0.0, {}
    
    return render_template(
        'index.html',
        sets=sets,
        results=cards or [],
        total_value=total_value,
        set_values=set_values,
        current_set_id=current_set_id,
        error=error,
        user=current_user
    )


@app.route('/')
def index():
    return render_cards_page()


@app.route('/search', methods=['GET'])
def search():
    query = request.args.get('query', '').strip()
    enable_scraping = request.args.get('scrape', '').lower() == 'true'
    
    if not query:
        return render_cards_page()

    raw_cards = fetch_all_cards(f"name:{query}")
    if raw_cards is None:
        return render_cards_page(error='Errore di connessione al database Pokémon')

    # ATTENZIONE: enable_scraping=True è LENTO! Usa solo se necessario
    cards = sort_by_number([format_card(c, enable_scraping=enable_scraping) for c in raw_cards])
    return render_cards_page(cards=cards)


@app.route('/set/<set_id>', methods=['GET'])
def get_set_cards(set_id):
    enable_scraping = request.args.get('scrape', '').lower() == 'true'
    
    # Usa la cache se disponibile E non è richiesto scraping
    if set_id in set_cards_cache and not enable_scraping:
        return render_cards_page(cards=set_cards_cache[set_id], current_set_id=set_id)

    raw_cards = fetch_all_cards(f"set.id:{set_id}")
    if raw_cards is None:
        return render_cards_page(current_set_id=set_id, error='Errore di connessione al database Pokémon')

    # ATTENZIONE: enable_scraping=True è MOLTO LENTO per set interi!
    cards = sort_by_number([format_card(c, enable_scraping=enable_scraping) for c in raw_cards])
    
    # Salva in cache solo se non è stato fatto scraping
    if not enable_scraping:
        set_cards_cache[set_id] = cards
    
    return render_cards_page(cards=cards, current_set_id=set_id)


@app.route('/api/collection/add', methods=['POST'])
@login_required
def add_to_collection():
    data = request.json
    print(f"[API] Richiesta aggiunta carta - User: {current_user.email}, Data: {data}")
    
    # Validazione input
    if not data or 'card_id' not in data:
        print("[API] ERRORE: Dati mancanti nella richiesta")
        return jsonify({"error": "Dati mancanti"}), 400
    
    card_id = data.get('card_id', '').strip()
    if not card_id:
        print("[API] ERRORE: ID carta vuoto")
        return jsonify({"error": "ID carta non valido"}), 400
    
    # Verifica se già presente per questo utente
    already_owned = CollectedCard.query.filter_by(
        user_id=current_user.id,
        api_card_id=card_id
    ).first()
    
    if already_owned:
        return jsonify({"message": "Carta già presente in collezione"}), 200

    # Validazione e conversione prezzo (accetta anche prezzi inseriti manualmente)
    try:
        price = float(data.get('price', 0))
        # Accetta prezzi negativi come 0
        if price < 0:
            price = 0.0
    except (ValueError, TypeError):
        price = 0.0

    card = CollectedCard(
        user_id=current_user.id,
        api_card_id=card_id,
        name=data.get('name', 'Sconosciuta')[:100],  # Limita lunghezza
        set_name=data.get('set_id', 'Sconosciuto')[:100],
        price=price
    )
    
    try:
        db.session.add(card)
        db.session.commit()
        print(f"[API] Carta aggiunta con successo: {card_id} per user {current_user.id}")
        return jsonify({"message": "Carta aggiunta con successo", "price": price}), 200
    except Exception as e:
        db.session.rollback()
        print(f"[API] ERRORE nell'aggiunta della carta: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Errore nel salvataggio: {str(e)}"}), 500


@app.route('/api/collection/update_price', methods=['POST'])
@login_required
def update_card_price():
    """Aggiorna il prezzo di una carta nella collezione."""
    data = request.json
    
    # Validazione input
    if not data or 'card_id' not in data or 'price' not in data:
        return jsonify({"error": "Dati mancanti"}), 400
    
    card_id = data.get('card_id', '').strip()
    if not card_id:
        return jsonify({"error": "ID carta non valido"}), 400
    
    # Validazione prezzo
    try:
        new_price = float(data.get('price', 0))
        if new_price < 0:
            return jsonify({"error": "Il prezzo non può essere negativo"}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "Prezzo non valido"}), 400
    
    card = CollectedCard.query.filter_by(
        user_id=current_user.id,
        api_card_id=card_id
    ).first()
    
    if not card:
        return jsonify({"error": "Carta non trovata in collezione"}), 404
    
    try:
        card.price = new_price
        db.session.commit()
        return jsonify({"message": "Prezzo aggiornato con successo", "new_price": new_price}), 200
    except Exception as e:
        db.session.rollback()
        print(f"Errore nell'aggiornamento del prezzo: {e}")
        return jsonify({"error": "Errore nell'aggiornamento"}), 500


@app.route('/api/collection/remove', methods=['POST'])
@login_required
def remove_from_collection():
    data = request.json
    
    # Validazione input
    if not data or 'card_id' not in data:
        return jsonify({"error": "Dati mancanti"}), 400
    
    card_id = data.get('card_id', '').strip()
    if not card_id:
        return jsonify({"error": "ID carta non valido"}), 400
    
    card = CollectedCard.query.filter_by(
        user_id=current_user.id,
        api_card_id=card_id
    ).first()
    
    if not card:
        return jsonify({"message": "Carta non trovata"}), 404
    
    try:
        db.session.delete(card)
        db.session.commit()
        return jsonify({"message": "Carta rimossa con successo"}), 200
    except Exception as e:
        db.session.rollback()
        print(f"Errore nella rimozione della carta: {e}")
        return jsonify({"error": "Errore nella rimozione"}), 500


@app.route('/api/collection', methods=['GET'])
@login_required
def get_collection():
    """Restituisce tutte le carte nella collezione dell'utente corrente."""
    try:
        cards = CollectedCard.query.filter_by(user_id=current_user.id).all()
        return jsonify([card.to_dict() for card in cards]), 200
    except Exception as e:
        print(f"Errore nel recupero della collezione: {e}")
        return jsonify({"error": "Errore nel recupero della collezione"}), 500


@app.route('/api/collection/stats', methods=['GET'])
@login_required
def get_collection_stats():
    """Restituisce statistiche della collezione dell'utente corrente."""
    try:
        total_value, set_values = calculate_collection_stats(current_user.id)
        return jsonify({
            'total_value': total_value,
            'set_values': set_values
        }), 200
    except Exception as e:
        print(f"Errore nel recupero delle statistiche: {e}")
        return jsonify({"error": "Errore nel recupero delle statistiche"}), 500


def preload_popular_sets():
    """Pre-carica in cache i set più recenti per velocizzare il primo accesso."""
    with app.app_context():
        print("[CACHE] Pre-caricamento set popolari...")
        sets = get_all_sets()
        
        # Pre-carica i primi 5 set più recenti
        for i, set_data in enumerate(sets[:5]):
            set_id = set_data.get('id')
            if set_id and set_id not in set_cards_cache:
                print(f"[CACHE] Pre-caricamento set {i+1}/5: {set_data.get('name')}")
                raw_cards = fetch_all_cards(f"set.id:{set_id}")
                if raw_cards:
                    cards = sort_by_number([format_card(c) for c in raw_cards])
                    set_cards_cache[set_id] = cards
        
        print("[CACHE] Pre-caricamento completato!")


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        
        # Pre-carica i set popolari in un thread separato per non bloccare l'avvio
        import threading
        preload_thread = threading.Thread(target=preload_popular_sets, daemon=True)
        preload_thread.start()
    
    app.run(debug=True, threaded=True)
