"""
Script per inizializzare il database con le nuove tabelle multi-utente.
Esegui questo script dopo aver configurato OAuth per creare le tabelle necessarie.
"""

from app import app, db
from models import User, CollectedCard, PriceCache, UserPreferences

def migrate_collected_cards():
    """Aggiunge le nuove colonne di caching alla tabella collected_cards.
    db.create_all() non modifica tabelle esistenti, quindi serve una migrazione manuale."""
    from sqlalchemy import inspect, text
    
    inspector = inspect(db.engine)
    columns = [col['name'] for col in inspector.get_columns('collected_cards')]
    
    if 'price_updated_at' not in columns:
        print("  - Aggiunta colonna price_updated_at a collected_cards...")
        with db.engine.connect() as conn:
            conn.execute(text("ALTER TABLE collected_cards ADD COLUMN price_updated_at DATETIME"))
            conn.commit()
    
    if 'price_source' not in columns:
        print("  - Aggiunta colonna price_source a collected_cards...")
        with db.engine.connect() as conn:
            conn.execute(text("ALTER TABLE collected_cards ADD COLUMN price_source VARCHAR(30)"))
            conn.commit()
    
    if 'language' not in columns:
        print("  - Aggiunta colonna language a collected_cards...")
        with db.engine.connect() as conn:
            conn.execute(text("ALTER TABLE collected_cards ADD COLUMN language VARCHAR(5) NOT NULL DEFAULT 'en'"))
            conn.commit()
    
    if 'user_id' not in columns:
        print("  - Aggiunta colonna user_id a collected_cards...")
        # Assegna le carte esistenti al primo utente (se presente)
        with db.engine.connect() as conn:
            first_user = conn.execute(text("SELECT id FROM users ORDER BY id LIMIT 1")).fetchone()
            default_user = first_user[0] if first_user else 1
            conn.execute(text(f"ALTER TABLE collected_cards ADD COLUMN user_id INTEGER NOT NULL DEFAULT {default_user}"))
            conn.commit()
    
    if 'added_at' not in columns:
        print("  - Aggiunta colonna added_at a collected_cards...")
        with db.engine.connect() as conn:
            conn.execute(text("ALTER TABLE collected_cards ADD COLUMN added_at DATETIME"))
            conn.commit()
    
    # Crea l'indice univoco (user_id, api_card_id, language) se non esiste
    with db.engine.connect() as conn:
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS unique_user_card_lang ON collected_cards (user_id, api_card_id, language)"))
        conn.commit()
    
    print("  [OK] Migrazione collected_cards completata")


def migrate_price_cache():
    """Aggiunge la colonna pending alla tabella price_cache.
    db.create_all() non modifica tabelle esistenti, quindi serve una migrazione manuale."""
    from sqlalchemy import inspect, text
    
    inspector = inspect(db.engine)
    columns = [col['name'] for col in inspector.get_columns('price_cache')]
    
    if 'pending' not in columns:
        print("  - Aggiunta colonna pending a price_cache...")
        with db.engine.connect() as conn:
            conn.execute(text("ALTER TABLE price_cache ADD COLUMN pending BOOLEAN NOT NULL DEFAULT 0"))
            conn.commit()
    
    if 'language' not in columns:
        print("  - Aggiunta colonna language a price_cache...")
        with db.engine.connect() as conn:
            conn.execute(text("ALTER TABLE price_cache ADD COLUMN language VARCHAR(5) NOT NULL DEFAULT 'en'"))
            conn.commit()
    
    print("  [OK] Migrazione price_cache completata")


def migrate_users():
    """Aggiunge la colonna is_admin alla tabella users.
    db.create_all() non modifica tabelle esistenti, quindi serve una migrazione manuale."""
    from sqlalchemy import inspect, text
    
    inspector = inspect(db.engine)
    columns = [col['name'] for col in inspector.get_columns('users')]
    
    if 'is_admin' not in columns:
        print("  - Aggiunta colonna is_admin a users...")
        with db.engine.connect() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT 0"))
            conn.commit()
    
    print("  [OK] Migrazione users completata")


def init_database():

    """Inizializza il database creando tutte le tabelle."""
    with app.app_context():
        print("Creazione tabelle del database...")
        
        # Crea tutte le tabelle
        db.create_all()
        
        # Migrazione per le nuove colonne di caching
        migrate_collected_cards()
        
        # Migrazione per la colonna pending di price_cache
        migrate_price_cache()
        
        # Migrazione per la colonna is_admin di users
        migrate_users()
        
        print("[OK] Tabelle create con successo!")


        print("\nTabelle disponibili:")
        print("  - users (utenti autenticati)")
        print("  - collected_cards (carte possedute per utente)")
        print("  - price_cache (cache prezzi scraped)")
        print("  - user_preferences (preferenze utente)")
        print("\nIl database è pronto per l'uso!")


def make_admin(email):
    """Promuove un utente a amministratore (per email).
    Uso: python init_db.py --make-admin email@example.com"""
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        if not user:
            print(f"ERRORE: Nessun utente trovato con email '{email}'")
            print("L'utente deve prima effettuare il login almeno una volta.")
            return False
        user.is_admin = True
        db.session.commit()
        print(f"[OK] Utente '{user.email}' promosso a amministratore!")
        return True


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--make-admin':
        if len(sys.argv) < 3:
            print("Uso: python init_db.py --make-admin email@example.com")
            sys.exit(1)
        make_admin(sys.argv[2])
    else:
        init_database()



