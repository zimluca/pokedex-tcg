import os
from dotenv import load_dotenv

# Carica le variabili d'ambiente dal file .env
load_dotenv()

class Config:
    """Configurazione dell'applicazione Flask."""
    
    # Secret key per le sessioni (CAMBIALA in produzione!)
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    
    # Database
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///collezione.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Google OAuth 2.0
    GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
    GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')
    GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
    
    # OAuth redirect URI (deve corrispondere a quello configurato in Google Console)
    OAUTHLIB_INSECURE_TRANSPORT = os.environ.get('OAUTHLIB_INSECURE_TRANSPORT', '1')  # Solo per sviluppo locale
    
    # ====== SCRAPING ======
    # Se False, lo scraping automatico dei prezzi (eBay/Cardmarket/TCGPlayer)
    # è DISATTIVATO. I prezzi vengono presi solo dall'API Pokémon e dalle
    # impostazioni manuali degli amministratori.
    # Il codice dello scraper resta nel progetto (scraper.py, price_updater.py)
    # per poterlo riattivare in futuro impostando questa variabile a True.
    SCRAPING_ENABLED = os.environ.get('SCRAPING_ENABLED', 'false').lower() in ('true', '1', 'yes')


