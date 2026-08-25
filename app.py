from flask import Flask, render_template, request, jsonify
import requests
from models import db

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///pokemon.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

@app.route('/')
def index():
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get("https://api.pokemontcg.io/v2/sets", headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        sets = sorted(data.get('data', []), key=lambda x: x.get('releaseDate', ''), reverse=True)
    else:
        print(f"Errore di connessione: {response.status_code}")
        print(response.text)
        sets = []

    return render_template('index.html', sets=sets, results=[], total_value=0.00)

@app.route('/search', methods=['GET'])
def search():
    query = request.args.get('query', '')
    if not query:
        return render_template('index.html', sets=[], results=[])

    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(f"https://api.pokemontcg.io/v2/cards?q=name:{query}", headers=headers)
    
    if response.status_code == 200:
        data = response.json()
    else:
        print(f"Errore di connessione: {response.status_code}")
        print(response.text)
        return render_template('index.html', sets=[], results=[], error='Errore di connessione al database Pokémon')
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

    return render_template('index.html', sets=[], results=cards)

@app.route('/set/<set_id>', methods=['GET'])
def get_set_cards(set_id):
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(f"https://api.pokemontcg.io/v2/cards?q=set.id:{set_id}&orderBy=number", headers=headers)
    
    if response.status_code == 200:
        data = response.json()
    else:
        print(f"Errore di connessione: {response.status_code}")
        print(response.text)
        return render_template('index.html', sets=[], results=[], error='Errore di connessione al database Pokémon')
    cards = []

    for card in data.get('data', []):
        name = card.get('name', '')
        id_set = card.get('set', {}).get('id', '')
        image_url = card.get('images', {}).get('small', '')
        market_price = card.get('tcgplayer', {}).get('prices', {}).get('market', {}).get('price', 'N/A')

        cards.append({
            'nome_carta': name,
            'id_set': id_set,
            'immagine_url': image_url,
            'prezzo_stimato': market_price
        })

    return render_template('index.html', sets=[], results=cards)

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
