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


def scrape_ebay_price(card_name, set_name):
    """Scraping del prezzo medio da eBay basato sugli articoli venduti di recente.
    Restituisce (prezzo, url) o (0.0, None) se fallisce.
    
    eBay è ottimo per prezzi reali di mercato basati su vendite effettive.
    """
    try:
        rate_limit()
        
        # Costruisci query di ricerca per carte Pokémon
        search_query = f"pokemon {card_name} {set_name}".strip()
        encoded_query = quote(search_query)
        
        # Cerca articoli venduti (LH_Sold=1) e completati (LH_Complete=1)
        # Categoria 183454 = Pokémon Trading Card Game
        search_url = (
            f"https://www.ebay.com/sch/i.html?"
            f"_nkw={encoded_query}&"
            f"_sacat=183454&"  # Categoria Pokémon TCG
            f"LH_Sold=1&"      # Solo venduti
            f"LH_Complete=1&"  # Solo completati
            f"_sop=13"         # Ordina per: più recenti
        )
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        }
        
        response = requests.get(search_url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            print(f"[SCRAPER] eBay HTTP {response.status_code} per '{card_name}'")
            return 0.0, None
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # eBay usa diverse strutture per i prezzi
        prices = []
        
        # Pattern 1: s-item__price (nuovo layout)
        price_elements = soup.find_all('span', class_='s-item__price')
        for elem in price_elements:
            price_text = elem.get_text(strip=True)
            # Gestisci range di prezzi (es: "EUR 1,50 a EUR 3,00")
            if 'a' in price_text or 'to' in price_text:
                # Prendi il primo prezzo del range
                price_text = price_text.split('a')[0].split('to')[0]
            
            # Estrai numero (supporta sia . che , come separatore decimale)
            # Rimuovi simboli di valuta e spazi
            clean_text = re.sub(r'[^\d,\.]', '', price_text)
            clean_text = clean_text.replace(',', '.')
            
            match = re.search(r'\d+\.?\d*', clean_text)
            if match:
                try:
                    price = float(match.group())
                    if 0.1 < price < 10000:  # Filtro prezzi ragionevoli
                        prices.append(price)
                except ValueError:
                    continue
        
        # Pattern 2: lvprice (vecchio layout)
        if not prices:
            price_elements = soup.find_all('span', class_='lvprice')
            for elem in price_elements:
                price_text = elem.get_text(strip=True)
                clean_text = re.sub(r'[^\d,\.]', '', price_text)
                clean_text = clean_text.replace(',', '.')
                
                match = re.search(r'\d+\.?\d*', clean_text)
                if match:
                    try:
                        price = float(match.group())
                        if 0.1 < price < 10000:
                            prices.append(price)
                    except ValueError:
                        continue
        
        if prices:
            # Calcola la mediana dei prezzi venduti (più affidabile della media)
            prices.sort()
            median_price = prices[len(prices) // 2]
            
            # Se ci sono abbastanza dati, calcola la media dei prezzi centrali (esclude outlier)
            if len(prices) >= 5:
                # Prendi il 50% centrale dei prezzi
                start_idx = len(prices) // 4
                end_idx = 3 * len(prices) // 4
                central_prices = prices[start_idx:end_idx]
                avg_price = sum(central_prices) / len(central_prices)
            else:
                avg_price = median_price
            
            print(f"[SCRAPER] eBay prezzo medio per '{card_name}': €{avg_price:.2f} (da {len(prices)} vendite)")
            return round(avg_price, 2), search_url
        
        print(f"[SCRAPER] eBay nessun prezzo trovato per '{card_name}'")
        return 0.0, search_url
        
    except requests.exceptions.RequestException as e:
        print(f"[SCRAPER] eBay errore connessione: {e}")
        return 0.0, None
    except Exception as e:
        print(f"[SCRAPER] eBay errore imprevisto: {e}")
        import traceback
        traceback.print_exc()
        return 0.0, None
