from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Card(db.Model):
    """Modello per le carte Pokémon (attualmente non utilizzato, preparato per future funzionalità)."""
    __tablename__ = 'cards'
    
    card_id = db.Column(db.String(50), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    set_id = db.Column(db.String(50), nullable=False)
    price = db.Column(db.Float, nullable=False, default=0.0)
    
    def __repr__(self):
        return f'<Card {self.card_id}: {self.name}>'


class CollectedCard(db.Model):
    """Modello per le carte possedute dall'utente."""
    __tablename__ = 'collected_cards'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    api_card_id = db.Column(db.String(50), nullable=False, unique=True, index=True)
    name = db.Column(db.String(100), nullable=False)
    set_name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False, default=0.0)
    
    def __repr__(self):
        return f'<CollectedCard {self.api_card_id}: {self.name} - €{self.price}>'
    
    def to_dict(self):
        """Converte il modello in dizionario per JSON."""
        return {
            'api_card_id': self.api_card_id,
            'name': self.name,
            'set_name': self.set_name,
            'price': self.price
        }
