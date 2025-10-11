import discord
from discord.ext import commands
import re
from datetime import datetime
import os
import sys
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import statistics
from urllib.parse import quote
import asyncio

# Force stdout to flush immediately
sys.stdout.reconfigure(line_buffering=True)

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.messages = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Configuration - Using environment variables
MONITORED_CHANNEL_ID = int(os.getenv('MONITORED_CHANNEL_ID', '1417115045573300244'))
PING_ROLE_ID = int(os.getenv('PING_ROLE_ID', '1400527195679490319'))
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

# Price extraction patterns
PRICE_PATTERN = r'£(\d+\.?\d*)'

def get_driver():
    """Initialize headless Chrome driver"""
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
    
    # Performance optimizations
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_argument('--disable-extensions')
    chrome_options.add_argument('--disable-infobars')
    chrome_options.add_argument('--disable-notifications')
    chrome_options.add_argument('--disable-popup-blocking')
    
    # Disable images for faster loading
    prefs = {
        'profile.managed_default_content_settings.images': 2,
        'profile.default_content_setting_values.notifications': 2,
    }
    chrome_options.add_experimental_option('prefs', prefs)
    chrome_options.page_load_strategy = 'eager'  # Don't wait for full page load
    
    driver = webdriver.Chrome(options=chrome_options)
    return driver

def clean_product_name(name):
    """Clean and optimize product name for eBay search"""
    if not name:
        return name
    
    # Remove common words that might narrow search too much
    remove_words = ['[TEST]', 'set of', 'bundle', 'official']
    cleaned = name
    
    for word in remove_words:
        cleaned = re.sub(re.escape(word), '', cleaned, flags=re.IGNORECASE)
    
    # Remove prices
    cleaned = re.sub(r'£\d+\.?\d*', '', cleaned)
    
    # Remove extra whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    return cleaned

async def scrape_ebay_sold_prices(product_name, max_results=15):
    """Scrape eBay sold listings using Selenium"""
    print(f"🔍 Scraping eBay for: '{product_name}'", flush=True)
    
    # Build only 2 search variations max (reduced from 3)
    search_queries = []
    cleaned = clean_product_name(product_name)
    search_queries.append(cleaned)
    
    words = cleaned.split()
    if len(words) >= 3:
        # Just try without last word
        search_queries.append(' '.join(words[:-1]))
    
    # Remove duplicates
    seen = set()
    search_queries = [q for q in search_queries if q and not (q.lower() in seen or seen.add(q.lower()))]
    search_queries = search_queries[:2]  # Max 2 attempts
    
    print(f"   Will try {len(search_queries)} searches: {search_queries}", flush=True)
    
    driver = None
    try:
        # Run in executor to not block Discord bot
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _scrape_ebay_sync, search_queries, max_results)
        return result
    except Exception as e:
        print(f"   ❌ Scraping error: {e}", flush=True)
        return None, None, 0

