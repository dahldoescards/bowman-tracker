"""
Title Parser for 2025 Bowman Draft Box Listings.

Parses eBay listing titles to extract:
- Variant type (Jumbo, Breaker's Delight, Hobby/Regular)
- Box count (single box, 6-box case, 8-box case, etc.)
- Case type indicators

Handles various title formats found in eBay listings.
"""

import re
from typing import Tuple, Optional

# Variant detection patterns (order matters - more specific first)
VARIANT_PATTERNS = {
    'jumbo': [
        r'\bjumbo\b',
        r'\bsuper\s*jumbo\b',
        r'\bjmbo\b',  # Common typo
    ],
    'breakers_delight': [
        r"breaker'?s?\s*delight",
        r'\bbd\s*box\b',
        r'\bbreakers\s*d\b',
        r'\bb\.?d\.?\s*hobby\b',
    ],
    'hobby': [
        r'\bhobby\b(?!\s*jumbo)',  # "hobby" but not "hobby jumbo"
        r'\bregular\b',
        r'\bstandard\b',
    ]
}

# Box count extraction patterns
BOX_COUNT_PATTERNS = [
    # Case patterns: "6 box case", "8-box case", "case of 6", etc.
    (r'(\d+)\s*[-\s]?box\s*case', 'case'),
    (r'case\s*(?:of\s*)?(\d+)', 'case'),
    (r'(\d+)\s*[-\s]?ct\s*case', 'case'),
    
    # Lot patterns: "Lot of 2", "Lot of 3", etc.
    (r'lot\s*(?:of\s*)?(\d+)', 'multiple'),
    (r'(\d+)\s*lot', 'multiple'),
    
    # Multiple boxes: "2 boxes", "x3 boxes"
    (r'(\d+)\s*boxes', 'multiple'),
    (r'x\s*(\d+)\s*box', 'multiple'),
    (r'(\d+)\s*x\s*box', 'multiple'),
    
    # Specific case sizes (common configurations)
    (r'\b(6)\s*[-\s]?box\b', 'case'),  # 6-box (Hobby case)
    (r'\b(8)\s*[-\s]?box\b', 'case'),  # 8-box (Jumbo case)
    (r'\b(16)\s*[-\s]?box\b', 'case'), # 16-box (Breaker's Delight case)
    
    # Single box indicators (return 1)
    (r'\bsingle\s*box\b', 'single'),
    (r'\b1\s*box\b', 'single'),
]

# Known case configurations for Bowman Draft 2025
KNOWN_CASE_SIZES = {
    'hobby': 6,      # Hobby cases have 6 boxes
    'jumbo': 8,      # Jumbo cases have 8 boxes  
    'breakers_delight': 16,  # Breaker's Delight cases have 16 boxes
}


def detect_variant_type(title: str) -> str:
    """
    Detect the variant type from a listing title.
    Returns: 'jumbo', 'breakers_delight', or 'hobby'
    """
    title_lower = title.lower()
    
    # Check for Jumbo first (most distinctive)
    for pattern in VARIANT_PATTERNS['jumbo']:
        if re.search(pattern, title_lower, re.IGNORECASE):
            return 'jumbo'
    
    # Check for Breaker's Delight
    for pattern in VARIANT_PATTERNS['breakers_delight']:
        if re.search(pattern, title_lower, re.IGNORECASE):
            return 'breakers_delight'
    
    # Check for explicit Hobby mentions
    for pattern in VARIANT_PATTERNS['hobby']:
        if re.search(pattern, title_lower, re.IGNORECASE):
            return 'hobby'
    
    # Default to hobby if no specific variant found
    # (Most common box type)
    return 'hobby'


def extract_box_count(title: str, variant_type: str = None) -> int:
    """
    Extract the number of boxes from a listing title.
    
    Args:
        title: The listing title
        variant_type: If known, helps determine case size for "case" mentions
    
    Returns:
        Number of boxes in the listing (minimum 1)
    """
    title_lower = title.lower()
    
    # Check for explicit box counts first
    for pattern, count_type in BOX_COUNT_PATTERNS:
        match = re.search(pattern, title_lower, re.IGNORECASE)
        if match:
            if count_type == 'single':
                return 1
            
            try:
                count = int(match.group(1))
                if 1 <= count <= 100:  # Reasonable range check
                    return count
            except (ValueError, IndexError):
                continue
    
    # Check for "case" without explicit count - use known case sizes
    if re.search(r'\bcase\b', title_lower):
        if variant_type and variant_type in KNOWN_CASE_SIZES:
            return KNOWN_CASE_SIZES[variant_type]
        # If we know it's a case but don't know type, default to hobby case
        return 6
    
    # Default to single box
    return 1


def extract_ebay_item_id(url: str) -> Optional[str]:
    """
    Extract the eBay item ID from a URL.
    
    eBay URLs typically look like:
    - https://www.ebay.com/itm/123456789
    - https://www.ebay.com/itm/title-text/123456789
    
    Returns the item ID as a string, or None if not found.
    """
    if not url:
        return None
    
    # Pattern for eBay item IDs (usually 12 digits)
    match = re.search(r'ebay\.com/itm/(?:[^/]+/)?(\d+)', url)
    if match:
        return match.group(1)
    
    # Alternative pattern
    match = re.search(r'/itm/(\d+)', url)
    if match:
        return match.group(1)
    
    return None


