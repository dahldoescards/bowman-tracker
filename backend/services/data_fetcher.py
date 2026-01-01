"""
Data Fetcher Service for 2025 Bowman Draft Box Tracker.

Fetches sales data from 130point.com using proxy rotation.
Integrates with the BoxVsPlayerClassifier to filter out player card sales.
"""

import os
import sys
import random
import pickle
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
ENDPOINT = "https://back.130point.com/cards/"
MAX_RETRIES = 5
REQUEST_TIMEOUT = 30

# Search queries for each variant
SEARCH_QUERIES = [
    "2025 Bowman Draft Hobby",
    "2025 Bowman Draft Jumbo", 
    "2025 Bowman Draft Delight",
]

# Path configurations
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROXY_FILE = os.environ.get('PROXY_FILE', os.path.join(os.path.dirname(BASE_DIR), 'proxies.txt'))
CLASSIFIER_PATH = os.environ.get('CLASSIFIER_PATH', os.path.join(BASE_DIR, 'models', 'player_vs_box_classifier_combined.pkl'))

# Set USE_PROXIES=false in production to disable proxy usage
USE_PROXIES = os.environ.get('USE_PROXIES', 'true').lower() == 'true'


class ProxyManager:
    """Manages proxy rotation for requests."""
    
    def __init__(self, proxy_file: str = None):
        self.proxies: List[Dict] = []
        self.failed_proxies: set = set()
        
        if proxy_file and os.path.exists(proxy_file):
            self.load_proxies(proxy_file)
    
    def load_proxies(self, proxy_file: str) -> int:
        """
        Load proxies from file. 
        Format: host:port:username:password
        """
        try:
            with open(proxy_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        parts = line.split(':')
                        if len(parts) == 4:
                            self.proxies.append({
                                'host': parts[0],
                                'port': parts[1],
                                'username': parts[2],
                                'password': parts[3]
                            })
            logger.info(f"Loaded {len(self.proxies)} proxies")
            return len(self.proxies)
        except Exception as e:
            logger.error(f"Error loading proxies: {e}")
            return 0
    
    def get_random_proxy(self) -> Optional[Dict]:
        """Get a random proxy that hasn't failed."""
        available = [p for p in self.proxies if self._proxy_key(p) not in self.failed_proxies]
        if not available:
            # Reset failed proxies if all have failed
            self.failed_proxies.clear()
            available = self.proxies
        
        return random.choice(available) if available else None
    
    def mark_failed(self, proxy: Dict):
        """Mark a proxy as failed."""
        self.failed_proxies.add(self._proxy_key(proxy))
    
    def _proxy_key(self, proxy: Dict) -> str:
        return f"{proxy['host']}:{proxy['port']}"
    
    def get_proxy_url(self, proxy: Dict) -> str:
        """Convert proxy dict to URL format."""
        return f"http://{proxy['username']}:{proxy['password']}@{proxy['host']}:{proxy['port']}"


class BoxVsPlayerClassifier:
    """
    Classifier to distinguish box/case sales from player card sales.
    This is a copy of the classifier class to avoid import issues.
    """
    
    def __init__(self, model, vectorizer):
        self.model = model
        self.vectorizer = vectorizer
    
    def extract_box_features(self, titles):
        """Extract explicit features indicating box/case sales."""
        import numpy as np
        features = []
        
        box_keywords = [
            'box', 'case', 'factory sealed', 'sealed', 'hobby', 'jumbo', 
            'breaker delight', 'pre sale', 'presale', 'factory', '12ct', 
            '6 box', '8 box', 'super jumbo'
        ]
        
        for title in titles:
            title_lower = title.lower()
            feature_vec = []
            
            box_count = sum(1 for keyword in box_keywords if keyword in title_lower)
            feature_vec.append(box_count)
            
            feature_vec.append(1 if 'factory sealed' in title_lower else 0)
            feature_vec.append(1 if 'hobby case' in title_lower else 0)
            feature_vec.append(1 if 'hobby box' in title_lower else 0)
            feature_vec.append(1 if 'super jumbo' in title_lower else 0)
            feature_vec.append(1 if 'breaker delight' in title_lower else 0)
            feature_vec.append(1 if 'sealed' in title_lower else 0)
            feature_vec.append(1 if 'box' in title_lower and 'case' in title_lower else 0)
            
            player_keywords = ['auto', 'autograph', '1st', 'prospect', 'refractor', 
                              'chrome', 'psa', 'graded', '/', '#']
            player_count = sum(1 for keyword in player_keywords if keyword in title_lower)
            feature_vec.append(player_count)
            
            feature_vec.append(len(title))
            feature_vec.append(len(title.split()))
            
            features.append(feature_vec)
        
        return features
    
    def predict(self, titles) -> List[int]:
        """Predict box sale (1) or player sale (0) for given titles."""
        import numpy as np
        
        if isinstance(titles, str):
            titles = [titles]
        
        X_tfidf = self.vectorizer.transform(titles).toarray()
        X_explicit = np.array(self.extract_box_features(titles))
        X_combined = np.hstack([X_tfidf, X_explicit])
        
        return self.model.predict(X_combined)
    
    def is_box_sale(self, title: str) -> bool:
        """Check if a title represents a box sale."""
        return self.predict([title])[0] == 1


def load_classifier(classifier_path: str = None):
    """Load the trained classifier model."""
    path = classifier_path or CLASSIFIER_PATH
    
    if not os.path.exists(path):
        logger.warning(f"Classifier not found at {path}. Using rule-based fallback.")
        return None
    
    try:
        # Custom unpickler to remap the old classifier_class module
        import types
        import sys
        
        # Create a fake module for the old import
        fake_module = types.ModuleType('classifier_class')
        fake_module.BoxVsPlayerClassifier = BoxVsPlayerClassifier
        sys.modules['classifier_class'] = fake_module
        
        with open(path, 'rb') as f:
            loaded_obj = pickle.load(f)
        
        # The loaded object should have model and vectorizer attributes
        if hasattr(loaded_obj, 'model') and hasattr(loaded_obj, 'vectorizer'):
            classifier = BoxVsPlayerClassifier(loaded_obj.model, loaded_obj.vectorizer)
            logger.info("Classifier loaded successfully")
            return classifier
        else:
            logger.warning("Loaded object doesn't have expected attributes")
            return None
            
    except Exception as e:
        logger.error(f"Error loading classifier: {e}")
        return None


def is_box_sale_fallback(title: str) -> bool:
    """
    Fallback rule-based check for box sales when classifier is not available.
    More conservative - requires strong box indicators.
    """
    title_lower = title.lower()
    
    # Strong box indicators
    box_indicators = ['hobby box', 'jumbo box', 'breaker', 'factory sealed', 
                      'sealed box', 'case', 'hobby case', 'jumbo case']
    
    # Strong player card indicators (exclusions)
    player_indicators = ['auto', 'autograph', '/99', '/50', '/25', '/10', '/5', '/1',
                        'refractor', 'psa', 'bgs', 'sgc', 'graded', 'rookie', 'rc',
                        'parallel', 'insert', 'numbered', '1st bowman']
    
    has_box_indicator = any(ind in title_lower for ind in box_indicators)
    has_player_indicator = any(ind in title_lower for ind in player_indicators)
    
    # Must have box indicator and not have player indicator
    return has_box_indicator and not has_player_indicator


def query_130point(query_term: str, proxy_manager: ProxyManager) -> Optional[str]:
    """Query 130point endpoint with optional proxy rotation."""
    
    for attempt in range(MAX_RETRIES):
        # Only use proxies if enabled and available
        proxy = None
        if USE_PROXIES:
            proxy = proxy_manager.get_random_proxy()
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        data = {'query': query_term}
        
        proxies = None
        if proxy:
            proxy_url = proxy_manager.get_proxy_url(proxy)
            proxies = {'http': proxy_url, 'https': proxy_url}
            logger.debug(f"Attempt {attempt + 1}/{MAX_RETRIES}: Using proxy {proxy['host']}")
        else:
            logger.debug(f"Attempt {attempt + 1}/{MAX_RETRIES}: Direct connection")
        
        try:
            response = requests.post(
                ENDPOINT,
                headers=headers,
                data=data,
                proxies=proxies,
                timeout=REQUEST_TIMEOUT
            )
            
            if response.status_code == 200:
                logger.info(f"Successfully fetched data for '{query_term}' ({len(response.text)} chars)")
                return response.text
            else:
                logger.warning(f"HTTP {response.status_code} for '{query_term}'")
                if proxy:
                    proxy_manager.mark_failed(proxy)
                    
        except Exception as e:
            logger.warning(f"Request failed: {e}")
            if proxy:
                proxy_manager.mark_failed(proxy)
    
    logger.error(f"All attempts failed for '{query_term}'")
    return None


def parse_130point_response(html_content: str) -> List[Dict]:
    """Parse HTML response to extract listing data."""
    soup = BeautifulSoup(html_content, 'html.parser')
    results = []
    
    # Find all data rows
    rows = soup.find_all('tr', id='dRow')
    logger.debug(f"Found {len(rows)} listing rows")
    
    for row in rows:
        result = {
            'title': '',
            'url': '',
            'price': 0.0,
            'date': ''
        }
        
        # Extract price from data-price attribute
        price_attr = row.get('data-price')
        if price_attr:
            try:
                result['price'] = float(price_attr)
            except (ValueError, TypeError):
                continue
        
        # Extract title and URL
        title_span = row.find('span', id='titleText')
        if title_span:
            link = title_span.find('a', href=True)
            if link:
                result['url'] = link.get('href', '')
                result['title'] = link.get_text(strip=True)
        
        # Extract sale date - try multiple methods
        result['date'] = ''
        row_html = str(row)
        
        # Method 1: Check for data-date attribute on the row
        date_attr = row.get('data-date')
        if date_attr:
            result['date'] = date_attr.strip()
        
        # Method 2: Look for dateSpan class
        if not result['date']:
            date_elem = row.find('span', class_='dateSpan')
            if date_elem:
                result['date'] = date_elem.get_text(strip=True)
        
        # Method 3: Look for "Date:</b>" pattern (from original 130point code)
        if not result['date']:
            import re
            date_bold_match = re.search(r'Date:</b>\s*([^<]+)', row_html, re.IGNORECASE)
            if date_bold_match:
                result['date'] = date_bold_match.group(1).strip()
        
        # Method 4: Look for "Date:" in various formats
        if not result['date']:
            import re
            date_patterns = [
                r'Date:\s*</b>\s*([^<]+)',  # Date: </b> followed by text
                r'>Date:\s*([^<]+)<',        # >Date: text<
                r'Date:\s*(\d{1,2}/\d{1,2}/\d{2,4})',  # Date: MM/DD/YYYY
                r'Sold:\s*(\d{1,2}/\d{1,2}/\d{2,4})',  # Sold: MM/DD/YYYY
                r'>(\d{1,2}/\d{1,2}/\d{4})<',          # >MM/DD/YYYY<
                r'>(\d{1,2}/\d{1,2}/\d{2})<',          # >MM/DD/YY<
                r'(\d{1,2}/\d{1,2}/\d{4})',            # MM/DD/YYYY anywhere
                r'(\d{4}-\d{2}-\d{2})',                # YYYY-MM-DD anywhere
                r'([A-Z][a-z]{2}\s+\d{1,2},?\s+\d{4})', # Dec 25, 2025 format
            ]
            for pattern in date_patterns:
                match = re.search(pattern, row_html, re.IGNORECASE)
                if match:
                    result['date'] = match.group(1).strip()
                    break
        
        # Method 5: Look in any td/span for date-like content
        if not result['date']:
            import re
            all_spans = row.find_all(['td', 'span', 'div'])
            for elem in all_spans:
                text = elem.get_text(strip=True)
                # Check for date patterns in text
                date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{2,4})', text)
                if date_match:
                    result['date'] = date_match.group(1)
                    break
        
        # Method 6 (last resort): Default to today only if absolutely nothing found
        if not result['date'] and result['title'] and result['price'] > 0:
            from datetime import datetime
            result['date'] = datetime.now().strftime('%m/%d/%Y')
        
        # Only add if we have essential fields
        if result['title'] and result['url'] and result['price'] > 0:
            results.append(result)
    
    return results


