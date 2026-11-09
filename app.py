import os
import re
import time
import threading
import json
import base64
from datetime import datetime


from flask import Flask, render_template, request, jsonify, redirect, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from flask_login import LoginManager, login_required, current_user
import requests

from models import db, User, Card, CollectedCard, PriceCache, UserPreferences
from config import Config

from auth import auth_bp
from price_updater import start_price_updater


app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

# Dietro un reverse proxy (tunnel cloudflared/ngrok, PythonAnywhere) lo schema originale
# arriva nell'header X-Forwarded-Proto. ProxyFix lo applica, così gli URL generati
# (in particolare il redirect URI OAuth) sono https:// e non http://.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

# Configurazione Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Effettua il login per accedere a questa pagina.'

# Gestione personalizzata per richieste AJAX non autenticate
@login_manager.unauthorized_handler
def unauthorized():
    """Gestisce le richieste non autenticate in modo appropriato per AJAX."""
    if request.is_json or request.headers.get('Content-Type') == 'application/json':
        return jsonify({"error": "Non autenticato", "redirect": url_for('auth.login')}), 401
    return redirect(url_for('auth.login'))

# Registra il blueprint di autenticazione
app.register_blueprint(auth_bp, url_prefix='/auth')


@app.after_request
def add_no_cache_headers(response):
    """Impedisce al browser di memorizzare nella cache le pagine.
    Così i prezzi (inclusi quelli manuali degli admin e i default per rarità)
    vengono sempre mostrati aggiornati, senza dover forzare l'aggiornamento."""
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response



@login_manager.user_loader
def load_user(user_id):
    """Carica l'utente dalla sessione."""
    return User.query.get(int(user_id))

POKEMON_API_BASE = "https://api.pokemontcg.io/v2"
REQUEST_TIMEOUT = 10  # secondi: evita che una richiesta lenta blocchi l'app
MAX_PAGES = 20         # sicurezza anti-loop-infinito in caso di risposte anomale
CACHE_TTL_HOURS = 24   # ore di validità del prezzo in cache prima di rifare scraping


# Chiave API Pokémon: in produzione va impostata come variabile d'ambiente
# (fallback alla chiave usata durante lo sviluppo)
POKEMON_API_KEY = os.environ.get('POKEMON_API_KEY', 'a72c1fed-a82f-4aa8-8974-106c8f056733')
HEADERS = {'X-Api-Key': POKEMON_API_KEY}

# ====== SCANNER FOTOCAMERA (AI Vision con Google Gemini) ======
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_API_KEY = Config.GEMINI_API_KEY
GEMINI_MODEL = Config.GEMINI_MODEL
GEMINI_TIMEOUT = 60                      # secondi: il riconoscimento di un'immagine richiede 10-20s
SCAN_MAX_IMAGE_BYTES = 8 * 1024 * 1024   # 8 MB: dimensione massima dell'immagine accettata

# Prompt di sistema inviato al modello: deve restituire SOLO il JSON richiesto
SCAN_SYSTEM_PROMPT = (
    'Analizza questa carta Pokémon. Restituisci ESATTAMENTE un JSON con due chiavi: '
    '"name" (il nome del Pokémon) e "number" (il numero della carta nel set, es. 025/165). '
    'Non scrivere altro'
)

sets_cache = None
set_cards_cache = {}  # cache in memoria: set_id -> lista di carte già scaricate

SETS_CACHE_FILE = os.path.join(os.path.dirname(__file__), 'instance', 'sets_cache.json')


def _load_sets_from_disk():
    """Carica la lista dei set dal file di cache su disco (fallback se API non disponibile)."""
    try:
        if os.path.exists(SETS_CACHE_FILE):
            with open(SETS_CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"[CACHE] Errore nel caricamento set da disco: {e}")
    return None

