import discord
from discord.ext import commands
import re
from datetime import datetime
import aiohttp
import statistics
from urllib.parse import quote
import os

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

async def get_ebay_current_listings(product_name, max_results=20):
    """Fetch current active listings to find lowest RRP/retail price"""
    if not EBAY_APP_ID:
        return None
    
    try:
        search_query = product_name.strip()
        
        params = {
            'OPERATION-NAME': 'findItemsAdvanced',
            'SERVICE-VERSION': '1.0.0',
            'SECURITY-APPNAME': EBAY_APP_ID,
            'RESPONSE-DATA-FORMAT': 'JSON',
            'REST-PAYLOAD': '',
            'keywords': search_query,
            'itemFilter(0).name': 'ListingType',
            'itemFilter(0).value': 'FixedPrice',  # Buy It Now only
            'itemFilter(1).name': 'Condition',
            'itemFilter(1).value': 'New',
            'sortOrder': 'PricePlusShippingLowest',
            'paginationInput.entriesPerPage': max_results,
            'GLOBAL-ID': 'EBAY-GB'
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(EBAY_FINDING_API, params=params, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    search_result = data.get('findItemsAdvancedResponse', [{}])[0]
                    items = search_result.get('searchResult', [{}])[0].get('item', [])
                    
                    if items:
                        # Get prices from current listings
                        prices = []
                        for item in items:
                            selling_status = item.get('sellingStatus', [{}])[0]
                            price_obj = selling_status.get('convertedCurrentPrice', [{}])[0]
                            price = float(price_obj.get('__value__', 0))
                            if price > 0:
                                prices.append(price)
                        
                        if prices:
                            return min(prices)  # Return lowest current retail price
                
                return None
    
    except Exception as e:
        print(f"Error fetching current listings: {e}")
        return None

async def get_ebay_sold_prices(product_name, max_results=20):
    """Fetch recent sold prices from eBay with fallback searches"""
    if not EBAY_APP_ID:
        print("Warning: EBAY_APP_ID not set")
        return None, None, 0
    
    # Build progressive search variations - from specific to broad
    search_queries = []
    
    # 1. Start with original
    search_queries.append(product_name)
    
    # 2. Clean version (remove special chars, extra spaces)
    cleaned = re.sub(r'[^\w\s]', ' ', product_name)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if cleaned != product_name:
        search_queries.append(cleaned)
    
    # 3. Try removing words progressively
    words = cleaned.split()
    
    if len(words) >= 4:
        # Remove last word
        search_queries.append(' '.join(words[:-1]))
        # Remove first word
        search_queries.append(' '.join(words[1:]))
        # Remove first and last
        if len(words) >= 5:
            search_queries.append(' '.join(words[1:-1]))
    
    if len(words) >= 3:
        # Try just first 3 words
        search_queries.append(' '.join(words[:3]))
        # Try just last 3 words
        search_queries.append(' '.join(words[-3:]))
        
    if len(words) >= 2:
        # Try just first 2 words
        search_queries.append(' '.join(words[:2]))
        # Try just last 2 words  
        search_queries.append(' '.join(words[-2:]))
    
    # 4. Remove common filler words
    filler_words = {'the', 'a', 'an', 'of', 'and', 'with', 'pack', 'packs', 'set', 'bundle'}
    filtered_words = [w for w in words if w.lower() not in filler_words]
    if len(filtered_words) >= 2 and filtered_words != words:
        search_queries.append(' '.join(filtered_words))
    
    # Remove duplicates while preserving order
    seen = set()
    search_queries = [q for q in search_queries if q and not (q.lower() in seen or seen.add(q.lower()))]
    
    # Limit to 10 variations max to avoid excessive API calls
    search_queries = search_queries[:10]
    
    print(f"Trying {len(search_queries)} search variations for: '{product_name}'")
    
    for i, query in enumerate(search_queries, 1):
        try:
            search_query = query.strip()
            if not search_query:
                continue
            
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
                'itemFilter(1).value': 'FixedPrice',  # Buy It Now only
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
                            print(f"  [{i}/{len(search_queries)}] API error for '{query}': {error_msg}")
                            continue
                        
                        items = search_result.get('searchResult', [{}])[0].get('item', [])
                        
                        if not items:
                            print(f"  [{i}/{len(search_queries)}] No results for: '{query}'")
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
                            print(f"  [{i}/{len(search_queries)}] ✓ SUCCESS! Found {len(sold_prices)} sales using: '{query}'")
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
                            print(f"  [{i}/{len(search_queries)}] Found items but no valid prices for: '{query}'")
        
        except Exception as e:
            print(f"  [{i}/{len(search_queries)}] Error with query '{query}': {e}")
            continue
    
    # No results from any query
    print(f"  ✗ FAILED: No sold items found after {len(search_queries)} attempts")
    return None, None, 0

def clean_product_name(name):
    """Clean and optimize product name for eBay search"""
    if not name:
        return name
    
    # Remove common words that might narrow search too much
    remove_words = ['[TEST]', 'set of', 'bundle', 'official', 'new', 'sealed']
    cleaned = name
    
    for word in remove_words:
        cleaned = re.sub(re.escape(word), '', cleaned, flags=re.IGNORECASE)
    
    # Remove prices
    cleaned = re.sub(r'£\d+\.?\d*', '', cleaned)
    
    # Remove extra whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    # For Pokemon products, keep key terms
    # "Mega Evolutions Booster Box" -> try broader search if no results
    
    return cleaned

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
    
    # Fetch eBay data
    print(f"Searching eBay for: {product_name}")
    
    # Get sold prices (for resell estimate)
    ebay_data, resell_price, sold_count = await get_ebay_sold_prices(product_name)
    
    # Get current lowest retail price (for RRP comparison)
    current_rrp = await get_ebay_current_listings(product_name)
    
    # Determine actual cost basis
    if current_rrp and current_rrp < buy_price:
        # The listing price is higher than current retail - might be overpriced
        actual_cost = current_rrp
        price_warning = True
    else:
        actual_cost = buy_price
        price_warning = False
    
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
    
    if price_warning:
        price_info.append(f"⚠️ **Alert Price:** ~~£{buy_price:.2f}~~ (may be overpriced)")
        price_info.append(f"💡 **Lowest Current Listing:** £{current_rrp:.2f}")
        price_info.append(f"📊 **Using for calculations:** £{actual_cost:.2f}")
    else:
        price_info.append(f"🏷️ **Alert Buy Price:** £{buy_price:.2f}")
        if current_rrp and current_rrp < buy_price * 0.95:  # Only show if significantly lower
            price_info.append(f"💡 **FYI: Found cheaper listing:** £{current_rrp:.2f}")
    
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
    
    # Add eBay search links
    search_url = f"https://www.ebay.co.uk/sch/i.html?_nkw={quote(product_name)}&LH_Sold=1&LH_Complete=1"
    links.append(f"[🔍 eBay Sold Listings]({search_url})")
    
    current_url = f"https://www.ebay.co.uk/sch/i.html?_nkw={quote(product_name)}&LH_ItemCondition=1000"
    links.append(f"[🛒 Current eBay Listings]({current_url})")
    
    if links:
        alert.add_field(
            name="🔗 Links",
            value="\n".join(links[:7]),
            inline=False
        )
    
    # Add thumbnail if original has one
    if original_embed.thumbnail:
        alert.set_thumbnail(url=original_embed.thumbnail.url)
    
    # Add image if original has one
    if original_embed.image:
        alert.set_image(url=original_embed.image.url)
    
    # Footer with source and warnings
    source_text = original_embed.author.name if original_embed.author else 'Unknown'
    if ebay_data:
        source_text += f" | {sold_count} sales analyzed"
    if price_warning:
        source_text += " | ⚠️ Price Alert"
    
    alert.set_footer(text=source_text)
    
    return alert, profit, sold_count

@bot.event
async def on_ready():
    print(f'{bot.user} is now monitoring for deals!')
    print(f'Watching channel ID: {MONITORED_CHANNEL_ID}')
    print(f'eBay API integration: {"✓ Active" if EBAY_APP_ID else "✗ Not configured"}')

@bot.event
async def on_message(message):
    # Only monitor the specific channel
    if message.channel.id != MONITORED_CHANNEL_ID:
        return
    
    # Ignore bot's own messages
    if message.author == bot.user:
        return
    
    # Check if message has embeds
    if not message.embeds:
        return
    
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
                print(f"Warning: Role {PING_ROLE_ID} not found")
        
        except Exception as e:
            print(f"Error processing embed: {e}")
            import traceback
            traceback.print_exc()
            continue

# Health check endpoint for Railway
@bot.event
async def on_connect():
    print("Bot connected to Discord!")

# Run the bot
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("ERROR: DISCORD_TOKEN environment variable not set!")
        exit(1)
    
    bot.run(DISCORD_TOKEN)
