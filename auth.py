import json
import requests
from flask import Blueprint, redirect, request, url_for, session
from flask_login import login_user, logout_user, current_user
from oauthlib.oauth2 import WebApplicationClient

from models import db, User
from config import Config

auth_bp = Blueprint('auth', __name__)

# Verifica che le credenziali OAuth siano configurate
if not Config.GOOGLE_CLIENT_ID or not Config.GOOGLE_CLIENT_SECRET:
    print("[AUTH] ATTENZIONE: Credenziali Google OAuth non configurate!")
    print("[AUTH] Configura GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET nel file .env")

# Client OAuth
client = WebApplicationClient(Config.GOOGLE_CLIENT_ID) if Config.GOOGLE_CLIENT_ID else None


def get_google_provider_cfg():
    """Recupera la configurazione del provider Google OAuth."""
    try:
        response = requests.get(Config.GOOGLE_DISCOVERY_URL, timeout=5)
        return response.json()
    except Exception as e:
        print(f"Errore nel recupero della configurazione Google: {e}")
        return None


@auth_bp.route('/login')
def login():
    """Inizia il flusso di autenticazione Google OAuth."""
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    # Verifica che il client OAuth sia configurato
    if not client:
        return "Errore: credenziali OAuth non configurate. Controlla il file .env", 500
    
    # Recupera configurazione Google
    google_provider_cfg = get_google_provider_cfg()
    if not google_provider_cfg:
        return "Errore nella configurazione OAuth", 500
    
    authorization_endpoint = google_provider_cfg["authorization_endpoint"]
    
    # Costruisci l'URI di callback corretto
    redirect_uri = url_for('auth.callback', _external=True)
    print(f"[AUTH] Login avviato - redirect_uri: {redirect_uri}")
    
    # Costruisci la richiesta di autorizzazione
    request_uri = client.prepare_request_uri(
        authorization_endpoint,
        redirect_uri=redirect_uri,
        scope=["openid", "email", "profile"],
    )
    
    return redirect(request_uri)


@auth_bp.route('/callback')
def callback():
    """Gestisce il callback da Google dopo l'autenticazione."""
    # Ottieni il codice di autorizzazione da Google
    code = request.args.get("code")

    # Google può rimandare qui un errore (es. access_denied, redirect_uri_mismatch)
    oauth_error = request.args.get("error")
    if oauth_error:
        error_desc = request.args.get("error_description", "")
        print(f"[AUTH] Google ha restituito un errore: {oauth_error} - {error_desc}")
        return f"Accesso non riuscito ({oauth_error}). {error_desc}", 400

    if not code:
        print("[AUTH] Callback senza codice di autorizzazione")
        return "Errore: codice di autorizzazione mancante", 400
    
    # Recupera configurazione Google
    google_provider_cfg = get_google_provider_cfg()
    if not google_provider_cfg:
        return "Errore nella configurazione OAuth", 500
    
    token_endpoint = google_provider_cfg["token_endpoint"]
    
    # Costruisci l'URI di callback corretto (deve essere lo stesso usato in /login)
    redirect_uri = url_for('auth.callback', _external=True)
    
    # Prepara e invia la richiesta per ottenere i token
    token_url, headers, body = client.prepare_token_request(
        token_endpoint,
        authorization_response=request.url,
        redirect_url=redirect_uri,
        code=code
    )

    print(f"[AUTH] Scambio del codice - redirect_uri: {redirect_uri}")

    try:
        token_response = requests.post(
            token_url,
            headers=headers,
            data=body,
            auth=(Config.GOOGLE_CLIENT_ID, Config.GOOGLE_CLIENT_SECRET),
            timeout=10
        )
        token_data = token_response.json()
    except Exception as e:
        print(f"[AUTH] Errore di comunicazione con Google: {e}")
        return "Errore di comunicazione con Google. Riprova.", 500

    # Google può rifiutare lo scambio del codice (es. redirect_uri_mismatch, invalid_grant)
    if token_response.status_code != 200 or 'error' in token_data:
        error_code = token_data.get('error', 'unknown_error')
        error_desc = token_data.get('error_description', '')
        print(f"[AUTH] Google ha rifiutato lo scambio del codice: {error_code} - {error_desc}")
        return (
            f"Accesso non riuscito ({error_code}). {error_desc}<br>"
            "Verifica che l'URI di reindirizzamento autorizzato in Google Cloud Console "
            f"contenga esattamente: {redirect_uri}"
        ), 400

    # Analizza i token
    try:
        client.parse_request_body_response(json.dumps(token_data))
    except Exception as e:
        print(f"[AUTH] Risposta token non valida: {e}")
        return "Risposta non valida da Google. Riprova.", 500
    
    # Ottieni le informazioni dell'utente da Google
    userinfo_endpoint = google_provider_cfg["userinfo_endpoint"]
    uri, headers, body = client.add_token(userinfo_endpoint)
    userinfo_response = requests.get(uri, headers=headers, data=body, timeout=10)
    
    userinfo = userinfo_response.json()
    
    # Verifica che l'email sia verificata
    if not userinfo.get("email_verified"):
        return "Email non verificata da Google", 400
    
    # Estrai informazioni utente
    google_id = userinfo["sub"]
    email = userinfo["email"]
    name = userinfo.get("name")
    picture = userinfo.get("picture")
    
    # Cerca o crea l'utente nel database
    user = User.query.filter_by(google_id=google_id).first()
    
    if not user:
        # Nuovo utente
        user = User(
            google_id=google_id,
            email=email,
            name=name,
            picture=picture
        )
        db.session.add(user)
        print(f"[AUTH] Nuovo utente registrato: {email}")
    else:
        # Aggiorna informazioni utente esistente
        user.name = name
        user.picture = picture
        user.last_login = db.func.now()
        print(f"[AUTH] Utente esistente login: {email}")
    
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[AUTH] Errore nel salvataggio utente: {e}")
        return "Errore nel salvataggio dell'utente", 500
    
    # Login dell'utente con Flask-Login
    login_user(user, remember=True)
    
    return redirect(url_for('index'))


@auth_bp.route('/logout')
def logout():
    """Effettua il logout dell'utente."""
    logout_user()
    return redirect(url_for('index'))