def _save_sets_to_disk(sets):
    """Salva la lista dei set su disco per uso futuro."""
    try:
        os.makedirs(os.path.dirname(SETS_CACHE_FILE), exist_ok=True)
        with open(SETS_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(sets, f, ensure_ascii=False)
    except Exception as e:
        print(f"[CACHE] Errore nel salvataggio set su disco: {e}")



def api_get(url, params=None, max_retries=3):
    """GET con timeout, gestione errori di connessione e retry automatico.
    Riprova su errori 429 (rate limit) e 5xx (errori server temporanei)."""
    for attempt in range(max_retries + 1):
        try:
            response = requests.get(url, headers=HEADERS, params=params, timeout=REQUEST_TIMEOUT)
        except requests.exceptions.RequestException as e:
            print(f"Errore di connessione: {e}")
            if attempt < max_retries:
                time.sleep(1.0)
                continue
            return None

        if response.status_code == 200:
            return response
        
        # Retry automatico per rate limit (429) ed errori server temporanei (5xx)
        if response.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
            wait_time = 1.5 * (attempt + 1)
            print(f"Errore HTTP {response.status_code}, attendo {wait_time}s prima di riprovare (tentativo {attempt + 1}/{max_retries})...")
            time.sleep(wait_time)
            continue

        print(f"Errore API (HTTP {response.status_code}): {response.text}")
        return None
    
    return None



def get_user_language():
    """Ottiene la lingua preferita dell'utente corrente."""
    if not current_user.is_authenticated:
        return None
    
    prefs = UserPreferences.query.filter_by(user_id=current_user.id).first()
    return prefs.preferred_language if prefs else None


def get_all_sets(language_filter=None):
    """Ottiene tutti i set.
    I set sono gli stessi per tutte le lingue (le carte cambiano lingua, non i set),
    quindi il filtro lingua NON filtra i set ma viene usato solo per il caricamento delle carte.
    Usa sempre la cache per evitare richieste API ripetute."""
    global sets_cache
    
    # Usa sempre la cache (i set non dipendono dalla lingua)
    if sets_cache is not None:
        return sets_cache

    print("[API] Scaricamento lista set...")
    response = api_get(f"{POKEMON_API_BASE}/sets")
    if response is None:
        print("[API] ERRORE: Impossibile scaricare i set")
        # Fallback: usa la cache su disco per non far sparire la sidebar
        disk_sets = _load_sets_from_disk()
        if disk_sets:
            print(f"[CACHE] Usati {len(disk_sets)} set dalla cache su disco")
            sets_cache = disk_sets
            return sets_cache
        sets_cache = None
        return []

    data = response.json()
    sets_cache = sorted(data.get('data', []), key=lambda x: x.get('releaseDate', ''), reverse=True)
    # Salva su disco per uso futuro (fallback se API non disponibile)
    _save_sets_to_disk(sets_cache)
    print(f"[API] Set scaricati con successo: {len(sets_cache)}")
    return sets_cache




def extract_tcgplayer_price(tcgplayer):
    """Estrae il prezzo da TCGPlayer come fallback quando Cardmarket non ha dati.
    Cerca in tutti i tipi di carte e campi prezzo disponibili."""
    if not tcgplayer or not isinstance(tcgplayer, dict):
        return 0.0, None
    
    prices = tcgplayer.get('prices', {})
    if not isinstance(prices, dict):
        return 0.0, None
    
    # Lista completa di tutti i possibili tipi di carte TCGPlayer
    # Cerca in TUTTI i tipi disponibili, non solo quelli predefiniti
    all_card_types = list(prices.keys())
    
    # Priorità: prima i tipi comuni, poi tutti gli altri
    priority_types = [
        'holofoil', 'reverseHolofoil', 'normal', 
        'unlimitedHolofoil', '1stEditionHolofoil',
        'unlimited', '1stEdition'
    ]
    
    # Combina: prima i prioritari, poi tutti gli altri
    card_types_to_check = priority_types + [t for t in all_card_types if t not in priority_types]
    
    for card_type in card_types_to_check:
        type_prices = prices.get(card_type, {})
        if not isinstance(type_prices, dict):
            continue
        
        # Cerca in TUTTI i campi prezzo disponibili
        # Priorità al prezzo minimo ('low') per il mercato in buone condizioni
        price_fields = ['low', 'market', 'mid', 'directLow', 'high']
        all_price_fields = list(type_prices.keys())
        fields_to_check = price_fields + [f for f in all_price_fields if f not in price_fields]

        
        for key in fields_to_check:
            value = type_prices.get(key)
            if value is not None:
                try:
                    price = float(value)
                    if price > 0:
                        return price, tcgplayer.get('url', None)
                except (ValueError, TypeError):
                    continue
    
    return 0.0, None


def get_cached_price(card_id, language='en'):
    """Recupera il prezzo dalla cache se disponibile e non obsoleto (24 ore).
    Il prezzo è specifico per lingua."""
    cached = PriceCache.query.filter_by(card_id=card_id, language=language).first()
    if cached and not cached.is_stale(hours=CACHE_TTL_HOURS):
        return cached.price, cached.url, cached.source
    return None, None, None


def cache_price(card_id, card_name, set_name, price, url, source, language='en'):
    """Salva il prezzo nella cache e aggiorna i campi prezzo delle carte in collezione.
    Il prezzo è specifico per lingua."""
    try:
        cached = PriceCache.query.filter_by(card_id=card_id, language=language).first()
        if cached:
            # Aggiorna esistente
            cached.price = price
            cached.url = url
            cached.source = source
            cached.scraped_at = db.func.now()
            cached.pending = False
        else:
            # Crea nuovo
            cached = PriceCache(
                card_id=card_id,
                card_name=card_name,
                set_name=set_name,
                language=language,
                price=price,
                url=url,
                source=source,
                pending=False
            )
            db.session.add(cached)
        
        # Aggiorna anche le carte in collezione che hanno questo card_id e lingua
        collected = CollectedCard.query.filter_by(api_card_id=card_id, language=language).all()
        for cc in collected:
            cc.price = price
            cc.price_updated_at = db.func.now()
            cc.price_source = source
        
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[CACHE] Errore nel salvataggio: {e}")


def queue_for_scraping(card_id, card_name, set_name, language='en'):
    """Mette una carta in coda per lo scraping in background.
    Crea una voce in PriceCache con pending=True se non esiste già una voce valida.
    La coda è specifica per lingua.
    Se SCRAPING_ENABLED è False, questa funzione non fa nulla (scraping disattivato)."""
    from config import Config
    
    # Se lo scraping è disattivato, non accodare nulla
    if not Config.SCRAPING_ENABLED:
        return
    
    try:
        cached = PriceCache.query.filter_by(card_id=card_id, language=language).first()
        if cached:
            # Se già in coda o ha un prezzo valido, non fare nulla
            if cached.pending:
                return
            if cached.price and cached.price > 0 and not cached.is_stale(hours=CACHE_TTL_HOURS):
                return
            # Segna come in coda per lo scraping
            cached.pending = True
        else:
            # Crea una nuova voce in coda
            cached = PriceCache(
                card_id=card_id,
                card_name=card_name,
                set_name=set_name,
                language=language,
                price=0.0,
                url=None,
                source='pending',
                pending=True
            )
            db.session.add(cached)
        
        db.session.commit()
        print(f"[CACHE] '{card_name}' ({language}) accodato per scraping in background")
    except Exception as e:
        db.session.rollback()
        print(f"[CACHE] Errore nell'accodamento: {e}")






def extract_price_info(cardmarket, tcgplayer=None, card_id=None, card_name=None, set_name=None, language='en', enable_scraping=True):
    """Restituisce (prezzo, url) usando il primo prezzo disponibile.
    Priorità: Prezzo manuale admin → Cardmarket API → TCGPlayer API → Cache → Scraping → 0.0
    Il prezzo è specifico per lingua: per 'it' si preferisce Cardmarket, per 'en' TCGPlayer.
    Gestisce in modo sicuro valori None, stringhe e numeri."""
    
    # 0. PRIORITÀ ASSOLUTA: prezzo manuale impostato dall'amministratore.
    #    Se un admin ha deciso il prezzo (source='manual'), questo ha la precedenza
    #    su qualsiasi prezzo API, così la decisione dell'admin è sempre rispettata.
    if card_id:
        manual = PriceCache.query.filter_by(card_id=card_id, language=language, source='manual').first()
        if manual and manual.price and manual.price > 0:
            print(f"[CACHE] Prezzo MANUALE (admin) per '{card_name}' ({language}): €{manual.price:.2f}")
            return manual.price, manual.url if manual.url else '#'
    
    cardmarket_price = 0.0
    cardmarket_url = '#'
    
    # 1. Prova prima con Cardmarket API (Europa) - preferito per italiano
    if cardmarket and isinstance(cardmarket, dict):
        cardmarket_url = cardmarket.get('url', '#')
        prices = cardmarket.get('prices', {})
        if isinstance(prices, dict):
            # Priorità al prezzo minimo ('lowPrice') per il mercato in buone condizioni
            priority_keys = ['lowPrice', 'trendPrice', 'averageSellPrice', 'avg1', 'avg7', 'avg30', 'suggestedPrice']
            all_keys = list(prices.keys())
            keys_to_check = priority_keys + [k for k in all_keys if k not in priority_keys]

            
            for key in keys_to_check:
                value = prices.get(key)
                if value is not None:
                    try:
                        price = float(value)
                        if price > 0:
                            cardmarket_price = price
                            break
                    except (ValueError, TypeError):
                        continue
    
    # Per italiano, Cardmarket è la fonte primaria
    if language == 'it' and cardmarket_price > 0:
        return cardmarket_price, cardmarket_url
    
    # 2. Prova con TCGPlayer API (USA) - preferito per inglese
    if tcgplayer:
        tcg_price, tcg_url = extract_tcgplayer_price(tcgplayer)
        if tcg_price > 0:
            return tcg_price, tcg_url if tcg_url else '#'
    
    # Per inglese, se TCGPlayer non ha prezzo, usa Cardmarket come fallback
    if language == 'en' and cardmarket_price > 0:
        return cardmarket_price, cardmarket_url
    
    # 3. Controlla la cache (se abbiamo card_id) - specifica per lingua
    if card_id:
        cached_price, cached_url, cached_source = get_cached_price(card_id, language)
        if cached_price and cached_price > 0:
            print(f"[CACHE] Prezzo da cache per '{card_name}' ({language}): €{cached_price:.2f} ({cached_source})")
            return cached_price, cached_url if cached_url else '#'
    
    # 4. Scraping in background: accoda la carta per lo scraping asincrono
    #    invece di bloccare la richiesta con scraping sincrono
    if card_id and card_name and set_name:
        queue_for_scraping(card_id, card_name, set_name, language)
    
    # 5. Nessun prezzo disponibile

    if cardmarket_url != '#':
        return 0.0, cardmarket_url
    if tcgplayer and isinstance(tcgplayer, dict):
        return 0.0, tcgplayer.get('url', '#')
    
    return 0.0, '#'



def get_default_price_by_rarity(rarity, name=''):
    """Restituisce un prezzo predefinito in base alla rarità della carta.
    Usato per i set senza dati di prezzo nell'API (es. serie 'me').
    - Comuni/Non comuni: €0.02
    - Rare: €0.10
    - ex (non fuori serie): €0.50
    - Altre carte più rare (full art, secret rare, ecc.): 0.0 (prezzo vuoto, da inserire manualmente)
    """
    if not rarity:
        return 0.0
    
    rarity_lower = rarity.lower()
    name_lower = name.lower()
    
    # Carte "ex" regolari (non full art, non fuori serie)
    # Rileva "ex" nel nome (es. "Charizard ex") ma esclude varianti speciali
    is_ex = ' ex' in name_lower or name_lower.endswith('ex') or ' ex ' in name_lower
    
    # Varianti speciali che NON ricevono il prezzo predefinito (da inserire manualmente)
    special_variants = [
        'full art', 'fullart', 'secret', 'hyper', 'rainbow', 'gold',
        'illustration', 'alt art', 'alternate', 'promo', 'vmax', 'vstar',
        'tera', 'ex full', 'sir', 'sar', 'ultra rare', 'special illustration'
    ]
    
    # Se è una variante speciale, non assegnare prezzo predefinito
    for variant in special_variants:
        if variant in rarity_lower or variant in name_lower:
            return 0.0
    
    # Rarità comuni e non comuni
    if 'common' in rarity_lower or 'uncommon' in rarity_lower:
        return 0.02
    
    # Rarità rare
    if 'rare' in rarity_lower:
        # Se è una "ex" regolare, prezzo più alto
        if is_ex:
            return 0.50
        return 0.10
    
    # Fallback: se il nome contiene "ex" ma non è una variante speciale
    if is_ex:
        return 0.50
    
    return 0.0


def format_card(card, language='en'):
    """Formatta i dati della carta dall'API in un dizionario semplificato.
    Il prezzo è specifico per lingua."""
    cardmarket = card.get('cardmarket')
    tcgplayer = card.get('tcgplayer')
    card_id = card.get('id', '')
    card_name = card.get('name', '')
    set_name = card.get('set', {}).get('id', '')
    rarity = card.get('rarity', '')
    
    # Estrai prezzo e URL (scraping sempre attivo) - specifico per lingua
    trend_price, price_url = extract_price_info(
        cardmarket, 
        tcgplayer,
        card_id=card_id,
        card_name=card_name,
        set_name=set_name,
        language=language
    )
    
    # Se non c'è prezzo dall'API/cache/scraping, usa il prezzo predefinito per rarità
    # (per i set senza dati di prezzo, es. serie 'me')
    if trend_price <= 0:
        trend_price = get_default_price_by_rarity(rarity, card_name)
    
    # Determina se il prezzo è disponibile o meno
    price_available = trend_price > 0
    
    return {
        'card_id': card_id,
        'nome_carta': card_name,
        'id_set': set_name,
        'immagine_url': card.get('images', {}).get('small', ''),
        'prezzo_stimato': trend_price,
        'prezzo_disponibile': price_available,
        'cardmarket_url': price_url,
        'numero': card.get('number', ''),
        'rarity': rarity,
        'language': language,
    }




def fetch_all_cards(query):
    """Scarica tutte le carte che corrispondono alla query, gestendo la paginazione.
    Richiede esplicitamente i dati di prezzo da Cardmarket e TCGPlayer.
    Restituisce None in caso di errore di connessione."""
    all_cards = []
    page = 1

    # Parametri per richiedere esplicitamente i prezzi
    params = {
        'q': query,
        'page': page,
        'pageSize': 250,
        'select': 'id,name,number,set,images,cardmarket,tcgplayer'
    }

    while page <= MAX_PAGES:
        params['page'] = page
        response = api_get(f"{POKEMON_API_BASE}/cards", params=params)
        if response is None:
            return None

        data = response.json()
        page_data = data.get('data', [])
        all_cards.extend(page_data)

        total_count = data.get('totalCount', len(all_cards))
        if len(all_cards) >= total_count or not page_data:
            break
        page += 1

    return all_cards


def extract_card_number(numero):
    """Estrae il numero dalla stringa del numero carta in modo sicuro.
    Gestisce formati come '1', '001', 'SV01', 'PROMO 1', ecc."""
    if not numero or not isinstance(numero, str):
        return 0
    
    match = re.search(r'\d+', numero)
    if match:
        try:
            return int(match.group())
        except ValueError:
            return 0
    return 0


def sort_by_number(cards):
    """Ordina le carte per numero estratto in modo sicuro."""
    cards.sort(key=lambda c: extract_card_number(c.get('numero', '')))
    return cards


# ====== SCANNER FOTOCAMERA: RICONOSCIMENTO E RICERCA ======

def decode_scan_image(data_uri):
    """Decodifica l'immagine Base64 ricevuta dal frontend (anche in formato data URI).
    Restituisce (immagine_bytes, mime_type).
    Solleva ValueError con un messaggio leggibile se i dati non sono validi."""
    if not data_uri or not isinstance(data_uri, str):
        raise ValueError('Immagine mancante nella richiesta')

    payload = data_uri.strip()
    mime_type = 'image/jpeg'

    # Il frontend invia un data URI: "data:image/jpeg;base64,...."
    if payload.startswith('data:'):
        header, _, payload = payload.partition(',')
        match = re.match(r'data:([^;]+)', header)
        if match:
            mime_type = match.group(1).lower()

    if mime_type not in ('image/jpeg', 'image/png', 'image/webp'):
        raise ValueError('Formato immagine non supportato: usa JPEG, PNG o WEBP')

    try:
        image_bytes = base64.b64decode(payload)
    except Exception:
        raise ValueError('Immagine non valida: codifica Base64 non riconosciuta')

    if not image_bytes:
        raise ValueError('Immagine vuota')

    if len(image_bytes) > SCAN_MAX_IMAGE_BYTES:
        raise ValueError('Immagine troppo grande: scatta una foto a risoluzione più bassa')

    return image_bytes, mime_type


def _extract_gemini_text(response_data):
    """Estrae il testo dalla risposta di Gemini.
    Restituisce una stringa vuota se il modello non ha prodotto contenuto."""
    candidates = response_data.get('candidates') or []
    if candidates:
        parts = (candidates[0].get('content') or {}).get('parts') or []
        return ''.join(part.get('text', '') for part in parts).strip()

    # Nessun candidato: il modello potrebbe aver bloccato l'immagine
    feedback = response_data.get('promptFeedback') or {}
    if feedback.get('blockReason'):
        print(f"[SCAN] Immagine rifiutata dal modello: {feedback.get('blockReason')}")
    return ''


def _parse_scan_json(text):
    """Converte la risposta del modello in dizionario.
    Tollerante ai blocchi markdown (```json ... ```) e a testo aggiuntivo attorno al JSON."""
    if not text:
        raise RuntimeError('Il riconoscimento non ha prodotto risultati: riprova con una foto più nitida')

    cleaned = text.strip()

    # Rimuove eventuali fence markdown
    if cleaned.startswith('```'):
        cleaned = re.sub(r'^```[a-zA-Z]*\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Fallback: estrae il primo oggetto JSON presente nel testo
        match = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

    raise RuntimeError('Il modello ha restituito una risposta non valida: riprova')


def analyze_card_image(image_bytes, mime_type='image/jpeg'):
    """Invia l'immagine a Google Gemini (modello multimodale) e restituisce (nome, numero).
    Solleva RuntimeError con un messaggio leggibile in caso di problemi."""
    if not GEMINI_API_KEY:
        raise RuntimeError('Scanner non configurato: imposta la variabile GEMINI_API_KEY nel file .env')

    url = f"{GEMINI_API_BASE}/{GEMINI_MODEL}:generateContent"
    payload = {
        'systemInstruction': {'parts': [{'text': SCAN_SYSTEM_PROMPT}]},
        'contents': [{
            'parts': [
                {'text': 'Riconosci la carta Pokémon in questa foto.'},
                {
                    'inline_data': {
                        'mime_type': mime_type,
                        'data': base64.b64encode(image_bytes).decode('ascii')
                    }
                }
            ]
        }],
        # temperature 0 = risposta deterministica; responseMimeType = JSON puro
        'generationConfig': {'temperature': 0.0, 'responseMimeType': 'application/json'}
    }

    try:
        response = requests.post(
            url,
            params={'key': GEMINI_API_KEY},
            json=payload,
            timeout=GEMINI_TIMEOUT
        )
    except requests.exceptions.RequestException as e:
        print(f"[SCAN] Errore di connessione al servizio di riconoscimento: {e}")
        raise RuntimeError('Impossibile contattare il servizio di riconoscimento: controlla la connessione e riprova')

    if response.status_code != 200:
        print(f"[SCAN] Errore Gemini (HTTP {response.status_code}): {response.text[:500]}")
        if response.status_code in (401, 403):
            raise RuntimeError('Chiave API Gemini non valida: controlla la configurazione')
        if response.status_code == 404:
            raise RuntimeError(
                f'Modello Gemini "{GEMINI_MODEL}" non disponibile: aggiorna GEMINI_MODEL nel file .env'
            )
        if response.status_code == 429:
            raise RuntimeError('Servizio di riconoscimento sovraccarico: riprova tra qualche istante')
        raise RuntimeError('Il servizio di riconoscimento ha restituito un errore: riprova più tardi')

    try:
        response_data = response.json()
    except ValueError:
        raise RuntimeError('Risposta non valida dal servizio di riconoscimento')

    data = _parse_scan_json(_extract_gemini_text(response_data))
    name = str(data.get('name') or '').strip()
    number = str(data.get('number') or '').strip()

    if not name or name.lower() in ('sconosciuto', 'sconosciuta', 'unknown', 'null', 'none'):
        raise RuntimeError('Carta non riconosciuta: inquadra la carta intera e riprova')

    return name, number


def parse_scan_number(number_value):
    """Separa numero e totale da un numero carta letto dalla scansione.
    Esempi: '025/165' -> ('025', 165); 'TG05/TG30' -> ('TG05', 30); '25' -> ('25', None)."""
    if not number_value or not isinstance(number_value, str):
        return '', None

    raw = number_value.strip().upper().replace(' ', '')
    numero, _, totale = raw.partition('/')

    total_int = None
    match = re.search(r'\d+', totale)
    if match:
        try:
            total_int = int(match.group())
        except ValueError:
            total_int = None

    return numero, total_int


def fetch_cards_page(query, page_size=60):
    """Scarica una singola pagina di risultati dall'API Pokémon TCG.
    Più leggera di fetch_all_cards(): serve per le ricerche mirate dello scanner.
    Restituisce None in caso di errore di connessione."""
    params = {
        'q': query,
        'page': 1,
        'pageSize': page_size,
        'select': 'id,name,number,set,images,cardmarket,tcgplayer,rarity'
    }
    response = api_get(f"{POKEMON_API_BASE}/cards", params=params)
    if response is None:
        return None
    return response.json().get('data', [])


def pick_best_card_match(cards, numero, totale):
    """Sceglie la carta più coerente con il numero letto dalla scansione.
    Se il numero non è disponibile, restituisce il primo risultato (ordine di rilevanza dell'API)."""
    if not cards:
        return None
    if not numero:
        return cards[0]

    target = extract_card_number(numero)
    if target <= 0:
        return cards[0]

    exact = [c for c in cards if extract_card_number(c.get('number', '')) == target]
    if not exact:
        return None

    # Il totale del set aiuta a distinguere carte con lo stesso numero in set diversi
    if totale:
        for card in exact:
            set_data = card.get('set') or {}
            if (set_data.get('printedTotal') or set_data.get('total')) == totale:
                return card

    return exact[0]


def find_card_by_name_and_number(name, number_value):
    """Cerca nell'API Pokémon TCG la carta con il nome e il numero indicati.
    Restituisce il dizionario della carta API oppure None se non viene trovata."""
    # Le virgolette romperebbero la query dell'API: le rimuoviamo dal nome
    name = (name or '').strip().replace('"', '').replace('\\', '')
    if not name:
        return None

    numero, totale = parse_scan_number(number_value)

    if numero:
        # Il campo 'number' dell'API è una stringa ("25", "TG05", ...):
        # proviamo alcune varianti per gestire gli zeri iniziali (es. "025" -> "25")
        variants = [numero]
        if numero.isdigit():
            for candidate in (numero.lstrip('0'), numero.zfill(3)):
                if candidate and candidate not in variants:
                    variants.append(candidate)

        for candidate in variants:
            cards = fetch_cards_page(f'name:"{name}" number:{candidate}')
            if cards:
                best = pick_best_card_match(cards, numero, totale)
                if best:
                    return best

    # Fallback: ricerca per solo nome e confronto dei numeri lato server
    cards = fetch_cards_page(f'name:"{name}"', page_size=250)
    if not cards:
        return None
    return pick_best_card_match(cards, numero, totale)


def detect_price_source(card, price, language='en'):
    """Determina la fonte del prezzo principale di una carta (campo CollectedCard.price_source).
    Segue la stessa priorità usata in /api/card/<card_id>:
    prezzo manuale admin -> Cardmarket (IT) / TCGPlayer (EN) -> prezzo predefinito per rarità."""
    if not price or price <= 0:
        return None

    # 0. Prezzo manuale impostato dall'amministratore: priorità assoluta
    manual = PriceCache.query.filter_by(
        card_id=card.get('id', ''),
        language=language,
        source='manual'
    ).first()
    if manual and manual.price and manual.price > 0:
        return 'manual'

    # 1. Prezzo Cardmarket (stessa priorità di extract_price_info)
    cardmarket_price = 0.0
    prices = (card.get('cardmarket') or {}).get('prices') or {}
    if isinstance(prices, dict):
        priority_keys = ['lowPrice', 'trendPrice', 'averageSellPrice', 'avg1', 'avg7', 'avg30', 'suggestedPrice']
        keys_to_check = priority_keys + [k for k in prices.keys() if k not in priority_keys]
        for key in keys_to_check:
            try:
                value = float(prices.get(key))
            except (ValueError, TypeError):
                continue
            if value > 0:
                cardmarket_price = value
                break

    # 2. Prezzo TCGPlayer
    tcgplayer_price, _ = extract_tcgplayer_price(card.get('tcgplayer'))

    if language == 'it':
        if cardmarket_price > 0:
            return 'cardmarket'
        if tcgplayer_price > 0:
            return 'tcgplayer'
    else:
        if tcgplayer_price > 0:
            return 'tcgplayer'
        if cardmarket_price > 0:
            return 'cardmarket'

    # 3. Nessun prezzo di mercato: il prezzo salvato è quello predefinito per rarità
    return 'default'


def calculate_collection_stats(user_id=None):
    """Calcola statistiche della collezione: valore, conteggi e aggregati per set.
    Se user_id è None, usa l'utente corrente.
    Restituisce (total_value, set_values_dict, set_counts_dict)."""
    try:
        if user_id is None and current_user.is_authenticated:
            user_id = current_user.id
        
        if not user_id:
            return 0.0, {}, {}
        
        collected_cards = CollectedCard.query.filter_by(user_id=user_id).all()
        total_value = 0.0
        set_values = {}
        set_counts = {}
        
        for card in collected_cards:
            price = card.price if card.price else 0.0
            total_value += price
            
            # Aggrega per set (set_name contiene l'id del set, es. "sv3")
            set_id = card.set_name
            set_values[set_id] = set_values.get(set_id, 0.0) + price
            set_counts[set_id] = set_counts.get(set_id, 0) + 1
        
        return round(total_value, 2), set_values, set_counts
    except Exception as e:
        print(f"Errore nel calcolo delle statistiche: {e}")
        return 0.0, {}, {}


def build_market_analysis(card_id, current_price):
    """Costruisce l'analisi di mercato mostrata nella scheda finanziaria della carta.
    NOTA: lo storico è SIMULATO (deterministico rispetto alla carta) finché non
    verranno integrati i prezzi storici reali (Cardmarket / eBay).
    Restituisce: history, ema7, ema30, zscore, momentum, trend, confidenza, ecc."""
    from datetime import date, timedelta
    import random

    price = float(current_price or 0)
    rng = random.Random(f"{card_id}:{round(price, 2)}")

    days = 30
    base = price if price > 0 else 1.0
    value = base * (1 + rng.uniform(-0.10, 0.10))
    history = []
    for index in range(days):
        value = max(0.01, value * (1 + rng.uniform(-0.018, 0.020)))
        day = date.today() - timedelta(days=days - 1 - index)
        history.append({'date': day.isoformat(), 'price': round(value, 2)})

    # L'ultimo punto coincide sempre con il prezzo attuale della carta
    if price > 0:
        history[-1]['price'] = round(price, 2)

    prices = [point['price'] for point in history]
    average = sum(prices) / len(prices)
    variance = sum((point - average) ** 2 for point in prices) / len(prices)
    deviation = variance ** 0.5

    def ema(series, period):
        """Media mobile esponenziale."""
        k = 2 / (period + 1)
        result = series[0]
        for point in series[1:]:
            result = point * k + result * (1 - k)
        return result

    ema7 = ema(prices, 7)
    ema30 = ema(prices, 30)
    zscore = ((price - average) / deviation) if deviation > 0 else 0.0
    momentum = ((prices[-1] - prices[0]) / prices[0] * 100) if prices[0] else 0.0

    if zscore <= -1.0 or momentum > 3:
        trend = 'buy'
    elif zscore >= 1.0 or momentum < -3:
        trend = 'sell'
    else:
        trend = 'hold'

    labels = {'buy': 'Compra', 'sell': 'Vendi', 'hold': 'Mantieni'}
    volatility = (deviation / average * 100) if average else 0.0
    # Più lo storico è stabile, più il segnale è affidabile
    confidence = int(max(45, min(92, round(90 - volatility * 1.6))))

    return {
        'available': price > 0,
        'history': history,
        'ema7': round(ema7, 2),
        'ema30': round(ema30, 2),
        'average': round(average, 2),
        'zscore': round(zscore, 2),
        'momentum': round(momentum, 1),
        'volatility': round(volatility, 1),
        'min': round(min(prices), 2),
        'max': round(max(prices), 2),
        'trend': trend,
        'trend_label': labels[trend],
        'confidence': confidence,
        'simulated': True,
    }


def get_navigation_context():
    """Contesto comune a tutte le pagine (utente, lingua, statistiche portafoglio)."""
    user_language = get_user_language()

    if current_user.is_authenticated:
        total_value, set_values, set_counts = calculate_collection_stats()
    else:
        total_value, set_values, set_counts = 0.0, {}, {}

    return {
        'user': current_user,
        'is_admin': is_admin_user(),
        'user_language': user_language or '',
        'total_value': total_value,
        'set_values': set_values,
        'set_counts': set_counts,
        'owned_count': sum(set_counts.values()) if set_counts else 0,
    }


def render_cards_page(cards=None, current_set_id=None, error=None):
    """Funzione helper per renderizzare la pagina con le carte.
    Elimina duplicazione di codice tra le varie rotte."""
    
    # Ottieni lingua preferita e filtra i set
    user_language = get_user_language()
    sets = get_all_sets(language_filter=user_language)

    # Contesto comune (utente, lingua, statistiche del portafoglio)
    context = get_navigation_context()
    set_counts = context['set_counts']

    # Nome leggibile e totale dell'espansione corrente
    current_set_name = None
    current_set_total = 0
    if current_set_id:
        # Preferisci il totale API del set; se manca, usa le carte già caricate
        for set_data in sets:
            if set_data.get('id') == current_set_id:
                current_set_name = set_data.get('name')
                current_set_total = set_data.get('total') or set_data.get('printedTotal') or 0
                break
        if not current_set_total and cards:
            current_set_total = len(cards)

    # Valore medio per carta (KPI della dashboard)
    avg_card_value = 0.0
    if context['owned_count']:
        avg_card_value = round(context['total_value'] / context['owned_count'], 2)

    return render_template(
        'index.html',
        sets=sets,
        results=cards or [],
        current_set_id=current_set_id,
        current_set_name=current_set_name,
        current_set_owned=set_counts.get(current_set_id, 0) if current_set_id else 0,
        current_set_total=current_set_total,
        avg_card_value=avg_card_value,
        error=error,
        active_page='dashboard',
        **context
    )



@app.route('/')
def index():
    return render_cards_page()


@app.route('/search', methods=['GET'])
def search():
    query = request.args.get('query', '').strip()
    
    if not query:
        return render_cards_page()

    # Ottieni la lingua preferita dell'utente
    user_language = get_user_language() or 'en'
    # Normalizza: solo 'it' o 'en' sono supportati per i prezzi
    if user_language not in ('it', 'en'):
        user_language = 'en'

    raw_cards = fetch_all_cards(f"name:{query}")
    if raw_cards is None:
        return render_cards_page(error='Errore di connessione al database Pokémon')

    cards = sort_by_number([format_card(c, language=user_language) for c in raw_cards])
    return render_cards_page(cards=cards)


@app.route('/set/<set_id>', methods=['GET'])
def get_set_cards(set_id):
    # Ottieni la lingua preferita dell'utente
    user_language = get_user_language() or 'en'
    # Normalizza: solo 'it' o 'en' sono supportati per i prezzi
    if user_language not in ('it', 'en'):
        user_language = 'en'

    # Usa la cache se disponibile (cache per set+lingua)
    cache_key = f"{set_id}:{user_language}"
    if cache_key in set_cards_cache:
        return render_cards_page(cards=set_cards_cache[cache_key], current_set_id=set_id)

    raw_cards = fetch_all_cards(f"set.id:{set_id}")
    if raw_cards is None:
        return render_cards_page(current_set_id=set_id, error='Errore di connessione al database Pokémon')

    cards = sort_by_number([format_card(c, language=user_language) for c in raw_cards])
    set_cards_cache[cache_key] = cards
    
    return render_cards_page(cards=cards, current_set_id=set_id)



@app.route('/news')
def news():
    """Pagina 'Mercato & News'.
    Per ora mostra una lista dimostrativa di notizie: la struttura è già pronta
    per essere alimentata da una vera fonte (feed RSS / API di settore)."""
    news_items = [
        {
            'id': 1,
            'title': 'Il mercato delle carte Pokémon supera i 2 miliardi di euro',
            'date': '6 novembre 2026',
            'date_iso': '2026-11-06',
            'tag': 'Trend',
            'source': 'Market Watch',
            'read_time': '3 min',
            'impact': 'up',
            'impact_label': 'Rialzo',
            'summary': (
                'Le vendite di carte singole crescono a doppia cifra trainte dalle serie '
                'speciali e dal collezionismo internazionale. I set più recenti registrano '
                'volumi in aumento del 12% rispetto allo scorso trimestre.'
            ),
        },
        {
            'id': 2,
            'title': 'Cardmarket: nuove soglie di prezzo per le ristampe',
            'date': '4 novembre 2026',
            'date_iso': '2026-11-04',
            'tag': 'Prezzi',
            'source': 'Cardmarket Insight',
            'read_time': '4 min',
            'impact': 'warn',
            'impact_label': 'Osservare',
            'summary': (
                'L\'introduzione delle ristampe ha ridotto il prezzo medio delle carte '
                'full art del 7%. Gli analisti consigliano di attendere la stabilizzazione '
                'prima di nuovi acquisti sulle rarità più alte.'
            ),
        },
        {
            'id': 3,
            'title': 'Collezionismo: cresce il gradimento per le carte in italiano',
            'date': '2 novembre 2026',
            'date_iso': '2026-11-02',
            'tag': 'Collezionismo',
            'source': 'TCG Italia',
            'read_time': '2 min',
            'impact': 'down',
            'impact_label': 'Ribasso',
            'summary': (
                'Le carte in lingua italiana stanno recuperando valore rispetto alle '
                'controparti inglesi, con una contrazione dei prezzi delle versioni EN '
                'sui mercati europei.'
            ),
        },
    ]

    return render_template(
        'news.html',
        news_items=news_items,
        active_page='news',
        **get_navigation_context()
    )


@app.route('/api/collection/add', methods=['POST'])
@login_required
def add_to_collection():
    try:
        data = request.json
        print(f"[API] Richiesta aggiunta carta - User ID: {current_user.id}, Email: {current_user.email}")
        print(f"[API] Dati ricevuti: {data}")
    except Exception as e:
        print(f"[API] Errore nel parsing della richiesta: {e}")
        return jsonify({"error": "Richiesta non valida"}), 400
    
    # Validazione input
    if not data or 'card_id' not in data:
        print("[API] ERRORE: Dati mancanti nella richiesta")
        return jsonify({"error": "Dati mancanti"}), 400
    
    card_id = data.get('card_id', '').strip()
    if not card_id:
        print("[API] ERRORE: ID carta vuoto")
        return jsonify({"error": "ID carta non valido"}), 400
    
    # Lingua della carta (default 'en', solo 'it' o 'en' supportati)
    language = data.get('language', 'en')
    if language not in ('it', 'en'):
        language = 'en'
    
    # Verifica se già presente per questo utente nella stessa lingua
    already_owned = CollectedCard.query.filter_by(
        user_id=current_user.id,
        api_card_id=card_id,
        language=language
    ).first()
    
    if already_owned:
        return jsonify({"message": "Carta già presente in collezione"}), 200

    # Validazione e conversione prezzo (accetta anche prezzi inseriti manualmente)
    try:
        price = float(data.get('price', 0))
        # Accetta prezzi negativi come 0
        if price < 0:
            price = 0.0
    except (ValueError, TypeError):
        price = 0.0

    try:
        # Verifica che il database sia accessibile
        try:
            from sqlalchemy import text
            db.session.execute(text('SELECT 1'))
        except Exception as db_error:
            print(f"[API] ERRORE: Database non accessibile: {db_error}")
            return jsonify({"error": "Database non disponibile"}), 503

        
        card = CollectedCard(
            user_id=current_user.id,
            api_card_id=card_id,
            name=data.get('name', 'Sconosciuta')[:100],  # Limita lunghezza
            set_name=data.get('set_id', 'Sconosciuto')[:100],
            language=language,
            price=price,
            price_updated_at=datetime.utcnow(),
            price_source='manual'
        )
        
        print(f"[API] Oggetto carta creato: user_id={current_user.id}, card_id={card_id}, name={card.name}, set={card.set_name}, lang={language}, price={price}")


        
        db.session.add(card)
        print(f"[API] Carta aggiunta alla sessione, eseguo flush...")
        
        db.session.flush()  # Forza la validazione prima del commit
        print(f"[API] Flush completato, eseguo commit...")
        
        db.session.commit()
        print(f"[API] Commit completato! Carta aggiunta con successo: {card_id} per user {current_user.id}")
        
        return jsonify({"message": "Carta aggiunta con successo", "price": price}), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"[API] ERRORE nell'aggiunta della carta:")

        print(f"  Tipo errore: {type(e).__name__}")
        print(f"  Messaggio: {str(e)}")
        print(f"  User ID: {current_user.id}")
        print(f"  Card ID: {card_id}")
        print(f"  Nome carta: {data.get('name', 'N/A')}")
        print(f"  Set: {data.get('set_id', 'N/A')}")
        
        import traceback
        traceback.print_exc()
        
        # Restituisci un messaggio di errore più dettagliato
        error_msg = str(e)
        if "UNIQUE constraint failed" in error_msg:
            return jsonify({"error": "Carta già presente nella collezione"}), 409
        elif "NOT NULL constraint failed" in error_msg:
            return jsonify({"error": "Dati mancanti per salvare la carta"}), 400
        else:
            return jsonify({"error": f"Errore nel salvataggio: {error_msg}"}), 500


@app.route('/api/scan-card', methods=['POST'])
@login_required
def scan_card():
    """Riconosce una carta Pokémon da una foto e la aggiunge alla collezione.
    Flusso: immagine Base64 -> AI Vision (Google Gemini) -> API Pokémon TCG -> salvataggio.
    Restituisce sempre JSON, anche in caso di errore, per non far crashare il frontend."""
    data = request.get_json(silent=True) or {}

    # Lingua della carta (default 'en', solo 'it' o 'en' supportati)
    language = data.get('language', 'en')
    if language not in ('it', 'en'):
        language = 'en'

    # 1. Validazione dell'immagine ricevuta
    try:
        image_bytes, mime_type = decode_scan_image(data.get('image'))
    except ValueError as e:
        print(f"[SCAN] Immagine non valida: {e}")
        return jsonify({"error": str(e)}), 400

    print(f"[SCAN] Nuova scansione - User ID: {current_user.id}, immagine: {len(image_bytes)} bytes ({mime_type})")

    # 2. Riconoscimento della carta con AI Vision
    try:
        card_name, card_number = analyze_card_image(image_bytes, mime_type)
    except RuntimeError as e:
        print(f"[SCAN] Riconoscimento non riuscito: {e}")
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        print(f"[SCAN] Errore imprevisto nel riconoscimento: {e}")
        return jsonify({"error": "Errore durante il riconoscimento della carta"}), 500

    print(f"[SCAN] Carta riconosciuta: '{card_name}' n. '{card_number}'")

    # 3. Ricerca della carta esatta nell'API Pokémon TCG
    try:
        card = find_card_by_name_and_number(card_name, card_number)
    except Exception as e:
        print(f"[SCAN] Errore nella ricerca della carta: {e}")
        return jsonify({"error": "Errore nella ricerca della carta"}), 500

    if not card:
        return jsonify({
            "error": f"Carta non trovata ('{card_name}' n. {card_number or '?'}): riprova inquadrando meglio la carta"
        }), 404

    card_id = card.get('id', '')
    set_id = (card.get('set') or {}).get('id', '')
    set_full_name = (card.get('set') or {}).get('name', set_id)

    # Prezzo e dati "pronti per la collezione" con la stessa logica del resto dell'app
    formatted = format_card(card, language=language)
    price = formatted.get('prezzo_stimato', 0.0)

    card_payload = {
        'card_id': card_id,
        'name': formatted.get('nome_carta', card_name),
        'number': formatted.get('numero', card_number),
        'set_id': formatted.get('id_set', set_id),
        'set_name': set_full_name,
        'image_url': formatted.get('immagine_url', ''),
        'rarity': formatted.get('rarity', ''),
        'price': round(price, 2),
        'price_available': formatted.get('prezzo_disponibile', False),
        'language': language
    }

    # 4. Salvataggio nella collezione (senza duplicati)
    already_owned = CollectedCard.query.filter_by(
        user_id=current_user.id,
        api_card_id=card_id,
        language=language
    ).first()

    if already_owned:
        print(f"[SCAN] Carta già in collezione per user {current_user.id}: {card_id}")
        return jsonify({
            "message": "Carta già presente in collezione",
            "owned": True,
            "card": card_payload
        }), 200

    try:
        collected = CollectedCard(
            user_id=current_user.id,
            api_card_id=card_id,
            name=card_payload['name'][:100],
            set_name=card_payload['set_id'][:100],
            language=language,
            price=price,
            price_updated_at=datetime.utcnow(),
            price_source=detect_price_source(card, price, language)
        )
        db.session.add(collected)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[SCAN] Errore nel salvataggio della carta {card_id}: {e}")
        import traceback
        traceback.print_exc()

        # Se la carta è stata aggiunta nel frattempo (doppio scatto), non è un errore
        if "UNIQUE constraint failed" in str(e):
            return jsonify({
                "message": "Carta già presente in collezione",
                "owned": True,
                "card": card_payload
            }), 200

        return jsonify({"error": "Errore nel salvataggio della carta"}), 500

    print(f"[SCAN] Carta aggiunta alla collezione: {card_id} ({card_payload['name']}) per user {current_user.id}")

    return jsonify({
        "message": "Carta riconosciuta e aggiunta alla collezione",
        "owned": True,
        "card": card_payload
    }), 200


@app.route('/api/collection/update_price', methods=['POST'])
@login_required
def update_card_price():
    """Aggiorna il prezzo di una carta nella collezione."""
    data = request.json
    
    # Validazione input
    if not data or 'card_id' not in data or 'price' not in data:
        return jsonify({"error": "Dati mancanti"}), 400
    
    card_id = data.get('card_id', '').strip()
    if not card_id:
        return jsonify({"error": "ID carta non valido"}), 400
    
    # Lingua della carta (default 'en')
    language = data.get('language', 'en')
    if language not in ('it', 'en'):
        language = 'en'
    
    # Validazione prezzo
    try:
        new_price = float(data.get('price', 0))
        if new_price < 0:
            return jsonify({"error": "Il prezzo non può essere negativo"}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "Prezzo non valido"}), 400
    
    card = CollectedCard.query.filter_by(
        user_id=current_user.id,
        api_card_id=card_id,
        language=language
    ).first()
    
    if not card:
        return jsonify({"error": "Carta non trovata in collezione"}), 404

    
    try:
        card.price = new_price
        card.price_updated_at = datetime.utcnow()
        card.price_source = 'manual'
        db.session.commit()
        return jsonify({"message": "Prezzo aggiornato con successo", "new_price": new_price}), 200
    except Exception as e:
        db.session.rollback()
        print(f"Errore nell'aggiornamento del prezzo: {e}")
        return jsonify({"error": "Errore nell'aggiornamento"}), 500



