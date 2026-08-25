from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Collection(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome_carta = db.Column(db.String(100), nullable=False)
    id_set = db.Column(db.String(50), nullable=False)
    immagine_url = db.Column(db.String(200), nullable=False)
    prezzo_stimato = db.Column(db.Float, nullable=False)