def _scrape_ebay_sync(search_queries, max_results):
    """Synchronous eBay scraping function"""
    driver = None
    
    try:
        driver = get_driver()
        
        for i, query in enumerate(search_queries, 1):
            try:
                print(f"   [{i}/{len(search_queries)}] Trying: '{query}'", flush=True)
                
                # Build eBay sold listings URL
                search_url = f"https://www.ebay.co.uk/sch/i.html?_nkw={quote(query)}&LH_Sold=1&LH_Complete=1&LH_ItemCondition=1000"
                
                print(f"      Loading: {search_url}", flush=True)
                driver.get(search_url)
                
                # Reduced wait time - page_load_strategy='eager' helps
                import time
                time.sleep(1.5)
                
                # Debug: Check page title
                try:
                    page_title = driver.title
                    print(f"      Page title: {page_title}", flush=True)
                except:
                    pass
                
                # Try to find the results section with various selectors
                items = []
                
                # Method 1: Try ul.srp-results
                try:
                    results_list = driver.find_element(By.CSS_SELECTOR, "ul.srp-results")
                    items = results_list.find_elements(By.TAG_NAME, "li")
                    print(f"      Method 1: Found {len(items)} items via ul.srp-results", flush=True)
                except Exception as e:
                    print(f"      Method 1 failed: {e}", flush=True)
                
                # Method 2: Try data-testid
                if not items:
                    try:
                        items = driver.find_elements(By.CSS_SELECTOR, "[data-testid='item-card']")
                        print(f"      Method 2: Found {len(items)} items via data-testid", flush=True)
                    except Exception as e:
                        print(f"      Method 2 failed: {e}", flush=True)
                
                # Method 3: Try div with specific class patterns
                if not items:
                    try:
                        items = driver.find_elements(By.CSS_SELECTOR, "div.s-item__wrapper")
                        print(f"      Method 3: Found {len(items)} items via s-item__wrapper", flush=True)
                    except Exception as e:
                        print(f"      Method 3 failed: {e}", flush=True)
                
                # Method 4: Any list item in results area
                if not items:
                    try:
                        items = driver.find_elements(By.XPATH, "//li[contains(@class, 'item')]")
                        print(f"      Method 4: Found {len(items)} items via XPath", flush=True)
                    except Exception as e:
                        print(f"      Method 4 failed: {e}", flush=True)
                
                if len(items) == 0:
                    print(f"      ❌ No items found with any method", flush=True)
                    
                    # Debug: Save page source snippet
                    try:
                        page_snippet = driver.page_source[1000:2000]
                        print(f"      Page snippet: ...{page_snippet}...", flush=True)
                    except:
                        pass
                    
                    continue
                
                print(f"      ✓ Processing {len(items)} items", flush=True)
                
                # Extract prices from items (only process first 10 for speed)
                sold_prices = []
                for idx, item in enumerate(items[:10]):  # Reduced to 10 for faster processing
                    try:
                        # Get all text from item
                        item_text = item.text
                        
                        if not item_text:
                            continue
                        
                        # Look for prices in the text
                        matches = re.findall(r'£([\d,]+\.?\d*)', item_text)
                        
                        if matches:
                            for match in matches:
                                try:
                                    price = float(match.replace(',', ''))
                                    if 10 < price < 10000:  # Sanity check
                                        sold_prices.append(price)
                                        break  # Only take first valid price per item
                                except ValueError:
                                    continue
                                    
                    except Exception as e:
                        continue
                
                print(f"      Extracted {len(sold_prices)} prices from {len(items)} items", flush=True)
                
                if sold_prices:
                    print(f"      ✅ SUCCESS! Got {len(sold_prices)} valid prices", flush=True)
                    print(f"      Sample prices: £{sold_prices[0]:.2f}, £{sold_prices[1]:.2f}..." if len(sold_prices) >= 2 else f"      Prices: {sold_prices}", flush=True)
                    
                    # Calculate statistics
                    avg_price = statistics.mean(sold_prices)
                    median_price = statistics.median(sold_prices)
                    min_price = min(sold_prices)
                    max_price = max(sold_prices)
                    
                    return {
                        'average': avg_price,
                        'median': median_price,
                        'min': min_price,
                        'max': max_price,
                        'count': len(sold_prices),
                        'prices': sold_prices,
                        'query_used': query
                    }, median_price, len(sold_prices)
                else:
                    print(f"      ⚠️ Items found but couldn't extract valid prices", flush=True)
                    
            except Exception as e:
                print(f"      💥 Error: {e}", flush=True)
                import traceback
                traceback.print_exc()
                continue
        
        print(f"   ✗ No results from any search variation", flush=True)
        return None, None, 0
        
    finally:
        if driver:
            driver.quit()

def extract_product_info(embed):
    """Extract product name and price from embed"""
    product_name = None
    buy_price = None
    
    # Get product name from title
    if embed.title:
        product_name = clean_product_name(embed.title)
    
    # Extract buy price from fields
    for field in embed.fields:
        text = f"{field.name} {field.value}"
        
        # Look for price
        if 'price' in field.name.lower() or '£' in text:
            matches = re.findall(PRICE_PATTERN, text)
            if matches and not buy_price:
                buy_price = float(matches[0])
    
    # Check description for price if not found
    if not buy_price and embed.description:
        matches = re.findall(PRICE_PATTERN, embed.description)
        if matches:
            buy_price = float(matches[0])
    
    return product_name, buy_price