@app.route('/api/collection/remove', methods=['POST'])
@login_required
def remove_from_collection():
    data = request.json
    
    # Validazione input
    if not data or 'card_id' not in data:
        return jsonify({"error": "Dati mancanti"}), 400
    
    card_id = data.get('card_id', '').strip()
    if not card_id:
        return jsonify({"error": "ID carta non valido"}), 400
    
    # Lingua della carta (default 'en')
    language = data.get('language', 'en')
    if language not in ('it', 'en'):
        language = 'en'
    
    card = CollectedCard.query.filter_by(
        user_id=current_user.id,
        api_card_id=card_id,
        language=language
    ).first()
    
    if not card:
        return jsonify({"message": "Carta non trovata"}), 404

    
    try:
        db.session.delete(card)
        db.session.commit()
        return jsonify({"message": "Carta rimossa con successo"}), 200
    except Exception as e:
        db.session.rollback()
        print(f"Errore nella rimozione della carta: {e}")
        return jsonify({"error": "Errore nella rimozione"}), 500


@app.route('/api/card/<card_id>', methods=['GET'])
def get_card_detail(card_id):
    """Restituisce i dettagli completi di una carta con i prezzi da più fonti.
    Fonti: Cardmarket API, TCGPlayer API, eBay (scraping).
    Il prezzo è specifico per lingua."""
    try:
        # Ottieni la lingua preferita dell'utente
        user_language = get_user_language() or 'en'
        if user_language not in ('it', 'en'):
            user_language = 'en'

        # Recupera i dati completi della carta dall'API Pokémon
        response = api_get(f"{POKEMON_API_BASE}/cards/{card_id}")
        if response is None:
            return jsonify({"error": "Errore di connessione al database Pokémon"}), 500

        data = response.json()
        card = data.get('data')
        if not card:
            return jsonify({"error": "Carta non trovata"}), 404

        cardmarket = card.get('cardmarket') or {}
        tcgplayer = card.get('tcgplayer') or {}
        card_name = card.get('name', '')
        set_data = card.get('set', {})
        set_name = set_data.get('id', '')
        set_full_name = set_data.get('name', '')

        # ====== PREZZO CARDMARKET ======
        cardmarket_price = 0.0
        cardmarket_url = cardmarket.get('url', '#')
        if isinstance(cardmarket.get('prices'), dict):
            prices = cardmarket['prices']
            priority_keys = ['lowPrice', 'trendPrice', 'averageSellPrice', 'avg1', 'avg7', 'avg30', 'suggestedPrice']
            all_keys = list(prices.keys())
            keys_to_check = priority_keys + [k for k in all_keys if k not in priority_keys]
            for key in keys_to_check:
                try:
                    val = float(prices.get(key))
                    if val > 0:
                        cardmarket_price = val
                        break
                except (ValueError, TypeError):
                    continue

        # ====== PREZZO TCGPLAYER ======
        tcgplayer_price, tcgplayer_url = extract_tcgplayer_price(tcgplayer)
        if not tcgplayer_url:
            tcgplayer_url = tcgplayer.get('url', '#')

        # ====== PREZZO EBAY (dalla cache, NON scraping sincrono) ======
        # eBay viene scraped in background dal daemon price_updater
        # Qui leggiamo solo dalla cache per non bloccare l'interfaccia
        ebay_price = 0.0
        ebay_url = '#'
        cached_ebay = PriceCache.query.filter_by(card_id=card_id, language=f"{user_language}_ebay").first()
        if cached_ebay and cached_ebay.price and cached_ebay.price > 0:
            ebay_price = cached_ebay.price
            ebay_url = cached_ebay.url or '#'

        # ====== PREZZO PRINCIPALE (per collezione) ======
        # PRIORITÀ ASSOLUTA: prezzo manuale impostato dall'amministratore.
        # Se un admin ha deciso il prezzo (source='manual'), questo ha la precedenza
        # su qualsiasi prezzo API, così la decisione dell'admin è sempre rispettata.
        main_price = 0.0
        main_source = ''
        manual = PriceCache.query.filter_by(card_id=card_id, language=user_language, source='manual').first()
        if manual and manual.price and manual.price > 0:
            main_price = manual.price
            main_source = 'manual'
            print(f"[CACHE] Prezzo MANUALE (admin) per '{card_name}' ({user_language}): €{main_price:.2f}")
        elif user_language == 'it':
            # Per italiano preferisci Cardmarket
            if cardmarket_price > 0:
                main_price = cardmarket_price
                main_source = 'cardmarket'
            elif tcgplayer_price > 0:
                main_price = tcgplayer_price
                main_source = 'tcgplayer'
            elif ebay_price > 0:
                main_price = ebay_price
                main_source = 'ebay'
        else:
            # Per inglese preferisci TCGPlayer
            if tcgplayer_price > 0:
                main_price = tcgplayer_price
                main_source = 'tcgplayer'
            elif cardmarket_price > 0:
                main_price = cardmarket_price
                main_source = 'cardmarket'
            elif ebay_price > 0:
                main_price = ebay_price
                main_source = 'ebay'


        # ====== SE NESSUN PREZZO DISPONIBILE, USA PREZZO PREDEFINITO PER RARITÀ ======
        # Per i set senza dati di prezzo (es. serie 'me'), assegna un prezzo
        # predefinito in base alla rarità. Le carte più rare (full art, secret,
        # ecc.) restano senza prezzo per essere inserite manualmente.
        rarity = card.get('rarity', '')
        if main_price == 0.0:
            default_price = get_default_price_by_rarity(rarity, card_name)
            if default_price > 0:
                main_price = default_price
                main_source = 'default'
            else:
                # Solo per le carte senza prezzo predefinito, accoda per background
                queue_for_scraping(card_id, card_name, set_name, user_language)



        # Verifica se la carta è in collezione (se autenticato)
        owned = False
        if current_user.is_authenticated:
            owned = CollectedCard.query.filter_by(
                user_id=current_user.id,
                api_card_id=card_id,
                language=user_language
            ).first() is not None

        return jsonify({
            'card_id': card_id,
            'name': card_name,
            'number': card.get('number', ''),
            'set_id': set_name,
            'set_name': set_full_name,
            'image_url': card.get('images', {}).get('large', card.get('images', {}).get('small', '')),
            'rarity': card.get('rarity', ''),
            'types': card.get('types', []),
            'hp': card.get('hp', ''),
            'artist': card.get('artist', ''),
            'language': user_language,
            'prices': {
                'cardmarket': {
                    'price': round(cardmarket_price, 2),
                    'url': cardmarket_url,
                    'available': cardmarket_price > 0
                },
                'tcgplayer': {
                    'price': round(tcgplayer_price, 2),
                    'url': tcgplayer_url,
                    'available': tcgplayer_price > 0
                },
                'ebay': {
                    'price': round(ebay_price, 2),
                    'url': ebay_url,
                    'available': ebay_price > 0
                }
            },
            'main_price': round(main_price, 2),
            'main_source': main_source,
            'market': build_market_analysis(card_id, main_price),
            'owned': owned
        }), 200

    except Exception as e:
        print(f"[API] Errore nel recupero dettagli carta {card_id}: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Errore nel recupero dei dettagli della carta"}), 500


