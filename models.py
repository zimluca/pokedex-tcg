from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()


class User(UserMixin, db.Model):
    """Modello per gli utenti autenticati."""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    google_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
    email = db.Column(db.String(100), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100))
    picture = db.Column(db.String(500))
    # True se l'utente è amministratore (può modificare i prezzi)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Relazione con le carte possedute
    collected_cards = db.relationship('CollectedCard', backref='owner', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<User {self.email}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'name': self.name,
            'picture': self.picture,
            'is_admin': self.is_admin
        }


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
    """Modello per le carte possedute dall'utente.
    Ogni carta è associata a un utente specifico e a una lingua."""
    __tablename__ = 'collected_cards'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    api_card_id = db.Column(db.String(50), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    set_name = db.Column(db.String(100), nullable=False)
    # Lingua della carta: 'it' o 'en' (default 'en')
    language = db.Column(db.String(5), nullable=False, default='en')
    price = db.Column(db.Float, nullable=False, default=0.0)
    added_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    # Timestamp dell'ultimo aggiornamento del prezzo (None se mai aggiornato)
    price_updated_at = db.Column(db.DateTime, nullable=True)
    # Sorgente del prezzo: 'cardmarket', 'tcgplayer', 'ebay_scraped', 'cardmarket_scraped', 'tcgplayer_scraped', 'manual'
    price_source = db.Column(db.String(30), nullable=True)
    
    # Constraint: un utente può avere la stessa carta nella stessa lingua una sola volta
    __table_args__ = (
        db.UniqueConstraint('user_id', 'api_card_id', 'language', name='unique_user_card_lang'),
    )
    
    def __repr__(self):
        return f'<CollectedCard user={self.user_id} {self.api_card_id} ({self.language}): {self.name} - €{self.price}>'
    
    def is_price_stale(self, hours=24):
        """Verifica se il prezzo della carta è più vecchio di `hours` ore (default: 24).
        Se price_updated_at è None, il prezzo è considerato obsoleto."""
        from datetime import datetime, timedelta
        if self.price_updated_at is None:
            return True
        return datetime.now() - self.price_updated_at > timedelta(hours=hours)
    
    def to_dict(self):
        """Converte il modello in dizionario per JSON."""
        return {
            'api_card_id': self.api_card_id,
            'name': self.name,
            'set_name': self.set_name,
            'language': self.language,
            'price': self.price,
            'added_at': self.added_at.isoformat() if self.added_at else None,
            'price_updated_at': self.price_updated_at.isoformat() if self.price_updated_at else None,
            'price_source': self.price_source
        }
class PriceCache(db.Model):
    """Cache persistente per i prezzi ottenuti tramite scraping.
    Evita di fare scraping ripetuto per la stessa carta."""
    __tablename__ = 'price_cache'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    card_id = db.Column(db.String(50), nullable=False, index=True)
    card_name = db.Column(db.String(100), nullable=False)
    set_name = db.Column(db.String(100), nullable=False)
    # Lingua della carta: 'it' o 'en' (default 'en')
    language = db.Column(db.String(5), nullable=False, default='en')
    price = db.Column(db.Float, nullable=False, default=0.0)
    source = db.Column(db.String(20), nullable=False)  # 'cardmarket', 'tcgplayer', 'ebay', 'manual'
    url = db.Column(db.String(500))
    scraped_at = db.Column(db.DateTime, nullable=False, default=db.func.now())
    # True se la carta è in coda per lo scraping in background (prezzo non ancora disponibile)
    pending = db.Column(db.Boolean, nullable=False, default=False)
    
    # Constraint: una carta in una lingua specifica ha una sola voce in cache
    __table_args__ = (
        db.UniqueConstraint('card_id', 'language', name='unique_card_lang'),
    )
    
    def __repr__(self):
        return f'<PriceCache {self.card_name} ({self.language}): €{self.price} from {self.source}>'
    
    def is_stale(self, hours=2):
        """Verifica se il prezzo in cache è vecchio (default: 2 ore)."""
        from datetime import datetime, timedelta
        return datetime.now() - self.scraped_at > timedelta(hours=hours)




class UserPreferences(db.Model):

    """Preferenze utente (lingua, ecc.)."""
    __tablename__ = 'user_preferences'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True, index=True)
    preferred_language = db.Column(db.String(10), default='en')  # 'en', 'it', 'fr', 'de', 'es', 'ja'
    
    user = db.relationship('User', backref=db.backref('preferences', uselist=False))
    
    def __repr__(self):
        return f'<UserPreferences user={self.user_id} lang={self.preferred_language}>'
