import discord
from discord.ext import commands
import re
from datetime import datetime
import os
import sys
import aiohttp
import statistics
from urllib.parse import quote
import asyncio
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# Force stdout to flush immediately
sys.stdout.reconfigure(line_buffering=True)

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.messages = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Configuration - Parse multiple channels from environment variable
# Format: MONITORED_CHANNELS=channel_id:role_id,channel_id:role_id
MONITORED_CHANNELS = {}
channels_config = os.getenv('MONITORED_CHANNELS', '1417115045573300244:1400527195679490319,1397272799835324590:1397286672160395485')

for pair in channels_config.split(','):
    if ':' in pair:
        try:
            channel_id, role_id = pair.split(':')
            MONITORED_CHANNELS[int(channel_id.strip())] = int(role_id.strip())
        except ValueError:
            print(f"⚠️ Warning: Could not parse channel config: {pair}", flush=True)

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
EBAY_APP_ID = os.getenv('EBAY_APP_ID')

# eBay API Configuration
EBAY_FINDING_API = 'https://svcs.ebay.com/services/search/FindingService/v1'

# Price extraction patterns - allow optional space after £
PRICE_PATTERN = r'£\s*(\d+\.?\d*)'

def should_exclude_multipacks(product_name):
    """Determine if we should exclude multipacks based on product type"""
    lower_name = product_name.lower()
    
    # Single item indicators - these should exclude multipacks
    single_item_keywords = [
        'tin', 'mini tin', 'booster pack', 'single pack', 'blister',
        'theme deck', 'starter deck', 'premium collection'
    ]
    
    # If product name suggests a single item, exclude multipacks
    if any(keyword in lower_name for keyword in single_item_keywords):
        return True
    
    # If it's already a multipack/box, don't exclude anything
    multipack_keywords = ['booster box', 'display', 'case', 'bundle', 'lot', 'set of']
    if any(keyword in lower_name for keyword in multipack_keywords):
        return False
    
    # Default: don't exclude (safer for unknown products)
    return False

def get_exclusion_terms(product_name):
    """Get eBay search exclusion terms if applicable"""
    if should_exclude_multipacks(product_name):
        # Only exclude the most common multipacks - less aggressive
        return ' -"booster box" -display'
    return ''

def clean_product_name(name):
    """Clean and optimize product name for eBay search"""
    if not name:
        return name
    
    # Remove common words that might narrow search too much
    remove_words = ['[TEST]', 'bundle']
    cleaned = name
    
    for word in remove_words:
        cleaned = re.sub(re.escape(word), '', cleaned, flags=re.IGNORECASE)
    
    # Remove prices
    cleaned = re.sub(r'£\s*\d+\.?\d*', '', cleaned)
    
    # Remove URLs
    cleaned = re.sub(r'https?://\S+', '', cleaned)
    
    # Remove hyphens and replace with single space
    cleaned = cleaned.replace(' - ', ' ')
    cleaned = cleaned.replace('-', ' ')
    
    # Replace multiple spaces with single space (must be after hyphen removal)
    cleaned = re.sub(r'\s+', ' ', cleaned)
    
    # Remove leading/trailing whitespace
    cleaned = cleaned.strip()
    
    return cleaned