@app.route('/api/collection', methods=['GET'])
@login_required
def get_collection():

    """Restituisce tutte le carte nella collezione dell'utente corrente.
    Supporta il filtro per lingua (query param 'language')."""
    try:
        language = request.args.get('language', '')
        query = CollectedCard.query.filter_by(user_id=current_user.id)
        if language in ('it', 'en'):
            query = query.filter_by(language=language)
        cards = query.all()
        return jsonify([card.to_dict() for card in cards]), 200
    except Exception as e:
        print(f"Errore nel recupero della collezione: {e}")
        return jsonify({"error": "Errore nel recupero della collezione"}), 500



@app.route('/api/collection/stats', methods=['GET'])
@login_required
def get_collection_stats():
    """Restituisce statistiche della collezione dell'utente corrente."""
    try:
        total_value, set_values, set_counts = calculate_collection_stats(current_user.id)
        return jsonify({
            'total_value': total_value,
            'set_values': set_values,
            'set_counts': set_counts
        }), 200
    except Exception as e:
        print(f"Errore nel recupero delle statistiche: {e}")
        return jsonify({"error": "Errore nel recupero delle statistiche"}), 500


@app.route('/api/preferences/language', methods=['POST'])
@login_required
def set_language_preference():
    """Imposta la lingua preferita dell'utente."""
    data = request.json
    language = data.get('language', 'en')
    
    # Valida la lingua (solo italiano e inglese supportati per i prezzi)
    valid_languages = ['', 'en', 'it']
    if language not in valid_languages:
        return jsonify({"error": "Lingua non valida"}), 400

    
    try:
        prefs = UserPreferences.query.filter_by(user_id=current_user.id).first()
        if prefs:
            prefs.preferred_language = language if language else 'en'
        else:
            prefs = UserPreferences(
                user_id=current_user.id,
                preferred_language=language if language else 'en'
            )
            db.session.add(prefs)
        
        db.session.commit()
        print(f"[API] Lingua aggiornata per user {current_user.id}: {language}")
        return jsonify({"message": "Lingua aggiornata", "language": language}), 200
    except Exception as e:
        db.session.rollback()
        print(f"[API] Errore nell'aggiornamento lingua: {e}")
        return jsonify({"error": "Errore nell'aggiornamento"}), 500