def fetch_all_queries(proxy_manager: ProxyManager, classifier = None) -> Tuple[List[Dict], Dict]:
    """
    Fetch data for all search queries and return combined results.
    
    Returns:
        Tuple of (filtered_results, stats)
    """
    from services.title_parser import parse_listing
    
    all_results = []
    stats = {
        'total_fetched': 0,
        'box_sales': 0,
        'player_sales_filtered': 0,
        'errors': []
    }
    
    for query in SEARCH_QUERIES:
        logger.info(f"Fetching: {query}")
        
        try:
            html = query_130point(query, proxy_manager)
            
            if html:
                raw_results = parse_130point_response(html)
                stats['total_fetched'] += len(raw_results)
                
                for raw in raw_results:
                    # Check if it's a box sale
                    is_box = False
                    if classifier:
                        is_box = classifier.is_box_sale(raw['title'])
                    else:
                        is_box = is_box_sale_fallback(raw['title'])
                    
                    if is_box:
                        # Parse the listing to extract all fields
                        parsed = parse_listing(
                            raw['title'],
                            raw['url'],
                            raw['price'],
                            raw['date']
                        )
                        all_results.append(parsed)
                        stats['box_sales'] += 1
                    else:
                        stats['player_sales_filtered'] += 1
                        logger.debug(f"Filtered player sale: {raw['title'][:50]}...")
            else:
                stats['errors'].append(f"Failed to fetch: {query}")
                
        except Exception as e:
            logger.error(f"Error processing {query}: {e}")
            stats['errors'].append(f"{query}: {str(e)}")
    
    logger.info(f"Fetch complete: {stats['box_sales']} box sales, {stats['player_sales_filtered']} filtered")
    return all_results, stats


if __name__ == '__main__':
    # Test the fetcher
    proxy_manager = ProxyManager(PROXY_FILE)
    classifier = load_classifier()
    
    results, stats = fetch_all_queries(proxy_manager, classifier)
    
    print(f"\n{'='*60}")
    print(f"Fetch Results:")
    print(f"  Total fetched: {stats['total_fetched']}")
    print(f"  Box sales: {stats['box_sales']}")
    print(f"  Player sales filtered: {stats['player_sales_filtered']}")
    
    if results:
        print(f"\nSample results:")
        for r in results[:5]:
            print(f"  {r['variant_type']}: ${r['per_box_price']:.2f}/box - {r['title'][:50]}...")
