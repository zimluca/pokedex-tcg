import time
import re
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup

# Rate limiting per evitare ban
SCRAPE_DELAY = 2.5  # secondi tra una richiesta e l'altra
last_scrape_time = 0


def rate_limit():
    """Implementa rate limiting per lo scraping."""
    global last_scrape_time
    current_time = time.time()
    time_since_last = current_time - last_scrape_time
    
    if time_since_last < SCRAPE_DELAY:
        time.sleep(SCRAPE_DELAY - time_since_last)
    
    last_scrape_time = time.time()


def scrape_cardmarket_price(card_name, set_name):
    """Scraping del prezzo da Cardmarket come ultimo fallback.
    Restituisce (prezzo, url) o (0.0, None) se fallisce.
    
    ATTENZIONE: Usa con parsimonia, solo per carte senza prezzo API.
    """
    try:
        rate_limit()
        
        # Costruisci query di ricerca
        search_query = f"{card_name} {set_name}".strip()
        encoded_query = quote(search_query)
        search_url = f"https://www.cardmarket.com/en/Pokemon/Products/Search?searchString={encoded_query}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        }
        
        response = requests.get(search_url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            print(f"[SCRAPER] Errore HTTP {response.status_code} per '{card_name}'")
            return 0.0, None
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Cerca il primo risultato con prezzo
        # Cardmarket usa diverse strutture, cerchiamo pattern comuni
        price_patterns = [
            {'class': 'price-tag'},
            {'class': 'product-price'},
            {'class': 'font-weight-bold text-right'},
        ]
        
        for pattern in price_patterns:
            price_elements = soup.find_all('span', pattern)
            for elem in price_elements:
                price_text = elem.get_text(strip=True)
                # Estrai numero dal testo (es: "€1.50" -> 1.50)
                match = re.search(r'[\d,\.]+', price_text.replace(',', '.'))
                if match:
                    try:
                        price = float(match.group())
                        if price > 0:
                            print(f"[SCRAPER] Prezzo trovato per '{card_name}': €{price:.2f}")
                            return price, search_url
                    except ValueError:
                        continue
        
        print(f"[SCRAPER] Nessun prezzo trovato per '{card_name}'")
        return 0.0, search_url
        
    except requests.exceptions.RequestException as e:
        print(f"[SCRAPER] Errore di connessione: {e}")
        return 0.0, None
    except Exception as e:
        print(f"[SCRAPER] Errore imprevisto: {e}")
        return 0.0, None


def scrape_tcgplayer_price(card_name, set_name):
    """Scraping del prezzo da TCGPlayer come fallback alternativo.
    Restituisce (prezzo, url) o (0.0, None) se fallisce.
    
    NOTA: TCGPlayer ha protezioni anti-bot più aggressive.
    """
    try:
        rate_limit()
        
        # TCGPlayer richiede ricerca più specifica
        search_query = f"{card_name} {set_name}".strip()
        encoded_query = quote(search_query)
        search_url = f"https://www.tcgplayer.com/search/pokemon/product?productLineName=pokemon&q={encoded_query}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        }
        
        response = requests.get(search_url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            print(f"[SCRAPER] TCGPlayer HTTP {response.status_code} per '{card_name}'")
            return 0.0, None
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # TCGPlayer usa strutture diverse, pattern comuni
        price_patterns = [
            {'class': 'product-card__market-price'},
            {'class': 'spotlight__price'},
            {'class': 'product__market-price'},
        ]
        
        for pattern in price_patterns:
            price_elements = soup.find_all('span', pattern)
            for elem in price_elements:
                price_text = elem.get_text(strip=True)
                # Estrai numero (es: "$1.50" -> 1.50)
                match = re.search(r'[\d,\.]+', price_text.replace(',', ''))
                if match:
                    try:
                        price = float(match.group())
                        if price > 0:
                            print(f"[SCRAPER] TCGPlayer prezzo per '{card_name}': ${price:.2f}")
                            return price, search_url
                    except ValueError:
                        continue
        
        print(f"[SCRAPER] TCGPlayer nessun prezzo per '{card_name}'")
        return 0.0, search_url
        
    except requests.exceptions.RequestException as e:
        print(f"[SCRAPER] TCGPlayer errore connessione: {e}")
        return 0.0, None
    except Exception as e:
        print(f"[SCRAPER] TCGPlayer errore: {e}")
        return 0.0, None