def is_admin_user():
    """Verifica se l'utente corrente è un amministratore."""
    return current_user.is_authenticated and getattr(current_user, 'is_admin', False)


@app.route('/api/admin/card/price', methods=['POST'])
@login_required
def admin_set_card_price():
    """Imposta manualmente il prezzo di una carta (solo amministratori).
    Aggiorna la price_cache e tutte le carte in collezione con questo card_id.
    Il prezzo è specifico per lingua."""
    if not is_admin_user():
        return jsonify({"error": "Accesso negato: servono privilegi di amministratore"}), 403
    
    data = request.json
    if not data or 'card_id' not in data or 'price' not in data:
        return jsonify({"error": "Dati mancanti"}), 400
    
    card_id = data.get('card_id', '').strip()
    if not card_id:
        return jsonify({"error": "ID carta non valido"}), 400
    
    # Lingua della carta (default 'en')
    language = data.get('language', 'en')
    if language not in ('it', 'en'):
        language = 'en'
    
    # Validazione prezzo (0 = rimuovi prezzo manuale)
    try:
        new_price = float(data.get('price', 0))
        if new_price < 0:
            return jsonify({"error": "Il prezzo non può essere negativo"}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "Prezzo non valido"}), 400
    
    card_name = data.get('name', 'Carta')
    set_name = data.get('set_id', '')
    
    try:
        # Aggiorna la price_cache
        cached = PriceCache.query.filter_by(card_id=card_id, language=language).first()
        if cached:
            cached.price = new_price
            cached.source = 'manual'
            cached.scraped_at = db.func.now()
            cached.pending = False
        else:
            cached = PriceCache(
                card_id=card_id,
                card_name=card_name,
                set_name=set_name,
                language=language,
                price=new_price,
                url=None,
                source='manual',
                pending=False
            )
            db.session.add(cached)
        
        # Aggiorna tutte le carte in collezione con questo card_id e lingua
        collected = CollectedCard.query.filter_by(api_card_id=card_id, language=language).all()
        for cc in collected:
            cc.price = new_price
            cc.price_updated_at = datetime.utcnow()
            cc.price_source = 'manual'
        
        db.session.commit()
        
        # Invalida la cache in memoria per questo set+lingua, così la prossima
        # volta che si apre il set il prezzo manuale viene mostrato subito.
        # La cache è chiave "set_id:lingua".
        if set_name:
            cache_key = f"{set_name}:{language}"
            if cache_key in set_cards_cache:
                del set_cards_cache[cache_key]
                print(f"[ADMIN] Cache invalidata per {cache_key}")
        
        print(f"[ADMIN] Prezzo impostato per {card_id} ({language}): €{new_price}")
        return jsonify({
            "message": "Prezzo aggiornato con successo",
            "new_price": new_price,
            "updated_collection": len(collected)
        }), 200
    except Exception as e:
        db.session.rollback()
        print(f"[ADMIN] Errore nell'impostazione del prezzo: {e}")
        return jsonify({"error": "Errore nell'aggiornamento"}), 500



