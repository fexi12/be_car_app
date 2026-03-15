#!/usr/bin/env python3
"""
Brandacars: InterClássico.com vintage car price tracker scraper
Extracts car listings, stores in brandacars backend database, tracks price history
Run: python scraper.py
"""

import os
import sys
import time
from datetime import datetime
from playwright.sync_api import sync_playwright

# Add car module to path
sys.path.insert(0, os.path.dirname(__file__))
from car.database import db_cursor, sqlp

INTERCLASSICO_URL = 'https://www.interclassico.com/'  # Vintage cars

def scrape_listings():
    """Scrape InterClássico, store listings and price history"""
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        print(f"[{datetime.now().isoformat()}] Starting InterClássico scrape...")
        
        try:
            page.goto(INTERCLASSICO_URL, wait_until='domcontentloaded', timeout=30000)
            page.wait_for_load_state('networkidle', timeout=15000)
        except:
            pass  # Continue even if network idle fails
        
        # Extract listing data from page text (simple DOM structure)
        listings = page.evaluate("""() => {
            const results = [];
            const bodyText = document.body.innerText;
            
            // Parse lines for pattern: "Brand Model\\nYear\\nPrice"
            const lines = bodyText.split('\\n').filter(l => l.trim());
            
            for (let i = 0; i < lines.length - 2; i++) {
                const line = lines[i].trim();
                const yearStr = lines[i + 1].trim();
                const priceStr = lines[i + 2].trim();
                
                // Check if we found a pattern: text (likely brand/model), then year, then price
                const yearMatch = yearStr.match(/^(19|20)\\d{2}$/);
                const priceMatch = priceStr.match(/([0-9.,]+)€/);
                
                if (yearMatch && priceMatch && line && !line.includes('©')) {
                    const year = parseInt(yearMatch[0]);
                    const priceText = priceStr.match(/([0-9.]+)/)[1];
                    const price = parseInt(priceText.replace(/\\D/g, '')) || null;
                    
                    if (price && line.length > 2) {
                        // Parse brand and model
                        const parts = line.split(' ');
                        const brand = parts[0] || '';
                        const model = parts.slice(1).join(' ') || '';
                        const listingId = `interclassico_${brand}_${model}_${year}`.replace(/\\s+/g, '_').toLowerCase();
                        
                        results.push({
                            listingId,
                            brand,
                            model,
                            year,
                            price,
                            url: 'https://www.interclassico.com/',
                            mileage: null
                        });
                    }
                }
            }
            
            return results;
        }""")
        
        browser.close()
        
        print(f"[{datetime.now().isoformat()}] Found {len(listings)} listings")
        
        # Upsert listings and track price history
        with db_cursor(commit=True) as cur:
            for listing in listings:
                try:
                    listing_id = listing['listingId']
                    brand = listing['brand']
                    model = listing['model']
                    year = listing['year']
                    price = listing['price']
                    url = listing['url']
                    mileage = listing['mileage']
                    
                    # Check if listing exists and get previous price
                    cur.execute(sqlp("SELECT current_price FROM scraped_listings WHERE listing_id = ?"), (listing_id,))
                    existing = cur.fetchone()
                    
                    # Upsert listing
                    if existing:
                        cur.execute(sqlp("""
                            UPDATE scraped_listings
                            SET brand = ?, model = ?, year = ?, price = ?, current_price = ?, url = ?, mileage = ?, updated_at = ?
                            WHERE listing_id = ?
                        """), (brand, model, year, price, price, url, mileage, datetime.now().isoformat(), listing_id))
                    else:
                        cur.execute(sqlp("""
                            INSERT INTO scraped_listings
                            (listing_id, brand, model, year, price, current_price, url, mileage, scraped_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """), (listing_id, brand, model, year, price, price, url, mileage, datetime.now().isoformat(), datetime.now().isoformat()))
                    
                    # Insert price history if price changed
                    if not existing or existing[0] != price:
                        cur.execute(sqlp("""
                            INSERT INTO listing_price_history (listing_id, price, recorded_at)
                            VALUES (?, ?, ?)
                        """), (listing_id, price, datetime.now().isoformat()))
                    
                    time.sleep(0.5)  # Delay to avoid rate limiting
                    
                except Exception as err:
                    print(f"Error processing listing {listing.get('listingId')}: {err}")
        
        print(f"[{datetime.now().isoformat()}] Scrape complete")

if __name__ == '__main__':
    scrape_listings()