async def create_alert_embed(original_embed, source_message):
    """Create a formatted alert embed with eBay resell data"""
    
    # Extract product info
    product_name, buy_price = extract_product_info(original_embed)
    
    if not product_name:
        product_name = "Unknown Product"
    
    if not buy_price:
        buy_price = 0
    
    # Scrape eBay data
    ebay_data, resell_price, sold_count = await scrape_ebay_sold_prices(product_name)
    
    # Determine actual cost basis
    actual_cost = buy_price
    
    # Create new embed
    if ebay_data and resell_price and resell_price > actual_cost:
        profit = resell_price - actual_cost
        profit_percent = (profit / actual_cost) * 100 if actual_cost > 0 else 0
        
        # Color based on profit
        if profit > 50:
            color = discord.Color.gold()  # Excellent
        elif profit > 20:
            color = discord.Color.green()  # Good
        else:
            color = discord.Color.blue()  # Okay
    else:
        color = discord.Color.orange()  # No data or not profitable
        profit = 0
        profit_percent = 0
    
    alert = discord.Embed(
        color=color,
        timestamp=datetime.utcnow()
    )
    
    # Title
    alert.title = f"💰 {product_name}"
    
    # PROFIT AT THE TOP (most important for mobile users)
    if ebay_data and profit > 0:
        profit_emoji = "🟢" if profit > 20 else "🟡" if profit > 10 else "🔵"
        profit_text = f"{profit_emoji} **£{profit:.2f}** profit ({profit_percent:.1f}%)\n"
        profit_text += f"*Based on {sold_count} recent eBay sales*"
        
        alert.add_field(
            name="🎯 ESTIMATED PROFIT",
            value=profit_text,
            inline=False
        )
    elif ebay_data and sold_count > 0:
        alert.add_field(
            name="⚠️ LOW/NO PROFIT",
            value=f"Recent eBay sales show minimal profit potential\nMedian sold: £{ebay_data['median']:.2f} vs Cost: £{actual_cost:.2f}",
            inline=False
        )
    else:
        alert.add_field(
            name="❓ NO EBAY SALES DATA",
            value="⚠️ **Could not find recent sold listings**\n\nThis could mean:\n• New/rare product\n• Product name needs refinement\n• Low demand item\n\n**Manual research required before buying!**",
            inline=False
        )
    
    # Price breakdown
    price_info = []
    price_info.append(f"🏷️ **Alert Buy Price:** £{buy_price:.2f}")
    
    if ebay_data:
        price_info.append(f"📊 **eBay Median Sold:** £{ebay_data['median']:.2f}")
        price_info.append(f"📈 **eBay Average Sold:** £{ebay_data['average']:.2f}")
        price_info.append(f"💵 **Sold Price Range:** £{ebay_data['min']:.2f} - £{ebay_data['max']:.2f}")
        if ebay_data.get('query_used') and ebay_data['query_used'] != product_name:
            price_info.append(f"🔍 *Search used: \"{ebay_data['query_used']}\"*")
    else:
        price_info.append(f"❌ **Sold Data:** No recent sales found")
    
    alert.add_field(
        name="📊 Price Analysis",
        value="\n".join(price_info),
        inline=False
    )
    
    # Product details from original embed
    details = []
    for field in original_embed.fields:
        field_name_lower = field.name.lower()
        if 'status' in field_name_lower or 'stock' in field_name_lower:
            details.append(f"**{field.name}:** {field.value}")
    
    if details:
        alert.add_field(
            name="📦 Product Info",
            value="\n".join(details),
            inline=False
        )
    
    # Links section
    links = []
    for field in original_embed.fields:
        if 'link' in field.name.lower():
            # Extract URLs from the field value
            urls = re.findall(r'https?://[^\s\]]+', field.value)
            if urls:
                links.extend(urls)
            elif 'http' in field.value:
                links.append(field.value)
    
    # Add eBay search link
    search_url = f"https://www.ebay.co.uk/sch/i.html?_nkw={quote(product_name)}&LH_Sold=1&LH_Complete=1"
    links.append(f"[🔍 eBay Sold Listings]({search_url})")
    
    if links:
        alert.add_field(
            name="🔗 Links",
            value="\n".join(links[:6]),
            inline=False
        )
    
    # Add thumbnail if original has one
    if original_embed.thumbnail:
        alert.set_thumbnail(url=original_embed.thumbnail.url)
    
    # Add image if original has one
    if original_embed.image:
        alert.set_image(url=original_embed.image.url)
    
    # Footer with source
    source_text = original_embed.author.name if original_embed.author else 'Unknown'
    if ebay_data:
        source_text += f" | {sold_count} sales analyzed"
    
    alert.set_footer(text=source_text)
    
    return alert, profit, sold_count