@app.route('/api/admin/users', methods=['GET'])
@login_required
def admin_list_users():
    """Elenca tutti gli utenti (solo amministratori)."""
    if not is_admin_user():
        return jsonify({"error": "Accesso negato: servono privilegi di amministratore"}), 403
    
    users = User.query.all()
    return jsonify([u.to_dict() for u in users]), 200


@app.route('/api/admin/users/<int:user_id>/admin', methods=['POST'])
@login_required
def admin_toggle_user(user_id):
    """Imposta o rimuove lo stato di amministratore di un utente (solo amministratori)."""
    if not is_admin_user():
        return jsonify({"error": "Accesso negato: servono privilegi di amministratore"}), 403
    
    data = request.json or {}
    is_admin = bool(data.get('is_admin', False))
    
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "Utente non trovato"}), 404
    
    # Impedisci di rimuovere l'admin a se stessi (per evitare di rimanere senza admin)
    if user.id == current_user.id and not is_admin:
        return jsonify({"error": "Non puoi rimuovere i privilegi di amministratore a te stesso"}), 400
    
    try:
        user.is_admin = is_admin
        db.session.commit()
        print(f"[ADMIN] Utente {user.email} {'promosso a' if is_admin else 'rimosso da'} amministratore")
        return jsonify({"message": "Stato aggiornato", "is_admin": is_admin}), 200
    except Exception as e:
        db.session.rollback()
        print(f"[ADMIN] Errore nell'aggiornamento utente: {e}")
        return jsonify({"error": "Errore nell'aggiornamento"}), 500


