"""
Script per inizializzare il database con le nuove tabelle multi-utente.
Esegui questo script dopo aver configurato OAuth per creare le tabelle necessarie.
"""

from app import app, db
from models import User, CollectedCard, PriceCache, UserPreferences

def init_database():
    """Inizializza il database creando tutte le tabelle."""
    with app.app_context():
        print("Creazione tabelle del database...")
        
        # Crea tutte le tabelle
        db.create_all()
        
        print("✓ Tabelle create con successo!")
        print("\nTabelle disponibili:")
        print("  - users (utenti autenticati)")
        print("  - collected_cards (carte possedute per utente)")
        print("  - price_cache (cache prezzi scraped)")
        print("  - user_preferences (preferenze utente)")
        print("\nIl database è pronto per l'uso!")

if __name__ == "__main__":
    init_database()
