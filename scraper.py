import cloudscraper
from bs4 import BeautifulSoup
import json
import pandas as pd
import os
import time
import html
import unicodedata
import re

# Initialize the Cloudflare Bypasser
scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
)

def standardize_text(text):
    """Converts HTML entities and accented characters into standard English alphabet."""
    if not text or text in ["N/A", "NAME NOT FOUND"]:
        return text
        
    text = html.unescape(text)
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    return text.strip()

def clean_categories(cat_string):
    """Applies standard formatting rules to a category string."""
    if not cat_string or cat_string in ["N/A", "NAME NOT FOUND"]:
        return cat_string
        
    cat_string = cat_string.replace('|', ',')
    raw_cats = [c.strip() for c in cat_string.split(',')]
    
    cleaned_cats = []
    for c in raw_cats:
        if not c: continue
        c = c.replace('-', ' ')
        c = re.sub(r'(?i)\bblu ray\b', 'blu-ray', c)
        c = re.sub(r'(?i)\be scooters\b', 'e-scooters', c)
        
        if c.lower() in ['tv', 'television']:
            c = 'televisions'
            
        if len(c) > 0:
            c = c[0].upper() + c[1:]
            
        cleaned_cats.append(c)
        
    unique_cats = list(dict.fromkeys(cleaned_cats))
    return ",".join(unique_cats)

def scrape_review_data(url):
    """Fetches the webpage and extracts the data using our multi-tier fallback logic."""
    try:
        response = scraper.get(url, timeout=15)
        if response.status_code != 200:
            return None, None, None, None, None, None
        soup = BeautifulSoup(response.text, 'html.parser')
        html_text = response.text
    except Exception as e:
        print(f"Error loading {url}: {e}")
        return None, None, None, None, None, None

    product_name = None
    rating = "N/A"
    dateline = "N/A"
    categories = "N/A"
    author = "N/A"
    cms_url = "N/A"

    # ==========================================
    # EXTRACT CMS ID FROM FEP_OBJECT
    # ==========================================
    fep_match = re.search(r'var\s+FEP_object[\s\S]*?"id"\s*:\s*"([^"]+)"', html_text)
    if fep_match:
        cms_id = fep_match.group(1)
        cms_url = f"https://proof.vanilla.tools/techradar/articles/edit/{cms_id}"

    # ==========================================
    # EXTRACT AUTHOR FROM DFP_CONFIG
    # ==========================================
    dfp_block = re.search(r'var\s+dfp_config\s*=\s*(\{[\s\S]*?\});', html_text)
    if dfp_block:
        author_match = re.search(r'"author"\s*:\s*"([^"]+)"', dfp_block.group(1))
        if author_match:
            author = author_match.group(1)

    # ==========================================
    # 1. EXTRACT RATING (Visual HTML Logic)
    # ==========================================
    rating_span = soup.find(attrs={'aria-label': lambda a: a and 'out of 5 stars' in a.lower()})
    if rating_span:
        aria_label = rating_span.get('aria-label').lower()
        words = aria_label.replace('rating:', '').split()
        if 'out' in words:
            try:
                out_index = words.index('out')
                base_num = float(words[out_index - 1])
                if rating_span.find(class_=lambda c: c and 'half' in c.lower()):
                    base_num += 0.5
                rating = str(base_num)
            except:
                pass

    # ==========================================
    # 2. EXTRACT PRODUCT NAME (5-Tier Waterfall)
    # ==========================================
    
    # NEW: Ignore list for streaming services that hijack Hawk widgets
    hawk_ignore_list = [
        "netflix", 
        "amazon prime video", 
        "paramount plus", 
        "peacock tv", 
        "hbo max"
    ]

    for attr in ['data-model-name', 'data-product-name', 'data-hawk-model', 'data-product']:
        element = soup.find(attrs={attr: True})
        if element and element.get(attr):
            temp_name = element.get(attr)
            # Only assign the name if it's NOT in our ignore list
            if temp_name.strip().lower() not in hawk_ignore_list:
                product_name = temp_name
                break

    if not product_name:
        for header in soup.find_all(['h1', 'h2', 'h3']):
            header_text = header.get_text(strip=True)
            lower_text = header_text.lower()
            if " review:" in lower_text:
                index = lower_text.find(" review:")
                product_name = header_text[:index].strip()
                break
            elif " review" in lower_text:
                index = lower_text.find(" review")
                product_name = header_text[:index].strip()
                break

    if not product_name:
        title_tag = soup.find('title')
        if title_tag and title_tag.string:
            meta_title = title_tag.string
            if " review" in meta_title.lower():
                index = meta_title.lower().find(" review")
                product_name = meta_title[:index].strip()
            elif ":" in meta_title:
                product_name = meta_title.split(":")[0].strip()

    if not product_name:
        th_name = soup.find(lambda tag: tag.name in ['th', 'td'] and tag.text.strip().lower() == 'name')
        if th_name:
            sibling = th_name.find_next_sibling(['td', 'th'])
            if sibling: product_name = sibling.text.strip()

    # ==========================================
    # 3. EXTRACT DATE & SCHEMA FALLBACKS
    # ==========================================
    schema_tags = soup.find_all('script', type='application/ld+json')
    for tag in schema_tags:
        try:
            data = json.loads(tag.string)
            if isinstance(data, dict): data = [data] 
            
            for item in data:
                if item.get('@type') in ['Review', 'Article', 'NewsArticle', 'WebPage']:
                    if author == "N/A" and 'author' in item:
                        if isinstance(item['author'], list) and len(item['author']) > 0:
                            author = item['author'][0].get('name', 'N/A')
                        elif isinstance(item['author'], dict):
                            author = item['author'].get('name', 'N/A')
                    
                    if dateline == "N/A" and 'datePublished' in item:
                        dateline = item.get('datePublished', 'N/A')[:10]
                        
                    if item.get('@type') == 'Review':
                        if rating == "N/A" and 'reviewRating' in item:
                            rating = str(item['reviewRating'].get('ratingValue', 'N/A'))
                        if not product_name and 'itemReviewed' in item:
                            product_name = item['itemReviewed'].get('name')
        except:
            pass 

    # Author Fallback (HTML Meta Tags)
    if author == "N/A":
        author_meta = soup.find('meta', attrs={'name': ['author', 'parsely-author']})
        if author_meta and author_meta.get('content'):
            author = author_meta.get('content')

    # Date Fallback (HTML Meta Tags)
    if dateline == "N/A":
        date_meta = soup.find('meta', attrs={'property': 'article:published_time'})
        if date_meta and date_meta.get('content'):
            dateline = date_meta.get('content')[:10]

    # Name Safety Cleanup
    if not product_name: 
        product_name = "NAME NOT FOUND"
    elif " review:" in product_name.lower():
        index = product_name.lower().find(" review:")
        product_name = product_name[:index].strip()

    product_name = standardize_text(product_name)
    if len(product_name) > 50 and not product_name.startswith("[FLAG]"):
        product_name = f"[FLAG] {product_name}"

    author = standardize_text(author)

    # ==========================================
    # 4. EXTRACT CATEGORIES
    # ==========================================
    section_tags = soup.find_all('meta', property=lambda x: x and x in ['article:section', 'article:tag'])
    if section_tags:
        categories = ", ".join([tag.get('content') for tag in section_tags if tag.get('content')])
    else:
        keywords_meta = soup.find('meta', attrs={'name': 'keywords'})
        if keywords_meta and keywords_meta.get('content'):
            categories = keywords_meta.get('content')

    categories = standardize_text(categories)
    categories = clean_categories(categories)

    return product_name, rating, dateline, categories, cms_url, author