async def get_ebay_sold_prices_api(product_name, max_results=10):
    """Fetch recent sold prices from eBay API with exact match"""
    if not EBAY_APP_ID:
        print("   ⚠️ No eBay API key configured", flush=True)
        return None, None, 0
    
    print(f"🔍 Searching eBay API for: '{product_name}'", flush=True)
    
    # Build search variations - try exact match first, then broader
    search_queries = []
    cleaned = clean_product_name(product_name)
    
    # 1. Exact match with quotes (most precise)
    search_queries.append(f'"{cleaned}"')
    
    # 2. Without quotes (broader, catches variations)
    search_queries.append(cleaned)
    
    # 3. Without last word and no quotes (fallback)
    words = cleaned.split()
    if len(words) >= 3:
        search_queries.append(' '.join(words[:-1]))
    
    print(f"   Will try {len(search_queries)} searches (exact → broad)", flush=True)
    
    for i, query in enumerate(search_queries, 1):
        try:
            search_query = query.strip()
            if not search_query:
                continue
            
            print(f"   [{i}/{len(search_queries)}] API search: '{search_query}'", flush=True)
            
            # Add exclusions only if it's a single-item product
            exclusions = get_exclusion_terms(product_name)
            search_with_exclusions = search_query + exclusions
            if exclusions:
                print(f"      (Excluding multipacks)", flush=True)
            
            params = {
                'OPERATION-NAME': 'findCompletedItems',
                'SERVICE-VERSION': '1.0.0',
                'SECURITY-APPNAME': EBAY_APP_ID,
                'RESPONSE-DATA-FORMAT': 'JSON',
                'REST-PAYLOAD': '',
                'keywords': search_with_exclusions,
                'itemFilter(0).name': 'SoldItemsOnly',
                'itemFilter(0).value': 'true',
                'itemFilter(1).name': 'ListingType',
                'itemFilter(1).value': 'FixedPrice',
                'sortOrder': 'EndTimeSoonest',
                'paginationInput.entriesPerPage': max_results,
                'GLOBAL-ID': 'EBAY-GB'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(EBAY_FINDING_API, params=params, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # Parse response
                        search_result = data.get('findCompletedItemsResponse', [{}])[0]
                        
                        # Check for API errors
                        ack = search_result.get('ack', [''])[0]
                        if ack == 'Failure':
                            error_msg = search_result.get('errorMessage', [{}])[0]
                            print(f"      ❌ API error: {error_msg}", flush=True)
                            continue
                        
                        items = search_result.get('searchResult', [{}])[0].get('item', [])
                        
                        if not items:
                            print(f"      No results", flush=True)
                            continue
                        
                        # Extract sold prices
                        sold_prices = []
                        for item in items:
                            selling_status = item.get('sellingStatus', [{}])[0]
                            converted_price = selling_status.get('convertedCurrentPrice', [{}])[0]
                            price = float(converted_price.get('__value__', 0))
                            if price > 0:
                                sold_prices.append(price)
                        
                        if sold_prices:
                            print(f"      ✅ Found {len(sold_prices)} sales!", flush=True)
                            
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
                        print(f"      HTTP {response.status}", flush=True)
        
        except Exception as e:
            print(f"      Error: {e}", flush=True)
            continue
    
    print(f"   ✗ No results from API", flush=True)
    return None, None, 0

def get_driver():
    """Initialize headless Chrome driver"""
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_argument('--disable-extensions')
    
    # Disable images for speed
    prefs = {'profile.managed_default_content_settings.images': 2}
    chrome_options.add_experimental_option('prefs', prefs)
    chrome_options.page_load_strategy = 'eager'
    
    driver = webdriver.Chrome(options=chrome_options)
    return driver

async def scrape_ebay_sold_prices_selenium(product_name, max_results=10):
    """Fallback: Scrape eBay using Selenium"""
    print(f"🔍 Selenium fallback for: '{product_name}'", flush=True)
    
    cleaned = clean_product_name(product_name)
    
    # Try exact match first, then without quotes
    search_queries = [f'"{cleaned}"', cleaned]
    
    loop = asyncio.get_event_loop()
    
    for query in search_queries:
        print(f"   Trying: {query}", flush=True)
        result = await loop.run_in_executor(None, _scrape_ebay_sync, query, product_name, max_results)
        if result[0]:  # If we got data
            return result
    
    return None, None, 0

def _scrape_ebay_sync(search_query, original_product_name, max_results):
    """Synchronous Selenium scraping"""
    driver = None
    
    try:
        driver = get_driver()
        
        # Add exclusions only for single-item products
        exclusions = get_exclusion_terms(original_product_name)
        search_with_exclusions = search_query + exclusions
        
        if exclusions:
            print(f"      (Excluding multipacks)", flush=True)
        
        search_url = f"https://www.ebay.co.uk/sch/i.html?_nkw={quote(search_with_exclusions)}&LH_Sold=1&LH_Complete=1&LH_ItemCondition=1000"
        
        print(f"   Loading: {search_url[:120]}...", flush=True)
        driver.get(search_url)
        
        import time
        time.sleep(1.5)
        
        # Try multiple methods to find items
        items = []
        try:
            results_list = driver.find_element(By.CSS_SELECTOR, "ul.srp-results")
            items = results_list.find_elements(By.TAG_NAME, "li")
            print(f"   Found {len(items)} items", flush=True)
        except:
            print(f"   No items found", flush=True)
            return None, None, 0
        
        if len(items) == 0:
            return None, None, 0
        
        # Extract prices
        sold_prices = []
        for item in items[:max_results]:
            try:
                item_text = item.text
                if not item_text:
                    continue
                
                matches = re.findall(r'£\s*([\d,]+\.?\d*)', item_text)
                if matches:
                    for match in matches:
                        try:
                            price = float(match.replace(',', ''))
                            if 5 < price < 10000:  # Lowered from 10 to 5
                                sold_prices.append(price)
                                break
                        except ValueError:
                            continue
            except:
                continue
        
        print(f"   Extracted {len(sold_prices)} prices", flush=True)
        
        if sold_prices:
            print(f"   ✅ Selenium SUCCESS!", flush=True)
            
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
                'query_used': search_query
            }, median_price, len(sold_prices)
        
        return None, None, 0
        
    except Exception as e:
        print(f"   Selenium error: {e}", flush=True)
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
    
    # Debug: Print entire embed structure
    print(f"   === FULL EMBED DEBUG ===", flush=True)
    print(f"   Title: '{embed.title}'", flush=True)
    print(f"   Description: '{embed.description}'", flush=True)
    print(f"   Author: '{embed.author.name if embed.author else None}'", flush=True)
    print(f"   Footer: '{embed.footer.text if embed.footer else None}'", flush=True)
    print(f"   Number of fields: {len(embed.fields)}", flush=True)
    
    # Collect all text from embed
    all_text = []
    
    if embed.title:
        all_text.append(('title', embed.title))
    if embed.description:
        all_text.append(('description', embed.description))
    if embed.author and embed.author.name:
        all_text.append(('author', embed.author.name))
    if embed.footer and embed.footer.text:
        all_text.append(('footer', embed.footer.text))
    
    # Check all fields
    for idx, field in enumerate(embed.fields):
        print(f"   Field {idx}: name='{field.name}' value='{field.value}' inline={field.inline}", flush=True)
        all_text.append((f'field_{idx}_name', field.name))
        all_text.append((f'field_{idx}_value', field.value))
    
    # Search for first price in all collected text
    print(f"   Searching for price in {len(all_text)} text pieces...", flush=True)
    
    for location, text in all_text:
        if text and '£' in str(text):
            matches = re.findall(PRICE_PATTERN, str(text))
            if matches:
                try:
                    price = float(matches[0].replace(',', ''))
                    # Reasonable price check
                    if 1 < price < 100000:
                        buy_price = price
                        print(f"   ✅ Found price £{buy_price} in {location}", flush=True)
                        break
                except Exception as e:
                    print(f"   Failed to parse price from {location}: {e}", flush=True)
                    continue
    
    if not buy_price:
        print(f"   ❌ NO PRICE FOUND!", flush=True)
        print(f"   Checked locations: {[loc for loc, _ in all_text]}", flush=True)
    
    print(f"   === END DEBUG ===", flush=True)
    
    return product_name, buy_price

async def create_alert_embed(original_embed, source_message, ebay_data=None, resell_price=None, sold_count=0):
    """Create a formatted alert embed with eBay resell data"""
    
    # Extract product info
    product_name, buy_price = extract_product_info(original_embed)
    
    if not product_name:
        product_name = "Unknown Product"
    
    if not buy_price:
        buy_price = 0
    
    # Determine actual cost basis
    actual_cost = buy_price
    
    # Create new embed
    if ebay_data and resell_price and resell_price > actual_cost:
        profit = resell_price - actual_cost
        profit_percent = (profit / actual_cost) * 100 if actual_cost > 0 else 0
        
        # Color based on profit
        if profit > 50:
            color = discord.Color.gold()
        elif profit > 20:
            color = discord.Color.green()
        else:
            color = discord.Color.blue()
    else:
        color = discord.Color.orange()
        profit = 0
        profit_percent = 0
    
    alert = discord.Embed(
        color=color,
        timestamp=datetime.utcnow()
    )
    
    # Title
    alert.title = f"💰 {product_name}"
    
    # PROFIT AT THE TOP
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
    
    # Blacklist of domains to exclude
    excluded_domains = ['stockx.com', 'keepa.com', 'amazon.co', 'amazon.com', 'selleramp.com']
    
    # Extract original product links from embed (excluding blacklisted sites)
    for field in original_embed.fields:
        if 'link' in field.name.lower():
            urls = re.findall(r'https?://[^\s\]]+', field.value)
            for url in urls:
                # Check if URL contains any excluded domain
                if not any(excluded in url.lower() for excluded in excluded_domains):
                    links.append(url)
                    break  # Only take first valid link
            break
    
    # Add clean eBay search links
    clean_search = quote(product_name)
    links.append(f"[🔍 eBay Sold Listings](https://www.ebay.co.uk/sch/i.html?_nkw={clean_search}&LH_Sold=1&LH_Complete=1)")
    links.append(f"[🛒 Current eBay Listings](https://www.ebay.co.uk/sch/i.html?_nkw={clean_search}&LH_ItemCondition=1000)")
    links.append(f"[🔎 Google Search](https://www.google.co.uk/search?q={clean_search})")
    
    if links:
        alert.add_field(
            name="🔗 Quick Links",
            value="\n".join(links),
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

def create_initial_embed(original_embed):
    """Create a quick initial embed while searching"""
    product_name, buy_price = extract_product_info(original_embed)
    
    if not product_name:
        product_name = "Unknown Product"
    
    if not buy_price:
        buy_price = 0
    
    alert = discord.Embed(
        title=f"💰 {product_name}",
        description="🔍 **Searching eBay for resell data...**\n\nThis may take a few seconds.",
        color=discord.Color.blue(),
        timestamp=datetime.utcnow()
    )
    
    alert.add_field(
        name="🏷️ Alert Buy Price",
        value=f"£{buy_price:.2f}",
        inline=False
    )
    
    # Add thumbnail if original has one
    if original_embed.thumbnail:
        alert.set_thumbnail(url=original_embed.thumbnail.url)
    
    # Add image if original has one
    if original_embed.image:
        alert.set_image(url=original_embed.image.url)
    
    return alert

@bot.event
async def on_ready():
    print(f'{bot.user} is now monitoring for deals!', flush=True)
    print(f'Monitoring {len(MONITORED_CHANNELS)} channel(s):', flush=True)
    for channel_id, role_id in MONITORED_CHANNELS.items():
        print(f'  • Channel {channel_id} → Role {role_id}', flush=True)
    print(f'eBay API: {"✓ Configured" if EBAY_APP_ID else "✗ Not configured"}', flush=True)
    if EBAY_APP_ID:
        print(f'eBay App ID: {EBAY_APP_ID[:15]}...', flush=True)
    print('Bot is ready and waiting for embeds...', flush=True)

@bot.event
async def on_message(message):
    # Check if message is in a monitored channel
    if message.channel.id not in MONITORED_CHANNELS:
        return
    
    if message.author == bot.user:
        print("⏭️  Ignoring my own message", flush=True)
        return
    
    if not message.embeds:
        print("⏭️  No embeds found", flush=True)
        return
    
    # Get the role for this specific channel
    role_id = MONITORED_CHANNELS[message.channel.id]
    
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", flush=True)
    print(f"📨 Message received in monitored channel!", flush=True)
    print(f"   Channel ID: {message.channel.id}", flush=True)
    print(f"   Role ID: {role_id}", flush=True)
    print(f"   Author: {message.author}", flush=True)
    print(f"   Has embeds: {len(message.embeds)}", flush=True)
    print(f"✅ Processing {len(message.embeds)} embed(s)!", flush=True)
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", flush=True)
    
    for embed in message.embeds:
        try:
            # STEP 1: Send immediate ping with initial embed
            role = message.guild.get_role(role_id)
            initial_embed = create_initial_embed(embed)
            
            if role:
                alert_message = await message.channel.send(
                    content=f"{role.mention} 🚨 **New Deal Alert!**",
                    embed=initial_embed
                )
            else:
                alert_message = await message.channel.send(
                    content="🚨 **New Deal Alert!**",
                    embed=initial_embed
                )
            
            print("✅ Initial ping sent, now searching eBay...", flush=True)
            
            # STEP 2: Search eBay in the background
            product_name, buy_price = extract_product_info(embed)
            
            # Try eBay API first (fast)
            ebay_data, resell_price, sold_count = await get_ebay_sold_prices_api(product_name)
            
            # If API fails, use Selenium fallback
            if not ebay_data or sold_count == 0:
                print(f"   API returned no data, trying Selenium...", flush=True)
                ebay_data, resell_price, sold_count = await scrape_ebay_sold_prices_selenium(product_name)
            
            # STEP 3: Edit the message with full analysis
            final_embed, profit, sold_count = await create_alert_embed(embed, message, ebay_data, resell_price, sold_count)
            
            # Update the content based on results
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
            
            if role:
                await alert_message.edit(
                    content=f"{role.mention} {alert_text}",
                    embed=final_embed
                )
            else:
                await alert_message.edit(
                    content=alert_text,
                    embed=final_embed
                )
            
            print("✅ Message updated with full analysis!", flush=True)
        
        except Exception as e:
            print(f"Error processing embed: {e}", flush=True)
            import traceback
            traceback.print_exc()
            continue

@bot.event
async def on_connect():
    print("Bot connected to Discord!", flush=True)

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("ERROR: DISCORD_TOKEN environment variable not set!")
        exit(1)
    
    bot.run(DISCORD_TOKEN)
