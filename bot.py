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
EBAY_APP_ID = os.getenv('EBAY_APP_ID')

# eBay API Configuration
EBAY_FINDING_API = 'https://svcs.ebay.com/services/search/FindingService/v1'

# Price extraction patterns
PRICE_PATTERN = r'£(\d+\.?\d*)'

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
    cleaned = re.sub(r'£\d+\.?\d*', '', cleaned)
    
    # Remove URLs
    cleaned = re.sub(r'https?://\S+', '', cleaned)
    
    # Remove extra whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    return cleaned

async def get_ebay_sold_prices_api(product_name, max_results=10):
    """Fetch recent sold prices from eBay API"""
    if not EBAY_APP_ID:
        print("   ⚠️ No eBay API key configured", flush=True)
        return None, None, 0
    
    print(f"🔍 Searching eBay API for: '{product_name}'", flush=True)
    
    # Build 2 search variations max
    search_queries = []
    cleaned = clean_product_name(product_name)
    search_queries.append(cleaned)
    
    words = cleaned.split()
    if len(words) >= 3:
        search_queries.append(' '.join(words[:-1]))
    
    # Remove duplicates
    seen = set()
    search_queries = [q for q in search_queries if q and not (q.lower() in seen or seen.add(q.lower()))]
    search_queries = search_queries[:2]
    
    print(f"   Will try {len(search_queries)} searches: {search_queries}", flush=True)
    
    for i, query in enumerate(search_queries, 1):
        try:
            search_query = query.strip()
            if not search_query:
                continue
            
            print(f"   [{i}/{len(search_queries)}] API search: '{query}'", flush=True)
            
            params = {
                'OPERATION-NAME': 'findCompletedItems',
                'SERVICE-VERSION': '1.0.0',
                'SECURITY-APPNAME': EBAY_APP_ID,
                'RESPONSE-DATA-FORMAT': 'JSON',
                'REST-PAYLOAD': '',
                'keywords': search_query,
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

async def create_alert_embed(original_embed, source_message):
    """Create a formatted alert embed with eBay resell data"""
    
    # Extract product info
    product_name, buy_price = extract_product_info(original_embed)
    
    if not product_name:
        product_name = "Unknown Product"
    
    if not buy_price:
        buy_price = 0
    
    # Get eBay data using API
    ebay_data, resell_price, sold_count = await get_ebay_sold_prices_api(product_name)
    
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
    for field in original_embed.fields:
        if 'link' in field.name.lower():
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
    print(f'eBay API: {"✓ Configured" if EBAY_APP_ID else "✗ Not configured"}', flush=True)
    if EBAY_APP_ID:
        print(f'eBay App ID: {EBAY_APP_ID[:15]}...', flush=True)
    print('Bot is ready and waiting for embeds...', flush=True)

@bot.event
async def on_message(message):
    if message.channel.id == MONITORED_CHANNEL_ID:
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", flush=True)
        print(f"📨 Message received in monitored channel!", flush=True)
        print(f"   Author: {message.author}", flush=True)
        print(f"   Has embeds: {len(message.embeds)}", flush=True)
    
    if message.channel.id != MONITORED_CHANNEL_ID:
        return
    
    if message.author == bot.user:
        print("⏭️  Ignoring my own message", flush=True)
        return
    
    if not message.embeds:
        print("⏭️  No embeds found", flush=True)
        return
    
    print(f"✅ Processing {len(message.embeds)} embed(s)!", flush=True)
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", flush=True)
    
    for embed in message.embeds:
        try:
            alert_embed, profit, sold_count = await create_alert_embed(embed, message)
            
            role = message.guild.get_role(PING_ROLE_ID)
            
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
                await message.channel.send(
                    content=f"{role.mention} {alert_text}",
                    embed=alert_embed
                )
            else:
                await message.channel.send(
                    content=alert_text,
                    embed=alert_embed
                )
        
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
