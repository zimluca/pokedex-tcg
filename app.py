import os
import re
import time

from flask import Flask, render_template, request, jsonify
import requests

from models import db, Card, CollectedCard

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///collezione.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

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

    response = api_get(f"{POKEMON_API_BASE}/sets")
    if response is None:
        sets_cache = None  # al prossimo giro riprova
        return []

    data = response.json()
    sets_cache = sorted(data.get('data', []), key=lambda x: x.get('releaseDate', ''), reverse=True)
    print(f"Set scaricati: {len(sets_cache)}")
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


def extract_price_info(cardmarket, tcgplayer=None):
    """Restituisce (prezzo, url) usando il primo prezzo disponibile.
    Priorità: Cardmarket (EUR) con prezzo valido -> TCGPlayer (USD) -> Cardmarket URL -> 0.0
    Gestisce in modo sicuro valori None, stringhe e numeri."""
    
    cardmarket_price = 0.0
    cardmarket_url = '#'
    
    # Prova prima con Cardmarket (Europa)
    if cardmarket and isinstance(cardmarket, dict):
        cardmarket_url = cardmarket.get('url', '#')
        prices = cardmarket.get('prices', {})
        if isinstance(prices, dict):
            # Cerca in TUTTI i campi prezzo disponibili di Cardmarket
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
    
    # Se Cardmarket ha un prezzo valido, usalo
    if cardmarket_price > 0:
        return cardmarket_price, cardmarket_url
    
    # Altrimenti prova con TCGPlayer (USA)
    if tcgplayer:
        tcg_price, tcg_url = extract_tcgplayer_price(tcgplayer)
        if tcg_price > 0:
            return tcg_price, tcg_url if tcg_url else '#'
    
    # Nessun prezzo disponibile - restituisci URL Cardmarket se disponibile, altrimenti TCGPlayer
    if cardmarket_url != '#':
        return 0.0, cardmarket_url
    if tcgplayer and isinstance(tcgplayer, dict):
        return 0.0, tcgplayer.get('url', '#')
    
    return 0.0, '#'


def format_card(card):
    """Formatta i dati della carta dall'API in un dizionario semplificato."""
    cardmarket = card.get('cardmarket')
    tcgplayer = card.get('tcgplayer')
    
    # Estrai prezzo e URL
    trend_price, price_url = extract_price_info(cardmarket, tcgplayer)
    
    # Debug: stampa dettagli sui prezzi per capire il problema
    if trend_price == 0:
        card_name = card.get('name', 'Unknown')
        print(f"[DEBUG] Prezzo 0 per '{card_name}'")
        if cardmarket:
            cm_prices = cardmarket.get('prices', {})
            print(f"   Cardmarket presente: {bool(cardmarket)}, Prezzi: {cm_prices if cm_prices else 'Nessuno'}")
        else:
            print(f"   Cardmarket: Non presente")
        if tcgplayer:
            tcg_prices = tcgplayer.get('prices', {})
            print(f"   TCGPlayer presente: {bool(tcgplayer)}, Prezzi: {tcg_prices if tcg_prices else 'Nessuno'}")
        else:
            print(f"   TCGPlayer: Non presente")
    elif trend_price > 0:
        # Log positivo per confermare che i prezzi vengono estratti
        source = "Cardmarket" if cardmarket and cardmarket.get('prices') else "TCGPlayer"
        print(f"[INFO] Prezzo trovato per '{card.get('name', 'Unknown')}': €{trend_price:.2f} (fonte: {source})")
    
    return {
        'card_id': card.get('id', ''),
        'nome_carta': card.get('name', ''),
        'id_set': card.get('set', {}).get('id', ''),
        'immagine_url': card.get('images', {}).get('small', ''),
        'prezzo_stimato': trend_price,
        'cardmarket_url': price_url,
        'numero': card.get('number', ''),
    }


def fetch_all_cards(query):
    """Scarica tutte le carte che corrispondono alla query, gestendo la paginazione.
    Restituisce None in caso di errore di connessione."""
    all_cards = []
    page = 1

    while page <= MAX_PAGES:
        response = api_get(f"{POKEMON_API_BASE}/cards", params={'q': query, 'page': page, 'pageSize': 250})
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