def preload_popular_sets():
    """Pre-carica in cache i set più recenti per velocizzare il primo accesso.
    Pre-carica sia in inglese che in italiano (le due lingue supportate per i prezzi).
    Continua a pre-caricare in background finché non ha coperto tutti i set."""

    with app.app_context():
        print("[CACHE] Pre-caricamento set popolari...")
        sets = get_all_sets()
        if not sets:
            print("[CACHE] Nessun set disponibile per il pre-caricamento")
            return
        
        # Pre-carica i primi 10 set più recenti in entrambe le lingue
        languages = ['en', 'it']
        preloaded = 0
        for i, set_data in enumerate(sets[:10]):
            set_id = set_data.get('id')
            if not set_id:
                continue
            for lang in languages:
                cache_key = f"{set_id}:{lang}"
                if cache_key in set_cards_cache:
                    continue
                print(f"[CACHE] Pre-caricamento set {i+1}/10 ({lang}): {set_data.get('name')}")
                raw_cards = fetch_all_cards(f"set.id:{set_id}")
                if raw_cards:
                    cards = sort_by_number([format_card(c, language=lang) for c in raw_cards])
                    set_cards_cache[cache_key] = cards
                    preloaded += 1
                # Piccola pausa per evitare rate limit
                time.sleep(0.5)
        
        print(f"[CACHE] Pre-caricamento completato: {preloaded} set in cache")




