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
    
    # ====== SCANNER FOTOCAMERA (AI Vision) ======
    # Chiave API Google Gemini, usata per riconoscere le carte dalle foto.
    # Ottienila da: https://aistudio.google.com/app/apikey
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

    # Modello multimodale usato per il riconoscimento (deve supportare le immagini).
    # Può essere sovrascritto da variabile d'ambiente senza toccare il codice.
    # Nota: i modelli 1.5 e 2.5 non sono più disponibili per le nuove chiavi API.
    GEMINI_MODEL = os.environ.get('GEMINI_MODEL') or 'gemini-3.5-flash'

    # ====== SCRAPING ======
    # Se False, lo scraping automatico dei prezzi (eBay/Cardmarket/TCGPlayer)
    # è DISATTIVATO. I prezzi vengono presi solo dall'API Pokémon e dalle
    # impostazioni manuali degli amministratori.
    # Il codice dello scraper resta nel progetto (scraper.py, price_updater.py)
    # per poterlo riattivare in futuro impostando questa variabile a True.
    SCRAPING_ENABLED = os.environ.get('SCRAPING_ENABLED', 'false').lower() in ('true', '1', 'yes')


