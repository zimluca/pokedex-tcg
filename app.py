from flask import Flask, render_template, request, jsonify
import requests
from models import db, Card

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///collezione.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

sets_cache = None

def get_all_sets():
    global sets_cache
    if sets_cache is not None:
        return sets_cache

    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get("https://api.pokemontcg.io/v2/sets", headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        sets_cache = sorted(data.get('data', []), key=lambda x: x.get('releaseDate', ''), reverse=True)
        print(f"Set scaricati: {len(sets_cache)}")
    else:
        print(f"Errore di connessione: {response.status_code}")
        print(response.text)
        sets_cache = []

    return sets_cache

@app.route('/')
def index():
    sets = get_all_sets()
    return render_template('index.html', sets=sets, results=[], total_value=0.00)

@app.route('/search', methods=['GET'])
def search():
    query = request.args.get('query', '')
    sets = get_all_sets()
    if not query:
        return render_template('index.html', sets=sets, results=[])

    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(f"https://api.pokemontcg.io/v2/cards?q=name:{query}", headers=headers)
    
    if response.status_code == 200:
        data = response.json()
    else:
        print(f"Errore di connessione: {response.status_code}")
        print(response.text)
        return render_template('index.html', sets=sets, results=[], error='Errore di connessione al database Pokémon')
    cards = []

    for card in data.get('data', []):
        name = card.get('name', '')
        id_set = card.get('set', {}).get('id', '')
        image_url = card.get('images', {}).get('small', '')
        cardmarket = card.get('cardmarket', {})
        if cardmarket:
            trend_price = cardmarket.get('prices', {}).get('trendPrice', cardmarket.get('prices', {}).get('averageSellPrice', 'N/A'))
            cardmarket_url = cardmarket.get('url', '#')
        else:
            trend_price = 'N/A'
            cardmarket_url = '#'

        cards.append({
            'nome_carta': name,
            'id_set': id_set,
            'immagine_url': image_url,
            'prezzo_stimato': trend_price,
            'cardmarket_url': cardmarket_url
        })

    return render_template('index.html', sets=sets, results=cards)

@app.route('/set/<set_id>', methods=['GET'])
def get_set_cards(set_id):
    sets = get_all_sets()
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(f"https://api.pokemontcg.io/v2/cards?q=set.id:{set_id}&orderBy=number", headers=headers)
    
    if response.status_code == 200:
        data = response.json()
    else:
        print(f"Errore di connessione: {response.status_code}")
        print(response.text)
        return render_template('index.html', sets=sets, results=[], error='Errore di connessione al database Pokémon')
    cards = []

    for card in data.get('data', []):
        name = card.get('name', '')
        id_set = card.get('set', {}).get('id', '')
        image_url = card.get('images', {}).get('small', '')
        cardmarket = card.get('cardmarket', {})
        if cardmarket:
            trend_price = cardmarket.get('prices', {}).get('trendPrice', cardmarket.get('prices', {}).get('averageSellPrice', 'N/A'))
            cardmarket_url = cardmarket.get('url', '#')
        else:
            trend_price = 'N/A'
            cardmarket_url = '#'

        cards.append({
            'nome_carta': name,
            'id_set': id_set,
            'immagine_url': image_url,
            'prezzo_stimato': trend_price,
            'cardmarket_url': cardmarket_url
        })

    return render_template('index.html', sets=sets, results=cards)

@app.route('/api/collection/add', methods=['POST'])
def add_to_collection():
    data = request.json
    card = Card(
        card_id=data['card_id'],
        name=data['name'],
        set_id=data['set_id'],
        price=data['price']
    )
    db.session.add(card)
    db.session.commit()
    return jsonify({"message": "Carta aggiunta con successo"}), 200

@app.route('/api/collection/remove', methods=['POST'])
def remove_from_collection():
    data = request.json
    card = Card.query.filter_by(card_id=data['card_id']).first()
    if card:
        db.session.delete(card)
        db.session.commit()
        return jsonify({"message": "Carta rimossa con successo"}), 200
    else:
        return jsonify({"message": "Carta non trovata"}), 404

@app.route('/api/collection', methods=['GET'])
def get_collection():
    cards = Card.query.all()
    return jsonify([{'card_id': card.card_id, 'name': card.name, 'set_id': card.set_id, 'price': card.price} for card in cards]), 200

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
