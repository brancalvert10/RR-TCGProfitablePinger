# Discord Reselling Alert Bot 💰

Automated Discord bot that monitors product alerts and fetches real-time resell prices from eBay to calculate profit margins.

## Features

- 🎯 **Automated Profit Calculation** - Fetches real eBay sold listings to estimate resell value
- 📊 **Price Analysis** - Shows median, average, min, max from recent sales
- 🚨 **Smart Alerts** - Different alert levels based on profit margins
- 📱 **Mobile-Optimized** - Profit shown first for quick scanning
- 🔗 **Direct Links** - Includes original product links and eBay search

## Quick Deploy to Railway

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/template)

1. Click the button above
2. Add your environment variables (see below)
3. Deploy!

## Environment Variables

Set these in Railway or your `.env` file:

| Variable | Description | Required |
|----------|-------------|----------|
| `DISCORD_TOKEN` | Your Discord bot token | ✅ Yes |
| `EBAY_APP_ID` | Your eBay API App ID | ✅ Yes |
| `MONITORED_CHANNEL_ID` | Channel ID to monitor | ⚠️ Default: 1417115045573300244 |
| `PING_ROLE_ID` | Role ID to ping on alerts | ⚠️ Default: 1400527195679490319 |

## Setup Instructions

### 1. Create Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application"
3. Go to "Bot" section and create a bot
4. Enable these intents:
   - Message Content Intent
   - Server Members Intent
5. Copy the bot token

### 2. Get eBay API Key

1. Sign up at [eBay Developers](https://developer.ebay.com)
2. Create a new application
3. Copy your App ID (Client ID)

### 3. Invite Bot to Server

Use this URL (replace `YOUR_CLIENT_ID`):
```
https://discord.com/oauth2/authorize?client_id=YOUR_CLIENT_ID&permissions=274877908992&scope=bot
```

### 4. Deploy on Railway

1. Fork this repository
2. Connect to [Railway](https://railway.app)
3. Create new project from GitHub repo
4. Add environment variables in Railway dashboard
5. Deploy!

### 5. Local Development (Optional)

```bash
# Clone repo
git clone https://github.com/yourusername/discord-reselling-bot.git
cd discord-reselling-bot

# Install dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env
# Edit .env with your tokens

# Run bot
python bot.py
```

## How It Works

1. Bot monitors specific Discord channel for embeds
2. Extracts product name and buy price from embed
3. Searches eBay for recent completed sales
4. Calculates profit based on median sold price
5. Sends formatted alert with profit analysis
6. Pings specified role for notifications

## Alert Levels

- 🔥 **HIGH PROFIT** - £50+ profit
- 🚨 **Good Deal** - £20+ profit
- 💼 **Deal Detected** - Positive profit
- ℹ️ **Research Required** - No eBay data or minimal profit

## Example Output

```
@Resellers 🔥 HIGH PROFIT DEAL! 🔥

💰 Pokémon TCG Mega Evolution Elite Trainer Box

🎯 ESTIMATED PROFIT
🟢 £75.05 profit (45.7%)
Based on 8 recent eBay sales

📊 Price Analysis
🏷️ Buy Price: £164.95
📊 eBay Median Sold: £240.00
📈 eBay Average: £245.50
💵 Range: £220.00 - £280.00

📦 Product Info
Status: In-Stock
```

## Troubleshooting

### Bot not responding?
- Check bot has proper permissions in Discord
- Verify `MONITORED_CHANNEL_ID` is correct
- Check Railway logs for errors

### No eBay data?
- Verify `EBAY_APP_ID` is correct
- Product name might be too specific/generic
- eBay API might be rate-limited

### Wrong profit calculations?
- eBay median might not reflect true market value
- Consider manually checking recent sales
- Bot shows data source count for reliability

## Contributing

Pull requests welcome! Please follow existing code style.

## License

MIT License - feel free to use and modify!

## Support

Questions? Issues? Open a GitHub issue!
