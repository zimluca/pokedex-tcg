import os
import time
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
MAX_RETRIES = 3        # tentativi in caso di rate limit (HTTP 429)

HEADERS = {'User-Agent': 'Mozilla/5.0'}
API_KEY = os.environ.get('POKEMONTCG_API_KEY')
if API_KEY:
    HEADERS['X-Api-Key'] = API_KEY

sets_cache = None
set_cards_cache = {}  # cache in memoria: set_id -> lista di carte già scaricate


def api_get(url, params=None):
    """GET con timeout, gestione errori di connessione e retry sul rate limit (429)."""
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, headers=HEADERS, params=params, timeout=REQUEST_TIMEOUT)
        except requests.exceptions.RequestException as e:
            print(f"Errore di connessione: {e}")
            return None

        if response.status_code == 200:
            return response

        if response.status_code == 429:
            wait = 2 ** attempt
            print(f"Rate limit raggiunto, riprovo tra {wait}s...")
            time.sleep(wait)
            continue

        print(f"Errore di connessione: {response.status_code}")
        print(response.text)
        return None

    print("Troppi tentativi falliti per rate limit")
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
    """Restituisce (prezzo, url_cardmarket) usando il primo prezzo disponibile tra quelli noti."""
    if not cardmarket:
        return 0.0, '#'
    prices = cardmarket.get('prices', {})
    for key in ('trendPrice', 'averageSellPrice', 'lowPrice', '1DayAverage'):
        value = prices.get(key)
        if value is not None:
            return float(value), cardmarket.get('url', '#')
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


def sort_by_number(cards):
    cards.sort(key=lambda c: int(re.search(r'\d+', c['numero']).group()) if re.search(r'\d+', c['numero']) else 0)
    return cards


@app.route('/')
def index():
    sets = get_all_sets()
    total_value = sum(card.price for card in CollectedCard.query.all())
    return render_template('index.html', sets=sets, results=[], total_value=total_value, current_set_id=None)


@app.route('/search', methods=['GET'])
def search():
    query = request.args.get('query', '')
    sets = get_all_sets()
    if not query:
        return render_template('index.html', sets=sets, results=[], current_set_id=None)

    raw_cards = fetch_all_cards(f"name:{query}")
    if raw_cards is None:
        return render_template('index.html', sets=sets, results=[], current_set_id=None,
                                error='Errore di connessione al database Pokémon')

    cards = sort_by_number([format_card(c) for c in raw_cards])
    return render_template('index.html', sets=sets, results=cards, current_set_id=None)


@app.route('/set/<set_id>', methods=['GET'])
def get_set_cards(set_id):
    sets = get_all_sets()

    if set_id in set_cards_cache:
        return render_template('index.html', sets=sets, results=set_cards_cache[set_id], current_set_id=set_id)

    raw_cards = fetch_all_cards(f"set.id:{set_id}")
    if raw_cards is None:
        return render_template('index.html', sets=sets, results=[], current_set_id=set_id,
                                error='Errore di connessione al database Pokémon')

    cards = sort_by_number([format_card(c) for c in raw_cards])
    set_cards_cache[set_id] = cards
    return render_template('index.html', sets=sets, results=cards, current_set_id=set_id)


@app.route('/api/collection/add', methods=['POST'])
def add_to_collection():
    data = request.json
    already_owned = CollectedCard.query.filter_by(api_card_id=data['card_id']).first()
    if already_owned:
        return jsonify({"message": "Carta già presente in collezione"}), 200

    card = CollectedCard(
        api_card_id=data['card_id'],
        name=data['name'],
        set_name=data['set_id'],
        price=data['price']
    )
    db.session.add(card)
    db.session.commit()
    return jsonify({"message": "Carta aggiunta con successo"}), 200


@app.route('/api/collection/remove', methods=['POST'])
def remove_from_collection():
    data = request.json
    card = CollectedCard.query.filter_by(api_card_id=data['card_id']).first()
    if card:
        db.session.delete(card)
        db.session.commit()
        return jsonify({"message": "Carta rimossa con successo"}), 200
    else:
        return jsonify({"message": "Carta non trovata"}), 404


@app.route('/api/collection', methods=['GET'])
def get_collection():
    cards = CollectedCard.query.all()
    return jsonify([{'api_card_id': card.api_card_id, 'name': card.name, 'set_name': card.set_name, 'price': card.price} for card in cards]), 200


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, threaded=True)