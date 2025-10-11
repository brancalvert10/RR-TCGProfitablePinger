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

async def get_ebay_sold_prices(product_name, max_results=10):
    """Fetch recent sold prices from eBay"""
    if not EBAY_APP_ID:
        print("Warning: EBAY_APP_ID not set")
        return None, None, 0
    
    try:
        # Clean product name for search
        search_query = product_name.strip()
        
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
            'itemFilter(1).value(0)': 'FixedPrice',
            'itemFilter(1).value(1)': 'AuctionWithBIN',
            'sortOrder': 'EndTimeSoonest',
            'paginationInput.entriesPerPage': max_results,
            'GLOBAL-ID': 'EBAY-GB'  # UK eBay
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(EBAY_FINDING_API, params=params, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Parse response
                    search_result = data.get('findCompletedItemsResponse', [{}])[0]
                    items = search_result.get('searchResult', [{}])[0].get('item', [])
                    
                    if not items:
                        return None, None, 0
                    
                    # Extract sold prices
                    sold_prices = []
                    for item in items:
                        selling_status = item.get('sellingStatus', [{}])[0]
                        converted_price = selling_status.get('convertedCurrentPrice', [{}])[0]
                        price = float(converted_price.get('__value__', 0))
                        if price > 0:
                            sold_prices.append(price)
                    
                    if sold_prices:
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
                            'prices': sold_prices
                        }, median_price, len(sold_prices)
                    
                return None, None, 0
    
    except Exception as e:
        print(f"Error fetching eBay data: {e}")
        return None, None, 0

def extract_product_info(embed):
    """Extract product name and price from embed"""
    product_name = None
    buy_price = None
    
    # Get product name from title
    if embed.title:
        product_name = embed.title
        # Clean up title - remove price if present
        product_name = re.sub(r'£\d+\.?\d*', '', product_name).strip()
    
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
    
    # Fetch eBay sold prices
    print(f"Searching eBay for: {product_name}")
    ebay_data, resell_price, sold_count = await get_ebay_sold_prices(product_name)
    
    # Create new embed
    if ebay_data and resell_price and resell_price > buy_price:
        color = discord.Color.green()  # Profitable
        profit = resell_price - buy_price
        profit_percent = (profit / buy_price) * 100 if buy_price > 0 else 0
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
    elif ebay_data:
        alert.add_field(
            name="⚠️ LOW PROFIT MARGIN",
            value="Recent eBay sales suggest minimal profit potential",
            inline=False
        )
    else:
        alert.add_field(
            name="❓ NO EBAY DATA",
            value="Could not find recent sold listings. Research required!",
            inline=False
        )
    
    # Price breakdown
    price_info = []
    price_info.append(f"🏷️ **Buy Price:** £{buy_price:.2f}")
    
    if ebay_data:
        price_info.append(f"📊 **eBay Median Sold:** £{ebay_data['median']:.2f}")
        price_info.append(f"📈 **eBay Average:** £{ebay_data['average']:.2f}")
        price_info.append(f"💵 **Range:** £{ebay_data['min']:.2f} - £{ebay_data['max']:.2f}")
    else:
        price_info.append(f"❌ **Resell Data:** Not available")
    
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
        source_text += f" | Data from {sold_count} eBay sales"
    alert.set_footer(text=source_text)
    
    return alert, profit

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
            alert_embed, profit = await create_alert_embed(embed, message)
            
            # Get role to ping
            role = message.guild.get_role(PING_ROLE_ID)
            
            # Determine alert level
            if profit > 50:
                alert_text = "🔥 **HIGH PROFIT DEAL!** 🔥"
            elif profit > 20:
                alert_text = "🚨 **New Deal Alert!**"
            elif profit > 0:
                alert_text = "💼 **Deal Detected**"
            else:
                alert_text = "ℹ️ **Product Alert** (Research Required)"
            
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