def generate_unique_id(url: str, source: str = 'ebay') -> str:
    """
    Generate a unique identifier for a listing.
    
    For eBay: Uses the item ID
    For other sources: Uses a normalized URL hash
    """
    if source == 'ebay' or 'ebay.com' in url.lower():
        item_id = extract_ebay_item_id(url)
        if item_id:
            return f"ebay_{item_id}"
    
    # Fallback: hash the normalized URL
    import hashlib
    normalized_url = url.lower().strip().rstrip('/')
    url_hash = hashlib.md5(normalized_url.encode()).hexdigest()[:16]
    return f"{source}_{url_hash}"


def parse_listing(title: str, url: str, price: float, date_str: str) -> dict:
    """
    Parse a complete listing and return structured data.
    
    Args:
        title: Listing title
        url: Listing URL
        price: Total sale price
        date_str: Sale date string
    
    Returns:
        Dict with all extracted and calculated fields
    """
    # Detect variant type first (needed for case size inference)
    variant_type = detect_variant_type(title)
    
    # Extract box count
    box_count = extract_box_count(title, variant_type)
    
    # Calculate per-box price
    per_box_price = round(price / box_count, 2)
    
    # Generate unique ID
    unique_id = generate_unique_id(url)
    
    # Extract eBay item ID if applicable
    ebay_item_id = extract_ebay_item_id(url)
    
    # Determine source
    source = 'ebay' if 'ebay.com' in url.lower() else 'other'
    
    # Parse date to timestamp
    from datetime import datetime, timedelta, timezone
    sale_timestamp = 0
    sale_date = date_str
    
    # EST is UTC-5 hours
    EST_OFFSET = timedelta(hours=-5)
    EST = timezone(EST_OFFSET)
    UTC = timezone.utc
    
    try:
        # Handle various date formats from 130point
        # The primary format from 130point is: "Wed 31 Dec 2025 03:21:01 GMT"
        # These dates are in GMT/UTC and need to be converted to EST
        
        gmt_formats = [
            '%a %d %b %Y %H:%M:%S GMT',  # 130point format: "Wed 31 Dec 2025 03:21:01 GMT"
            '%a %d %b %Y %H:%M:%S %Z',   # With timezone
        ]
        
        local_formats = [
            '%a %d %b %Y',               # Short: "Wed 31 Dec 2025"
            '%d %b %Y',                  # "31 Dec 2025"
            '%m/%d/%Y',                  # US format: "12/31/2025"
            '%Y-%m-%d',                  # ISO format: "2025-12-31"
            '%b %d, %Y',                 # "Dec 31, 2025"
            '%B %d, %Y',                 # "December 31, 2025"
        ]
        
        parsed = False
        
        # First try GMT formats and convert to EST
        for fmt in gmt_formats:
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                # This is a GMT time - convert to EST
                dt_utc = dt.replace(tzinfo=UTC)
                dt_est = dt_utc.astimezone(EST)
                sale_timestamp = int(dt_est.timestamp())
                sale_date = dt_est.strftime('%Y-%m-%d')
                parsed = True
                break
            except ValueError:
                continue
        
        # Then try local formats (no conversion needed)
        if not parsed:
            for fmt in local_formats:
                try:
                    dt = datetime.strptime(date_str.strip(), fmt)
                    sale_timestamp = int(dt.timestamp())
                    sale_date = dt.strftime('%Y-%m-%d')
                    parsed = True
                    break
                except ValueError:
                    continue
                    
    except Exception:
        # If all parsing fails, use current date in EST
        dt = datetime.now(EST)
        sale_timestamp = int(dt.timestamp())
        sale_date = dt.strftime('%Y-%m-%d')
    
    return {
        'unique_id': unique_id,
        'source': source,
        'source_url': url,
        'ebay_item_id': ebay_item_id,
        'title': title,
        'sale_price': price,
        'box_count': box_count,
        'per_box_price': per_box_price,
        'variant_type': variant_type,
        'sale_date': sale_date,
        'sale_timestamp': sale_timestamp,
    }


def parse_price_string(price_str: str) -> float:
    """Parse a price string like '$1,299.99' to a float."""
    if not price_str:
        return 0.0
    
    # Remove currency symbols, commas, and whitespace
    cleaned = re.sub(r'[^\d.]', '', price_str)
    
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


# Test the parser
if __name__ == '__main__':
    # Test cases
    test_titles = [
        ("2025 Bowman Draft Jumbo Hobby Box Factory Sealed", 299.99, "12/30/2024"),
        ("2025 Bowman Draft Breaker's Delight Box Sealed", 449.99, "12/29/2024"),
        ("2025 Bowman Draft Hobby Box 6 Box Case", 1499.99, "12/28/2024"),
        ("2025 Bowman Draft Jumbo 8 Box Case Factory Sealed", 2199.99, "12/27/2024"),
        ("2025 Bowman Draft Super Jumbo Box", 599.99, "12/26/2024"),
        ("2025 Bowman Draft Hobby Box Single Box", 259.99, "12/25/2024"),
    ]
    
    print("Title Parser Test Results:")
    print("=" * 80)
    
    for title, price, date in test_titles:
        result = parse_listing(title, "https://www.ebay.com/itm/123456789", price, date)
        print(f"\nTitle: {title}")
        print(f"  Variant: {result['variant_type']}")
        print(f"  Box Count: {result['box_count']}")
        print(f"  Total Price: ${price:.2f}")
        print(f"  Per-Box Price: ${result['per_box_price']:.2f}")
        print(f"  Sale Date: {result['sale_date']}")
