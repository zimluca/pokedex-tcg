from flask import Flask, render_template, request, jsonify
import requests
from models import db

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///pokemon.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search', methods=['GET'])
def search():
    query = request.args.get('query', '')
    if not query:
        return render_template('index.html', results=[])

    response = requests.get(f"https://api.pokemontcg.io/v2/cards?q=name:{query}")
    data = response.json()
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

    return render_template('index.html', results=cards)

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
