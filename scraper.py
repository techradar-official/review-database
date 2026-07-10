import requests
from bs4 import BeautifulSoup
import json
import pandas as pd
import os
import time

def scrape_review_data(url):
    """Fetches the webpage and extracts the product name, rating, and dateline."""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
    except Exception as e:
        print(f"Error loading {url}: {e}")
        return None, None, None

    product_name = "PRODUCT NAME NOT FOUND"
    rating = "N/A"
    dateline = "N/A"

    # --- 1. Extract Product Name (Hybrid Method) ---
    schema_tags = soup.find_all('script', type='application/ld+json')
    found_in_schema = False
    
    for tag in schema_tags:
        try:
            data = json.loads(tag.string)
            if isinstance(data, dict):
                data = [data] 
            for item in data:
                if item.get('@type') == 'Review' and 'itemReviewed' in item:
                    product_name = item['itemReviewed'].get('name')
                    if 'reviewRating' in item:
                        rating = item['reviewRating'].get('ratingValue', 'N/A')
                    if 'datePublished' in item:
                        dateline = item.get('datePublished', 'N/A')[:10]
                    found_in_schema = True
                    break
        except:
            pass 
        if found_in_schema:
            break

    # --- 2. Fallback for Product Name (Meta Title Split) ---
    if not found_in_schema or product_name is None:
        title_tag = soup.find('title')
        if title_tag and title_tag.string:
            meta_title = title_tag.string
            if " review" in meta_title.lower():
                product_name = meta_title.split(" review")[0].split(" Review")[0].strip()

    return product_name, rating, dateline

def get_links_from_feed(page_number):
    """Scrapes a specific page of the TechRadar reviews feed for article URLs."""
    # TechRadar's pagination format: /reviews/page/2
    if page_number == 1:
        url = "https://www.techradar.com/reviews"
    else:
        url = f"https://www.techradar.com/reviews/page/{page_number}"
        
    print(f"Scanning feed page {page_number}: {url}")
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        # If the page doesn't exist (we hit the end of the feed), stop.
        if response.status_code != 200:
            return []
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        page_links = []
        # TechRadar wraps their main feed article links in tags with the class "article-link"
        # We find all of them to extract the href (URL)
        article_tags = soup.find_all('a', class_='article-link')
        
        for tag in article_tags:
            link = tag.get('href')
            if link and not link.startswith('http'):
                # Handle relative URLs just in case
                link = "https://www.techradar.com" + link
            
            # Avoid duplicates on the same page
            if link not in page_links:
                page_links.append(link)
                
        return page_links
    except Exception as e:
        print(f"Error scraping feed page: {e}")
        return []

def main():
    print("Starting TechRadar Pagination Scraper...")
    
    new_reviews_data = []
    
    # --- PAGINATION SETTINGS ---
    # We only scrape the first 3 pages of the feed (approx 60 articles) per run
    # so we don't overload their servers. Since this runs daily, 60 is plenty!
    pages_to_scrape = 3 
    all_urls_to_scrape = []

    for page in range(1, pages_to_scrape + 1):
        links = get_links_from_feed(page)
        all_urls_to_scrape.extend(links)
        time.sleep(2) # Pause for 2 seconds between pages to be polite to their server
        
    print(f"Found {len(all_urls_to_scrape)} total review URLs in the feed.")

    # Scrape each individual review URL
    for url in all_urls_to_scrape:
        print(f"Scraping data from: {url}")
        name, rating, date = scrape_review_data(url)
        
        new_reviews_data.append({
            'Product': name,
            'Rating': rating,
            'Dateline': date,
            'URL': url
        })
        time.sleep(1) # Pause for 1 second between articles

    new_df = pd.DataFrame(new_reviews_data)

    # Merge with existing data and remove duplicates
    json_filename = 'data.json'
    
    if os.path.exists(json_filename):
        print("Found existing data.json. Merging and deduplicating...")
        existing_df = pd.read_json(json_filename)
        combined_df = pd.concat([existing_df, new_df], ignore_index=True)
        # We drop duplicates based on URL. This is crucial: even if we scrape
        # an article we already scraped yesterday, this line prevents duplicates!
        final_df = combined_df.drop_duplicates(subset=['URL'], keep='last')
    else:
        print("No existing data.json found. Creating new database...")
        final_df = new_df

    # Save the final JSON file
    final_df.to_json(json_filename, orient='records', indent=4)
    print(f"Successfully saved {len(final_df)} total records to {json_filename}!")

if __name__ == "__main__":
    main()
