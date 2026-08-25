from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Card(db.Model):
    __tablename__ = 'cards'
    card_id = db.Column(db.String(50), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    set_id = db.Column(db.String(50), nullable=False)
    price = db.Column(db.Float, nullable=False)

class CollectedCard(db.Model):
    __tablename__ = 'collected_cards'
    id = db.Column(db.Integer, primary_key=True)
    api_card_id = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    set_name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
