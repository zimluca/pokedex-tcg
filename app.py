import os
import re

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


def api_get(url, params=None):
    """GET con timeout e gestione errori di connessione."""
    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as e:
        print(f"Errore di connessione: {e}")
        return None

    if response.status_code == 200:
        return response

    print(f"Errore API (HTTP {response.status_code}): {response.text}")
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


def extract_price_info(cardmarket):
    """Restituisce (prezzo, url_cardmarket) usando il primo prezzo disponibile tra quelli noti.
    Gestisce in modo sicuro valori None, stringhe e numeri."""
    if not cardmarket or not isinstance(cardmarket, dict):
        return 0.0, '#'
    
    prices = cardmarket.get('prices', {})
    if not isinstance(prices, dict):
        return 0.0, cardmarket.get('url', '#')
    
    for key in ('trendPrice', 'averageSellPrice', 'lowPrice', '1DayAverage'):
        value = prices.get(key)
        if value is not None:
            try:
                return float(value), cardmarket.get('url', '#')
            except (ValueError, TypeError):
                continue
    
    return 0.0, cardmarket.get('url', '#')


def format_card(card):
    trend_price, cardmarket_url = extract_price_info(card.get('cardmarket', {}))
    return {
        'card_id': card.get('id', ''),
        'nome_carta': card.get('name', ''),
        'id_set': card.get('set', {}).get('id', ''),
        'immagine_url': card.get('images', {}).get('small', ''),
        'prezzo_stimato': trend_price,
        'cardmarket_url': cardmarket_url,
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


def render_cards_page(cards=None, current_set_id=None, error=None):
    """Funzione helper per renderizzare la pagina con le carte.
    Elimina duplicazione di codice tra le varie rotte."""
    sets = get_all_sets()
    
    # Calcola il valore totale della collezione in modo sicuro
    try:
        total_value = sum(card.price for card in CollectedCard.query.all() if card.price)
    except Exception as e:
        print(f"Errore nel calcolo del valore totale: {e}")
        total_value = 0.0
    
    return render_template(
        'index.html',
        sets=sets,
        results=cards or [],
        total_value=round(total_value, 2),
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


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, threaded=True)