@bot.event
async def on_ready():
    print(f'{bot.user} is now monitoring for deals!', flush=True)
    print(f'Watching channel ID: {MONITORED_CHANNEL_ID}', flush=True)
    print(f'Ping role ID: {PING_ROLE_ID}', flush=True)
    print('🤖 Using Selenium web scraper (no rate limits!)', flush=True)
    print('Bot is ready and waiting for embeds...', flush=True)

@bot.event
async def on_message(message):
    # Debug: Log ALL messages in monitored channel
    if message.channel.id == MONITORED_CHANNEL_ID:
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", flush=True)
        print(f"📨 Message received in monitored channel!", flush=True)
        print(f"   Author: {message.author} (ID: {message.author.id})", flush=True)
        print(f"   Has embeds: {len(message.embeds)}", flush=True)
        print(f"   Is bot: {message.author.bot}", flush=True)
        print(f"   Is me: {message.author == bot.user}", flush=True)
    
    # Only monitor the specific channel
    if message.channel.id != MONITORED_CHANNEL_ID:
        return
    
    # Ignore ONLY our own messages (not all bots)
    if message.author == bot.user:
        print("⏭️  Ignoring my own message", flush=True)
        return
    
    # Check if message has embeds
    if not message.embeds:
        print("⏭️  No embeds found in message", flush=True)
        return
    
    print(f"✅ Processing {len(message.embeds)} embed(s) from {message.author}!", flush=True)
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", flush=True)
    
    # Process each embed
    for embed in message.embeds:
        try:
            # Create alert embed with eBay data
            alert_embed, profit, sold_count = await create_alert_embed(embed, message)
            
            # Get role to ping
            role = message.guild.get_role(PING_ROLE_ID)
            
            # Determine alert level based on profit AND data availability
            if sold_count == 0:
                alert_text = "⚠️ **NO SALES DATA - Research Required!**"
            elif profit > 50:
                alert_text = "🔥 **HIGH PROFIT DEAL!** 🔥"
            elif profit > 20:
                alert_text = "🚨 **New Deal Alert!**"
            elif profit > 0:
                alert_text = "💼 **Deal Detected**"
            else:
                alert_text = "ℹ️ **Product Alert** (Low/No Profit)"
            
            # Send notification
            if role:
                await message.channel.send(
                    content=f"{role.mention} {alert_text}",
                    embed=alert_embed
                )
            else:
                await message.channel.send(
                    content=alert_text,
                    embed=alert_embed
                )
                print(f"Warning: Role {PING_ROLE_ID} not found", flush=True)
        
        except Exception as e:
            print(f"Error processing embed: {e}", flush=True)
            import traceback
            traceback.print_exc()
            continue

# Health check endpoint for Railway
@bot.event
async def on_connect():
    print("Bot connected to Discord!", flush=True)

# Run the bot
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("ERROR: DISCORD_TOKEN environment variable not set!")
        exit(1)
    
    bot.run(DISCORD_TOKEN)
