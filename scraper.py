import requests
from bs4 import BeautifulSoup
import json
import pandas as pd
import os

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
                    
                    # Bonus: The Review schema usually contains the rating and date too!
                    if 'reviewRating' in item:
                        rating = item['reviewRating'].get('ratingValue', 'N/A')
                    if 'datePublished' in item:
                        dateline = item.get('datePublished', 'N/A')[:10] # Just grab the YYYY-MM-DD
                        
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
                # Uses regex/case-insensitive split approach practically
                product_name = meta_title.split(" review")[0].split(" Review")[0].strip()

    return product_name, rating, dateline

def main():
    print("Starting TechRadar Scraper...")
    
    # 1. Fetch the sitemap (For this script, we'll target a specific TR review sitemap)
    # Note: TechRadar has a massive sitemap index. You might need to plug in the specific 
    # year/month sitemap URL here depending on how far back you want to scrape daily.
    sitemap_url = "https://www.techradar.com/sitemap.xml" 
    
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(sitemap_url, headers=headers)
    soup = BeautifulSoup(response.content, 'xml')

    new_reviews_data = []

    # 2. Extract URLs and scrape
    urls = [loc.text for loc in soup.find_all('loc') if '/reviews/' in loc.text]
    
    # Limit to the first 20 for testing purposes so it doesn't run for hours
    print(f"Found {len(urls)} review URLs. Scraping the latest 20 for this test run...")
    for url in urls[:20]:
        print(f"Scraping: {url}")
        name, rating, date = scrape_review_data(url)
        
        new_reviews_data.append({
            'Product': name,
            'Rating': rating,
            'Dateline': date,
            'URL': url
        })

    new_df = pd.DataFrame(new_reviews_data)

    # 3. Merge with existing data and remove duplicates
    json_filename = 'data.json'
    
    if os.path.exists(json_filename):
        print("Found existing data.json. Merging and deduplicating...")
        existing_df = pd.read_json(json_filename)
        # Combine old and new
        combined_df = pd.concat([existing_df, new_df], ignore_index=True)
        # Drop duplicates based on URL, keeping the most recently scraped version
        final_df = combined_df.drop_duplicates(subset=['URL'], keep='last')
    else:
        print("No existing data.json found. Creating new database...")
        final_df = new_df

    # 4. Save the final JSON file
    final_df.to_json(json_filename, orient='records', indent=4)
    print(f"Successfully saved {len(final_df)} total records to {json_filename}!")

if __name__ == "__main__":
    main()