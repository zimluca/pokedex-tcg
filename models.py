from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Card(db.Model):
    __tablename__ = 'cards'
    card_id = db.Column(db.String(50), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    set_id = db.Column(db.String(50), nullable=False)
    price = db.Column(db.Float, nullable=False)