def get_links_from_feed(page_number):
    """Scrapes a specific page of the TechRadar reviews feed for article URLs."""
    if page_number == 1:
        url = "https://www.techradar.com/reviews"
    else:
        url = f"https://www.techradar.com/reviews/page/{page_number}"
        
    print(f"Scanning feed page {page_number}: {url}")
    
    try:
        response = scraper.get(url, timeout=15)
        if response.status_code != 200:
            return []
            
        soup = BeautifulSoup(response.text, 'html.parser')
        page_links = []
        
        article_tags = soup.find_all('a', class_='article-link')
        for tag in article_tags:
            link = tag.get('href')
            if link and not link.startswith('http'):
                link = "https://www.techradar.com" + link
            if link not in page_links:
                page_links.append(link)
                
        return page_links
    except Exception as e:
        print(f"Error scraping feed page: {e}")
        return []

def main():
    print("Starting TechRadar Daily Scraper...")
    
    new_reviews_data = []
    pages_to_scrape = 3 
    all_urls_to_scrape = []

    for page in range(1, pages_to_scrape + 1):
        links = get_links_from_feed(page)
        all_urls_to_scrape.extend(links)
        time.sleep(2) 
        
    print(f"Found {len(all_urls_to_scrape)} total review URLs in the feed.")

    for url in all_urls_to_scrape:
        print(f"Scraping data from: {url}")
        name, rating, date, cats, cms_link, author_name = scrape_review_data(url)
        
        if name and name != "NAME NOT FOUND":
            new_reviews_data.append({
                'Product': name,
                'Rating': rating,
                'Dateline': date,
                'Author': author_name,
                'Categories': cats,
                'CMS_URL': cms_link,
                'URL': url
            })
        time.sleep(1)

    if not new_reviews_data:
        print("No new reviews scraped successfully. Exiting.")
        return

    new_df = pd.DataFrame(new_reviews_data)
    json_filename = 'data.json'
    
    if os.path.exists(json_filename):
        print("Found existing data.json. Merging and deduplicating...")
        try:
            existing_df = pd.read_json(json_filename)
            if 'Author' not in existing_df.columns:
                existing_df['Author'] = "N/A"
            if 'CMS_URL' not in existing_df.columns:
                existing_df['CMS_URL'] = "N/A"

            combined_df = pd.concat([existing_df, new_df], ignore_index=True)
            final_df = combined_df.drop_duplicates(subset=['URL'], keep='last')
        except Exception as e:
            print(f"Error merging with existing JSON: {e}. Defaulting to new data.")
            final_df = new_df
    else:
        print("No existing data.json found. Creating new database...")
        final_df = new_df

    final_df = final_df.fillna("N/A")
    final_df.to_json(json_filename, orient='records', indent=4)
    print(f"Successfully saved {len(final_df)} total records to {json_filename}!")

if __name__ == "__main__":
    main()
