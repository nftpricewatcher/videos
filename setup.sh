#!/bin/bash
# TG Cloud Setup Script

echo "📦 TG Cloud Setup"
echo "=================="

# Install dependencies
pip install telethon flask --break-system-packages

# Create .env template
cat > .env << 'EOF'
# Get these from https://my.telegram.org/apps
TG_API_ID=your_api_id_here
TG_API_HASH=your_api_hash_here

# Create a private channel in Telegram, get ID from web.telegram.org URL
# The ID should look like: -100xxxxxxxxxx
TG_CHANNEL_ID=-100xxxxxxxxxx
EOF

echo ""
echo "✅ Dependencies installed!"
echo ""
echo "NEXT STEPS:"
echo "==========="
echo ""
echo "1. Get Telegram API credentials:"
echo "   - Go to https://my.telegram.org/apps"
echo "   - Create an app, get API_ID and API_HASH"
echo ""
echo "2. Create a private Telegram channel:"
echo "   - Open Telegram, create a new private channel"
echo "   - Go to web.telegram.org, open your channel"
echo "   - URL will be: web.telegram.org/k/#-100XXXXXXXXXX"
echo "   - Copy the number starting with -100"
echo ""
echo "3. Edit .env file with your credentials"
echo ""
echo "4. Run the app:"
echo "   source .env && python app.py"
echo ""
echo "5. Open http://localhost:5000 in your browser"
echo ""