if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        
        # Pre-carica i set popolari in un thread separato per non bloccare l'avvio
        import threading
        preload_thread = threading.Thread(target=preload_popular_sets, daemon=True)
        preload_thread.start()
    
    # Avvia il daemon di aggiornamento prezzi (dopo l'app context)
    start_price_updater(app)
    
    # In produzione NON usare questo file direttamente:
    # usa il server WSGI (es. wsgi.py su PythonAnywhere, o gunicorn/waitress).
    # Il debug è attivo solo se FLASK_DEBUG=1 (sviluppo locale).
    debug_mode = os.environ.get('FLASK_DEBUG', '0').lower() in ('1', 'true', 'yes')

    # Host/porta configurabili da .env:
    # 127.0.0.1 = raggiungibile solo da questo PC
    # 0.0.0.0   = raggiungibile anche dallo smartphone nella stessa rete Wi-Fi
    host = os.environ.get('FLASK_HOST', '127.0.0.1')
    try:
        port = int(os.environ.get('FLASK_PORT', '5000'))
    except ValueError:
        port = 5000

    if host == '0.0.0.0':
        print(f"[SERVER] In ascolto sulla rete locale (porta {port}): apri http://<IP-del-PC>:{port} dallo smartphone")
    else:
        print(f"[SERVER] In ascolto solo su locale: http://127.0.0.1:{port}")

    app.run(host=host, port=port, debug=debug_mode, threaded=True)