def calculate_collection_stats():
    """Calcola statistiche della collezione: valore totale e valori per set.
    Restituisce (total_value, set_values_dict)."""
    try:
        collected_cards = CollectedCard.query.all()
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
    total_value, set_values = calculate_collection_stats()
    
    return render_template(
        'index.html',
        sets=sets,
        results=cards or [],
        total_value=total_value,
        set_values=set_values,
        current_set_id=current_set_id,
        error=error
    )


@app.route('/')
def index():
    return render_cards_page()


@app.route('/search', methods=['GET'])
def search():
    query = request.args.get('query', '').strip()
    
    if not query:
        return render_cards_page()

    raw_cards = fetch_all_cards(f"name:{query}")
    if raw_cards is None:
        return render_cards_page(error='Errore di connessione al database Pokémon')

    cards = sort_by_number([format_card(c) for c in raw_cards])
    return render_cards_page(cards=cards)


@app.route('/set/<set_id>', methods=['GET'])
def get_set_cards(set_id):
    # Usa la cache se disponibile
    if set_id in set_cards_cache:
        return render_cards_page(cards=set_cards_cache[set_id], current_set_id=set_id)

    raw_cards = fetch_all_cards(f"set.id:{set_id}")
    if raw_cards is None:
        return render_cards_page(current_set_id=set_id, error='Errore di connessione al database Pokémon')

    cards = sort_by_number([format_card(c) for c in raw_cards])
    set_cards_cache[set_id] = cards
    return render_cards_page(cards=cards, current_set_id=set_id)


@app.route('/api/collection/add', methods=['POST'])
def add_to_collection():
    data = request.json
    
    # Validazione input
    if not data or 'card_id' not in data:
        return jsonify({"error": "Dati mancanti"}), 400
    
    card_id = data.get('card_id', '').strip()
    if not card_id:
        return jsonify({"error": "ID carta non valido"}), 400
    
    # Verifica se già presente
    already_owned = CollectedCard.query.filter_by(api_card_id=card_id).first()
    if already_owned:
        return jsonify({"message": "Carta già presente in collezione"}), 200

    # Validazione e conversione prezzo
    try:
        price = float(data.get('price', 0))
    except (ValueError, TypeError):
        price = 0.0

    card = CollectedCard(
        api_card_id=card_id,
        name=data.get('name', 'Sconosciuta')[:100],  # Limita lunghezza
        set_name=data.get('set_id', 'Sconosciuto')[:100],
        price=price
    )
    
    try:
        db.session.add(card)
        db.session.commit()
        return jsonify({"message": "Carta aggiunta con successo"}), 200
    except Exception as e:
        db.session.rollback()
        print(f"Errore nell'aggiunta della carta: {e}")
        return jsonify({"error": "Errore nel salvataggio"}), 500


@app.route('/api/collection/remove', methods=['POST'])
def remove_from_collection():
    data = request.json
    
    # Validazione input
    if not data or 'card_id' not in data:
        return jsonify({"error": "Dati mancanti"}), 400
    
    card_id = data.get('card_id', '').strip()
    if not card_id:
        return jsonify({"error": "ID carta non valido"}), 400
    
    card = CollectedCard.query.filter_by(api_card_id=card_id).first()
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
def get_collection():
    """Restituisce tutte le carte nella collezione dell'utente."""
    try:
        cards = CollectedCard.query.all()
        return jsonify([card.to_dict() for card in cards]), 200
    except Exception as e:
        print(f"Errore nel recupero della collezione: {e}")
        return jsonify({"error": "Errore nel recupero della collezione"}), 500


@app.route('/api/collection/stats', methods=['GET'])
def get_collection_stats():
    """Restituisce statistiche della collezione: valore totale e valori per set."""
    try:
        total_value, set_values = calculate_collection_stats()
        return jsonify({
            'total_value': total_value,
            'set_values': set_values
        }), 200
    except Exception as e:
        print(f"Errore nel recupero delle statistiche: {e}")
        return jsonify({"error": "Errore nel recupero delle statistiche"}), 500


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, threaded=True)
