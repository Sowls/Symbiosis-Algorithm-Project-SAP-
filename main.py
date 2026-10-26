import os
from dotenv import load_dotenv


load_dotenv()


TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID', '0'))
JSONBIN_ID = os.getenv('JSONBIN_ID')
JSONBIN_KEY = os.getenv('JSONBIN_KEY')
FINNHUB_KEY = os.getenv('FINNHUB_KEY')
