import os
import discord
from discord.ext import commands, tasks
import yfinance as yf
import pandas as pd
import asyncio
import nest_asyncio
import time
import random
import requests
import ccxt
import io
from flask import Flask
from threading import Thread
from datetime import datetime, timezone
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import xml.etree.ElementTree as ET
import finnhub
import numpy as np
from dotenv import load_dotenv
from ml_engine import ml_engine

load_dotenv()
nest_asyncio.apply()

print("⚡ Initialisation de Symbiosis Algorithm Trading V8.5 (100 Bots)...", flush=True)
analyzer = SentimentIntensityAnalyzer()
binance = ccxt.binance({'enableRateLimit': True})

# --- SERVEUR WEB (Render / Keep-Alive) ---
app = Flask('')
@app.route('/')
def home():
    return "🟢 Symbiosis Algorithm Trading V8.5 (100 Bots : Confirm, Retourn, Caméléon, ML, RL, Spécialistes, Méta) Online."
def run():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
def keep_alive():
    Thread(target=run, daemon=True).start()

# --- CONFIGURATION SÉCURISÉE (Variables d'environnement Render / .env) ---
TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID', '0'))
JSONBIN_ID = os.getenv('JSONBIN_ID')
JSONBIN_KEY = os.getenv('JSONBIN_KEY')
FINNHUB_KEY = os.getenv('FINNHUB_KEY')
finnhub_client = finnhub.Client(api_key=FINNHUB_KEY) if FINNHUB_KEY else None

# --- MARCHÉS ET RISQUE ---
ASSETS = {
    'Solana': 'SOL/USDT',
    'Bitcoin': 'BTC/USDT',
    'Or': 'GC=F',
    'Platine': 'PL=F',
    'Crude Oil': 'CL=F',
    'Argent': 'SI=F'
}

LEVERAGE_MAP = {
    'Solana': 10,
    'Bitcoin': 15,
    'Or': 20,
    'Platine': 15,
    'Crude Oil': 15,
    'Argent': 15
}

FRAIS_EXCHANGE = 0.0002   # 0.02% Maker fee
SPREAD = 0.0003           # 0.03%
SLIPPAGE = 0.0005         # 0.05%
FUNDING_RATE_DAY = 0.0006 # 0.06% / jour
COUT_PAR_LEG = FRAIS_EXCHANGE + SPREAD + SLIPPAGE  # 0.001 (0.10%) par leg

MARGIN_PER_TRADE = 0.25   # 25% du capital de base par trade
SIGNAL_THRESHOLD = 55     # Seuil d'entrée de base
INCUBATION_DAYS = 14      # 2 semaines d'observation avant l'entrée en chasse des Méta-Bots
COOLDOWN_SECONDS = 1800   # 30 minutes d'attente après un Stop-Loss sur le même actif

FINNHUB_SYMBOLS = {
    'Solana':    [],
    'Bitcoin':   [],
    'Or':        ['GLD', 'IAU', 'NEM'],
    'Platine':   ['PPLT', 'PLG'],
    'Crude Oil': ['USO', 'XOM', 'CVX'],
    'Argent':    ['SLV', 'SIVR'],
}

TICKER_TO_NAME = {v: k for k, v in ASSETS.items()}

RSS_FALLBACK = {
    'Solana':    'https://news.google.com/rss/search?q=Solana+SOL+crypto&hl=en&gl=US&ceid=US:en',
    'Bitcoin':   'https://news.google.com/rss/search?q=Bitcoin+BTC&hl=en&gl=US&ceid=US:en',
    'Or':        'https://news.google.com/rss/search?q=gold+price+XAU&hl=en&gl=US&ceid=US:en',
    'Platine':   'https://news.google.com/rss/search?q=platinum+price&hl=en&gl=US&ceid=US:en',
    'Crude Oil': 'https://news.google.com/rss/search?q=crude+oil+WTI+OPEC&hl=en&gl=US&ceid=US:en',
    'Argent':    'https://news.google.com/rss/search?q=silver+price+XAG&hl=en&gl=US&ceid=US:en',
}

FUTURES_ASSETS = {'Or', 'Platine', 'Crude Oil', 'Argent'}
CORREL_GROUPS = {
    'crypto': ['Bitcoin', 'Solana'],
    'precious_metals': ['Or', 'Argent', 'Platine'],
}


# =====================================================================
# GESTION DES HORAIRES ET PROTECTION ANTI-GAP DU VENDREDI SOIR
# =====================================================================
def is_market_open(asset_name: str) -> bool:
    if asset_name not in FUTURES_ASSETS:
        return True
    now_utc = datetime.now(timezone.utc)
    weekday = now_utc.weekday()  # 0=Lundi ... 4=Vendredi, 5=Samedi, 6=Dimanche
    hour = now_utc.hour
    if weekday == 4 and hour >= 22:
        return False
    if weekday == 5:
        return False
    if weekday == 6 and hour < 22:
        return False
    return True

def can_open_new_trade(asset_name: str, bot_name: str) -> bool:
    """
    1. Bloque les nouvelles entrées sur Futures le vendredi dès 19h00 UTC (évite le piège du week-end).
    2. Bloque la 1ère heure de réouverture le dimanche (22h00 - 23h00 UTC : spreads trop larges).
    3. Applique le filtre horaire institutionnel (Londres / NY) pour les bots Killzone.
    """
    now_utc = datetime.now(timezone.utc)
    weekday = now_utc.weekday()
    hour = now_utc.hour

    if asset_name in FUTURES_ASSETS:
        if weekday == 4 and hour >= 19:
            return False  # Plus d'entrée vendredi soir après 19h UTC
        if weekday == 6 and hour < 23:
            return False  # Gel pendant la 1ère heure de réouverture dimanche soir

    # Filtre spécial pour les bots Killzone (08h-11h UTC Londres & 13h-16h UTC New York)
    if "Killzone" in bot_name:
        if not ((8 <= hour < 11) or (13 <= hour < 16)):
            return False

    return True

def is_friday_pre_close_window(asset_name: str) -> bool:
    """Vendredi entre 21h00 et 21h59 UTC : fenêtre de protection avant fermeture des marchés Futures."""
    if asset_name not in FUTURES_ASSETS:
        return False
    now_utc = datetime.now(timezone.utc)
    return now_utc.weekday() == 4 and now_utc.hour == 21


intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)
bot.remove_command('help')

def create_pb(value, min_val, max_val, length=10):
    value = max(min_val, min(value, max_val))
    percent = (value - min_val) / (max_val - min_val) if max_val > min_val else 0
    return "█" * int(length * percent) + "░" * (length - int(length * percent))


# =====================================================================
# GÉNÉRATION DES 100 BOTS V8.5 (AVEC LES NOUVELLES ARCHÉTYPES ADAPTATIFS)
# =====================================================================
TRADER_PROFILES = {}
BOT_META = {}

def register_bot(name, weights, mode, famille, stars_val, desc, meta_type=None, lr=0.0, special=None):
    TRADER_PROFILES[name] = dict(weights)
    BOT_META[name] = {
        "stars": stars_val,
        "famille": famille,
        "mode": mode,          # 'CONFIRM', 'RETOURN', 'CAMELEON', 'META', 'TEMOIN'
        "desc": desc,
        "meta_type": meta_type,
        "lr": lr,              # Learning rate > 0 pour les bots RL auto-adaptatifs
        "special": special     # 'PULLBACK', 'SQUEEZE', 'STOPHUNT', 'SPECIALIST', 'AUTOTHRESH', 'KILLZONE'
    }

# ── 1. FAMILLE CONFIRMATION & STRUCTURE (22 Bots : Tendance, Pullback MTF, Squeeze, Killzone) ──
CONFIRM_SPECS = [
    ("Tendance_Douce_Confirm",      {"ema":0.35,"macd":0.25,"rsi":0.20,"news":0.15,"stoch":0.05}, 4.5, None, "Suit la tendance 1h avec validation momentum 5m."),
    ("Opti_Data_Driven_Confirm",    {"ema":0.25,"macd":0.25,"rsi":0.25,"news":0.25}, 5.0, None, "Équilibre 4 piliers en mode confirmation."),
    ("Ichimoku_Cloud_Confirm",      {"ichimoku":0.50,"ema":0.25,"macd":0.15,"news":0.10}, 4.5, None, "Cassure du nuage Ichimoku + croisement Tenkan/Kijun."),
    ("Ichimoku_MACD_Confirm",       {"ichimoku":0.45,"macd":0.35,"ema":0.20}, 5.0, None, "Structure temporelle Ichimoku + accélération MACD."),
    ("Supertrend_Pure_Confirm",     {"supertrend":0.45,"ema":0.30,"macd":0.25}, 4.5, None, "Vrai Supertrend ATR + tendance macro."),
    ("OBV_Flow_Confirm",            {"obv":0.45,"ema":0.30,"macd":0.25}, 4.5, None, "Suit l'accumulation des volumes dans le sens de la tendance."),
    ("VWAP_Breakout_Confirm",       {"vwap":0.40,"ema":0.30,"macd":0.20,"obv":0.10}, 4.5, None, "Impulsion au-dessus du VWAP journalier."),
    ("Kelly_Trend_Confirm",         {"ema":0.35,"supertrend":0.25,"macd":0.25,"news":0.15}, 5.0, None, "Demi-Kelly mathématique sur tendance claire."),
    ("Kelly_Confluence_Confirm",    {"ema":0.25,"ichimoku":0.25,"macd":0.25,"obv":0.25}, 5.0, None, "Sizing Kelly sur quadruple confirmation."),
    ("Triple_Trend_Confirm",        {"ema":0.35,"ichimoku":0.35,"supertrend":0.30}, 5.0, None, "Triple verrou : EMA + Ichimoku + Supertrend."),
    # Nouveaux : Pullback Multi-Timeframe (Achète les replis 5m dans une tendance 1h haussière)
    ("MTF_Gold_Pullback_Confirm",   {"pullback":0.55,"ema":0.25,"obv":0.20}, 5.0, "PULLBACK", "Achète uniquement les replis RSI 5m dans le sens de la tendance 1h."),
    ("MTF_Fiber_Pullback_Confirm",  {"pullback":0.50,"supertrend":0.30,"vwap":0.20}, 5.0, "PULLBACK", "Combine tendance 1h Supertrend et respiration court terme."),
    ("MTF_Volume_Pullback_Confirm", {"pullback":0.45,"obv":0.35,"macd":0.20}, 5.0, "PULLBACK", "Repli 5m soutenu par un flux de volume OBV positif."),
    ("MTF_Smart_Pullback_Confirm",  {"pullback":0.50,"ichimoku":0.30,"news":0.20}, 4.5, "PULLBACK", "Pullback sur tendance Ichimoku et catalyseur news."),
    # Nouveaux : Volatility Squeeze (Compression Bollinger dans Keltner puis explosion)
    ("Keltner_Squeeze_Confirm",     {"squeeze":0.55,"macd":0.25,"obv":0.20}, 5.0, "SQUEEZE", "Détecte les compressions extrêmes de volatilité et prend l'explosion."),
    ("Bollinger_Blast_Squeeze_Confirm", {"squeeze":0.50,"ema":0.30,"supertrend":0.20}, 5.0, "SQUEEZE", "Chasseur de réveil de volatilité post-consolidation."),
    ("Apex_Coiled_Squeeze_Confirm", {"squeeze":0.45,"obv":0.35,"ml":0.20}, 5.0, "SQUEEZE", "Ressort comprimé validé par les volumes et le ML."),
    # Nouveaux : Killzones Horaires (Londres 08h-11h & NY 13h-16h UTC)
    ("London_Open_Killzone_Confirm",{"ema":0.35,"vwap":0.35,"obv":0.30}, 4.5, "KILLZONE", "Ne trade que pendant les ouvertures institutionnelles Londres/NY."),
    ("NY_WallStreet_Killzone_Confirm",{"macd":0.35,"supertrend":0.35,"vwap":0.30}, 5.0, "KILLZONE", "Capte le flux directionnel de Wall Street (13h-16h UTC)."),
    ("Instit_Flow_Killzone_Confirm",{"ichimoku":0.40,"obv":0.35,"ml":0.25}, 5.0, "KILLZONE", "Haute liquidité uniquement : évite 100% du bruit nocturne."),
    # Nouveaux : Spécialistes par Actif (Mémorisent leurs actifs gagnants)
    ("Asset_Master_Specialist_Confirm", {"ema":0.30,"macd":0.30,"supertrend":0.20,"obv":0.20}, 5.0, "SPECIALIST", "Augmente ses mises sur ses actifs gagnants et boycotte ses actifs perdants."),
    ("Sector_Hunter_Specialist_Confirm",{"ichimoku":0.35,"vwap":0.35,"ml":0.30}, 5.0, "SPECIALIST", "Sélectionne automatiquement ses marchés de prédilection."),
]
for n, w, s, spec, d in CONFIRM_SPECS:
    register_bot(n, w, "CONFIRM", "Confirmation", s, d, special=spec)

# ── 2. FAMILLE RETOURNEMENT & CHASSEURS DE LIQUIDITÉ (18 Bots : Avec Filtre Anti-Couteau) ──
RETOURN_SPECS = [
    ("RSI_Extreme_Retourn",         {"rsi":0.55,"bb":0.25,"stoch":0.20}, 4.5, None, "Achète la survente confirmée par bougie de rejet."),
    ("Bollinger_Fade_Retourn",      {"bb":0.50,"rsi":0.30,"stoch":0.20}, 4.5, None, "Rebond élastique sur les bandes de Bollinger extrêmes."),
    ("VWAP_Bounce_Retourn",         {"vwap":0.50,"rsi":0.30,"bb":0.20}, 4.5, None, "Ramène le prix vers son VWAP journalier après un excès."),
    ("OBV_Divergence_Retourn",      {"obv":0.50,"rsi":0.30,"bb":0.20}, 4.5, None, "Détecte les vraies divergences Prix vs Volume OBV."),
    ("Williams_Snap_Retourn",       {"williams":0.50,"rsi":0.25,"stoch":0.25}, 4.0, None, "Exploite les zones extrêmes de Williams %R (-80 / -20)."),
    ("Double_Band_Retourn",         {"bb":0.45,"vwap":0.45,"rsi":0.10}, 4.5, None, "Double élastique statistique : Bollinger + écart VWAP."),
    ("Exhaustion_Hunter_Retourn",   {"rsi":0.35,"stoch":0.35,"obv":0.30}, 4.5, None, "Repère l'essoufflement des mouvements avec divergence OBV."),
    ("Mean_Revert_Pure_Retourn",    {"vwap":0.40,"bb":0.40,"williams":0.20}, 4.5, None, "Retour à la moyenne statistique en marché calme."),
    ("Z_Score_Sniper_Retourn",      {"bb":0.60,"rsi":0.25,"vwap":0.15}, 4.5, None, "Entre uniquement à plus de 2 écarts-types de la moyenne."),
    ("Value_Zone_Retourn",          {"vwap":0.55,"obv":0.25,"rsi":0.20}, 4.5, None, "Défend la zone de valeur institutionnelle VWAP."),
    ("Swing_Reversal_Retourn",      {"rsi":0.30,"bb":0.30,"vwap":0.20,"obv":0.20}, 4.5, None, "Confluence complète de retournement à 4 facteurs."),
    # Nouveaux : Chasseurs de Liquidité / Stop-Hunt (Fausses cassures avec longues mèches)
    ("Wick_Sniper_StopHunt_Retourn",{"stophunt":0.60,"rsi":0.20,"obv":0.20}, 5.0, "STOPHUNT", "Entre sur les longues mèches qui balayent les stops puis réintègrent le support."),
    ("Liquidity_Trap_StopHunt_Retourn",{"stophunt":0.55,"bb":0.25,"vwap":0.20}, 5.0, "STOPHUNT", "Exploite les fausses cassures (Bull/Bear traps) de 20 bougies."),
    ("Whale_Absorption_StopHunt_Retourn",{"stophunt":0.50,"obv":0.35,"williams":0.15}, 5.0, "STOPHUNT", "Repère l'absorption des liquidations par les baleines."),
    ("Fakeout_Master_StopHunt_Retourn",{"stophunt":0.55,"stoch":0.25,"ml":0.20}, 5.0, "STOPHUNT", "Combine rejet sur mèche extrême et validation ML."),
    # Nouveaux : Spécialistes & Killzone Retournement
    ("Reversal_Specialist_Retourn", {"vwap":0.40,"bb":0.35,"rsi":0.25}, 5.0, "SPECIALIST", "Joue les retournements uniquement sur les actifs où son WR est élevé."),
    ("MeanRevert_Specialist_Retourn",{"stophunt":0.40,"obv":0.30,"rsi":0.30}, 5.0, "SPECIALIST", "Spécialiste adaptatif des rebonds sur mèches par actif."),
    ("London_Fade_Killzone_Retourn",{"stophunt":0.45,"vwap":0.35,"rsi":0.20}, 4.5, "KILLZONE", "Prend le contre-pied des fausses cassures d'ouverture de session."),
]
for n, w, s, spec, d in RETOURN_SPECS:
    register_bot(n, w, "RETOURN", "Retournement", s, d, special=spec)

# ── 3. FAMILLE CAMÉLÉON (15 Bots : Confirmation si ADX >= 25, Retournement si ADX < 25) ──
CAMELEON_SPECS = [
    ("Proteus_Alpha_Cameleon",      {"ema":0.25,"macd":0.25,"rsi":0.25,"bb":0.25}, 5.0, None, "Bascule entre suivi EMA/MACD (ADX>=25) et rebond RSI/BB (ADX<25)."),
    ("Morph_Instit_Cameleon",       {"vwap":0.35,"obv":0.35,"ema":0.15,"rsi":0.15}, 5.0, None, "VWAP/OBV en cassure en tendance, et en rebond en range."),
    ("Regime_Master_Cameleon",      {"supertrend":0.30,"macd":0.20,"rsi":0.25,"bb":0.25}, 5.0, None, "Supertrend en marché directionnel, Bollinger/RSI en range."),
    ("ADX_Shifter_Cameleon",        {"ichimoku":0.30,"ema":0.20,"williams":0.25,"stoch":0.25}, 4.5, None, "Ichimoku en tendance, Williams/Stoch en consolidation."),
    ("Dual_Brain_Cameleon",         {"ema":0.20,"macd":0.20,"vwap":0.30,"rsi":0.30}, 5.0, None, "Double cerveau quantitatif adaptatif selon le régime ADX."),
    ("Quantum_Switch_Cameleon",     {"supertrend":0.25,"ichimoku":0.25,"bb":0.25,"obv":0.25}, 5.0, None, "Inverse sa lecture des bandes et du volume en range."),
    ("Adaptive_Kelly_Cameleon",     {"ema":0.25,"macd":0.25,"rsi":0.20,"bb":0.20,"news":0.10}, 5.0, None, "Combine le sizing Demi-Kelly avec le changement de régime ADX."),
    ("Mirage_Tactique_Cameleon",    {"pullback":0.35,"macd":0.20,"stophunt":0.25,"rsi":0.20}, 5.0, None, "Pullback en tendance (ADX>=25), Chasse aux mèches en range (ADX<25)."),
    ("Janus_Bidirection_Cameleon",  {"squeeze":0.35,"supertrend":0.20,"bb":0.25,"vwap":0.20}, 5.0, None, "Squeeze/Supertrend en tendance, retour VWAP en range."),
    ("Vortex_Regime_Cameleon",      {"ichimoku":0.25,"macd":0.25,"vwap":0.25,"rsi":0.25}, 4.5, None, "Capte tous les états du marché sans jamais rester bloqué."),
    ("Synapse_Flex_Cameleon",       {"ema":0.20,"obv":0.30,"bb":0.25,"williams":0.25}, 4.5, None, "Lit le flux OBV en confirmation ou en divergence."),
    ("Horizon_Switch_Cameleon",     {"ema":0.30,"news":0.20,"rsi":0.25,"vwap":0.25}, 4.5, None, "Intègre les news en tendance et joue la valeur VWAP en range."),
    ("Prism_Specialist_Cameleon",   {"supertrend":0.20,"macd":0.20,"bb":0.20,"rsi":0.20,"vwap":0.20}, 5.0, "SPECIALIST", "Caméléon ADX doublé d'une mémoire de rentabilité par actif."),
    ("Killzone_Elite_Cameleon",     {"ema":0.25,"vwap":0.25,"stophunt":0.25,"obv":0.25}, 5.0, "KILLZONE", "Caméléon actif uniquement pendant les heures Londres/NY."),
    ("Omni_Weather_Cameleon",       {"ema":0.20,"macd":0.20,"rsi":0.20,"bb":0.20,"ml":0.20}, 5.0, None, "All-Weather : combine régime ADX et prédiction ML."),
]
for n, w, s, spec, d in CAMELEON_SPECS:
    register_bot(n, w, "CAMELEON", "Caméléon", s, d, special=spec)

# ── 4. FAMILLE MACHINE LEARNING (15 Bots : Exploitent le GradientBoosting V8.5) ──
ML_SPECS = [
    ("ML_Pur_Sniper_Confirm",       {"ml":1.00}, "CONFIRM", 5.0, None, "100% piloté par les probabilités du GradientBoosting V8.5."),
    ("ML_Trend_Leader_Confirm",     {"ml":0.55,"ema":0.25,"macd":0.20}, "CONFIRM", 5.0, None, "Le ML dirige, l'EMA et le MACD valident la tendance."),
    ("ML_Pullback_Pro_Confirm",     {"ml":0.50,"pullback":0.35,"obv":0.15}, "CONFIRM", 5.0, "PULLBACK", "Combine prédiction ML et achat sur repli dans la tendance 1h."),
    ("ML_Squeeze_Break_Confirm",    {"ml":0.50,"squeeze":0.35,"macd":0.15}, "CONFIRM", 5.0, "SQUEEZE", "Déclenche sur compression de volatilité validée par l'IA."),
    ("ML_Volume_Flow_Confirm",      {"ml":0.50,"obv":0.30,"vwap":0.20}, "CONFIRM", 4.5, None, "Le ML combiné aux flux de volumes institutionnels."),
    ("ML_Macro_News_Confirm",       {"ml":0.50,"news":0.30,"ema":0.20}, "CONFIRM", 4.5, None, "Combine l'IA prédictive et le sentiment des actualités."),
    ("ML_Kelly_Master_Confirm",     {"ml":0.60,"ema":0.20,"macd":0.20}, "CONFIRM", 5.0, None, "Signal ML dominant avec gestion de mise Demi-Kelly."),
    ("ML_Killzone_Sniper_Confirm",  {"ml":0.55,"vwap":0.25,"obv":0.20}, "CONFIRM", 5.0, "KILLZONE", "IA active uniquement sur les sessions de Londres et New York."),
    ("ML_Contre_Exces_Retourn",     {"ml":0.50,"rsi":0.25,"bb":0.25}, "RETOURN", 5.0, None, "Joue les retournements uniquement quand le ML confirme le rebond."),
    ("ML_StopHunt_Sniper_Retourn",  {"ml":0.50,"stophunt":0.35,"obv":0.15}, "RETOURN", 5.0, "STOPHUNT", "Détecte les chasses aux stops avec validation probabiliste ML."),
    ("ML_VWAP_Revert_Retourn",      {"ml":0.45,"vwap":0.35,"rsi":0.20}, "RETOURN", 4.5, None, "Retour au VWAP validé par la probabilité ML à 30 min."),
    ("ML_Divergence_Retourn",       {"ml":0.45,"obv":0.35,"williams":0.20}, "RETOURN", 4.5, None, "Divergence de volume OBV appuyée par le modèle ML."),
    ("ML_Proteus_Cameleon",         {"ml":0.50,"ema":0.25,"rsi":0.25}, "CAMELEON", 5.0, None, "50% ML + 50% Caméléon ADX (Tendance ou Rebond)."),
    ("ML_Specialist_Cameleon",      {"ml":0.45,"supertrend":0.20,"stophunt":0.20,"obv":0.15}, "CAMELEON", 5.0, "SPECIALIST", "IA Caméléon qui sélectionne ses meilleurs actifs."),
    ("ML_AutoThresh_Cameleon",      {"ml":0.55,"vwap":0.25,"obv":0.20}, "CAMELEON", 5.0, "AUTOTHRESH", "IA dont le seuil d'exigence augmente automatiquement après une perte."),
]
for n, w, m, s, spec, d in ML_SPECS:
    register_bot(n, w, m, "Machine Learning", s, d, special=spec)

# ── 5. FAMILLE AUTO-ADAPTATIVE RL (15 Bots : Apprennent leurs poids + Seuil Dynamique) ──
RL_SPECS = [
    ("RL_Explorer_Fast_Confirm",    {"ema":0.20,"macd":0.20,"supertrend":0.20,"obv":0.20,"ml":0.20}, "CONFIRM", 0.12, None, "Apprentissage rapide (LR=12%) en mode Confirmation."),
    ("RL_Conservative_Confirm",     {"ema":0.25,"macd":0.25,"ichimoku":0.20,"rsi":0.15,"news":0.15}, "CONFIRM", 0.05, None, "Ajuste doucement ses poids (LR=5%) après chaque trade."),
    ("RL_Pullback_Learner_Confirm", {"pullback":0.30,"ema":0.25,"obv":0.25,"ml":0.20}, "CONFIRM", 0.10, "PULLBACK", "Apprend par renforcement à doser ses entrées sur repli."),
    ("RL_Squeeze_Mutant_Confirm",   {"squeeze":0.30,"supertrend":0.25,"macd":0.25,"obv":0.20}, "CONFIRM", 0.10, "SQUEEZE", "Optimise ses poids sur les sorties de compression."),
    ("RL_Volume_Specialist_Confirm",{"obv":0.30,"vwap":0.30,"macd":0.20,"ema":0.20}, "CONFIRM", 0.08, "SPECIALIST", "Double adaptation : ajuste ses poids ET sélectionne ses actifs."),
    ("RL_AutoThresh_Confirm",       {"ema":0.25,"supertrend":0.25,"obv":0.25,"ml":0.25}, "CONFIRM", 0.08, "AUTOTHRESH", "Adapte ses poids ET relève son seuil d'entrée en cas d'échec."),
    ("RL_Killzone_Adapt_Confirm",   {"vwap":0.30,"obv":0.30,"ema":0.20,"ml":0.20}, "CONFIRM", 0.10, "KILLZONE", "Apprentissage par renforcement concentré sur Londres/NY."),
    ("RL_Balanced_Confirm",         {"ema":0.15,"macd":0.15,"pullback":0.20,"ichimoku":0.15,"obv":0.15,"ml":0.20}, "CONFIRM", 0.08, None, "Part d'un profil équilibré et forge sa spécialité."),
    ("RL_Reversal_Fast_Retourn",    {"rsi":0.25,"bb":0.25,"vwap":0.25,"obv":0.25}, "RETOURN", 0.12, None, "Apprentissage rapide (LR=12%) sur les retournements."),
    ("RL_StopHunt_Learner_Retourn", {"stophunt":0.35,"vwap":0.25,"obv":0.20,"rsi":0.20}, "RETOURN", 0.10, "STOPHUNT", "Apprend à identifier les meilleures mèches de liquidation."),
    ("RL_AutoThresh_Retourn",       {"stophunt":0.30,"bb":0.25,"vwap":0.25,"ml":0.20}, "RETOURN", 0.08, "AUTOTHRESH", "Devient ultra-sélectif après un Stop-Loss en mode retournement."),
    ("RL_Specialist_Retourn",       {"rsi":0.25,"stophunt":0.25,"bb":0.25,"vwap":0.25}, "RETOURN", 0.10, "SPECIALIST", "Mémorise les actifs propices au retour à la moyenne."),
    ("RL_Omni_Brain_Cameleon",      {"ema":0.20,"pullback":0.15,"stophunt":0.15,"bb":0.15,"vwap":0.15,"ml":0.20}, "CAMELEON", 0.08, None, "Caméléon ADX qui réécrit ses propres poids après chaque trade."),
    ("RL_Apex_Predator_Cameleon",   {"squeeze":0.20,"supertrend":0.20,"stophunt":0.20,"obv":0.20,"ml":0.20}, "CAMELEON", 0.10, "AUTOTHRESH", "Caméléon + RL + Seuil dynamique auto-ajusté."),
    ("RL_Kelly_Master_Cameleon",    {"ema":0.25,"macd":0.20,"bb":0.20,"vwap":0.15,"ml":0.20}, "CAMELEON", 0.07, "SPECIALIST", "Combine Demi-Kelly, Caméléon ADX, Mémoire d'actif et RL."),
]
for n, w, m, lr_val, spec, d in RL_SPECS:
    register_bot(n, w, m, "Auto-Adaptatif RL", 5.0, d, lr=lr_val, special=spec)

# ── 6. FAMILLE MÉTA-ESSAIM & CORRÉLATION (12 Bots : Incubation 14 jours puis chasse !) ──
META_SPECS = [
    ("Crowd_Top10_Meta_Confirm",        "TOP10_FOLLOW",     "Suiveur du Mouvement de Foule : entre quand >= 6 bots du Top 10 convergent."),
    ("Elite_Top5_Sniper_Meta_Confirm",  "TOP5_FOLLOW",      "Copie uniquement le consensus fort (>= 3/5) du Top 5 général."),
    ("Fade_Bottom5_Meta_Retourn",       "FADE_BOTTOM5",     "Prend l'exact opposé des 5 pires bots du classement (quand >= 3/5 convergent) !"),
    ("Fade_Bottom10_Meta_Retourn",      "FADE_BOTTOM10",    "Inverse la foule des 10 bots les moins performants du fonds."),
    ("Darwin_Top3_Clone_Meta_Confirm",  "DARWIN_TOP3",      "Hybride en temps réel les décisions des 3 meilleurs bots du moment."),
    ("Correl_Confirm_ML_Meta_Confirm",  "CORREL_CONF_ML",   "Entre si la famille Confirmation ET la famille ML sont d'accord."),
    ("Correl_Retourn_ML_Meta_Retourn",  "CORREL_RET_ML",    "Entre si la famille Retournement ET la famille ML convergent."),
    ("Correl_RL_Cameleon_Meta_Confirm", "CORREL_RL_CAM",    "Croise l'intelligence des bots RL avec les bots Caméléons."),
    ("Consensus_Global_Meta_Confirm",   "GLOBAL_FOLLOW",    "Suit le consensus de l'ensemble des 100 bots quand > 65% convergent."),
    ("Contrarien_Foule_Meta_Retourn",   "GLOBAL_FADE",      "Vend l'euphorie collective quand > 75% de tous les bots sont du même côté."),
    ("Hot_Hand_Tracker_Meta_Confirm",   "WINRATE_LEADERS",  "Suit les 5 bots ayant le meilleur Winrate (minimum 6 trades)."),
    ("Alpha_Spread_Meta_Confirm",       "TOP10_VS_BOT10",   "Mesure l'écart de conviction entre le Top 10 et le Bottom 10."),
]
for n, m_type, d in META_SPECS:
    register_bot(n, {}, "META", "Méta-Essaim", 5.0, d, meta_type=m_type)

# ── 7. FAMILLE TÉMOINS SCIENTIFIQUES (3 Bots : Baseline) ──
register_bot("Singe_Aleatoire_Temoin", {}, "TEMOIN", "Témoin", 0.5, "Score 100% aléatoire. La baseline scientifique.")
register_bot("Le_Permabull_Temoin",    {}, "TEMOIN", "Témoin", 1.0, "Toujours LONG (+100%). Référence marché haussier.")
register_bot("Le_Permabear_Temoin",    {}, "TEMOIN", "Témoin", 1.0, "Toujours SHORT (-100%). Référence marché baissier.")


def get_stars_display(name):
    meta = BOT_META.get(name, {})
    n = meta.get("stars", 2.5)
    full = int(n)
    half = 1 if (n - full) >= 0.5 else 0
    return "⭐" * full + ("✨" if half else "") + f" ({n}/5)"

def get_bot_info(name):
    meta = BOT_META.get(name, {"stars": 2.5, "famille": "Inconnu", "desc": "Aucune description."})
    return get_stars_display(name), meta["famille"], meta["desc"]


# =====================================================================
# ÉTAT DU PORTEFEUILLE, MÉMOIRE ADAPTATIVE & TRADER HUMAIN
# =====================================================================
paper_portfolio = {
    n: {
        'capital': 300.0,
        'initial_capital': 300.0,
        'peak_capital': 300.0,
        'max_drawdown': 0.0,
        'trades': 0,
        'wins': 0,
        'total_fees': 0.0,
        'positions': {},
        'custom_weights': dict(TRADER_PROFILES[n]) if BOT_META[n]['lr'] > 0 else {},
        'dynamic_threshold': float(SIGNAL_THRESHOLD), # Pour les bots AUTOTHRESH
        'asset_stats': {},                            # {asset: {'wins': 0, 'trades': 0, 'pnl': 0.0}} pour SPECIALIST
        'cooldowns': {}                               # {asset: timestamp_until_allowed} anti-revenge trading
    }
    for n in TRADER_PROFILES.keys()
}

meta_state = {
    'experiment_start_time': time.time(),
    'hunt_opened_alert_sent': False,
    'last_crowd_alert': {}
}

HUMAN_NAME = "👤 Vous"
human_trader = {
    'capital': 300.0,
    'initial_capital': 300.0,
    'peak_capital': 300.0,
    'max_drawdown': 0.0,
    'trades': 0,
    'wins': 0,
    'total_fees': 0.0,
    'positions': {},
    'trade_history': [],
}


# =====================================================================
# APPRENTISSAGE PAR L'EXPÉRIENCE (RL + MÉMOIRE D'ACTIF + SEUIL DYNAMIQUE)
# =====================================================================
def record_bot_experience(bot_name: str, asset_name: str, signals_snapshot: dict, trade_type: str, profit: float, is_sl: bool):
    """
    Met à jour toute l'expérience du bot après un trade :
    1. Cooldown de 30 min sur l'actif si Stop-Loss touché.
    2. Statistiques par actif (pour les bots SPECIALIST).
    3. Ajustement du seuil d'exigence (pour les bots AUTOTHRESH).
    4. Ajustement des coefficients (pour les bots RL).
    """
    p = paper_portfolio[bot_name]
    meta = BOT_META.get(bot_name, {})

    # 1. Cooldown Anti-Revenge Trading si SL touché
    if is_sl and profit < 0:
        p.setdefault('cooldowns', {})[asset_name] = time.time() + COOLDOWN_SECONDS

    # 2. Mémoire par actif (Asset Specialist)
    ast_stats = p.setdefault('asset_stats', {}).setdefault(asset_name, {'wins': 0, 'trades': 0, 'pnl': 0.0})
    ast_stats['trades'] += 1
    ast_stats['pnl'] = round(ast_stats.get('pnl', 0.0) + profit, 2)
    if profit > 0:
        ast_stats['wins'] += 1

    # 3. Seuil d'entrée dynamique (Auto-Threshold)
    cur_thresh = p.get('dynamic_threshold', float(SIGNAL_THRESHOLD))
    if meta.get('special') == 'AUTOTHRESH' or meta.get('lr', 0) > 0:
        if profit > 0:
            # Redescend doucement vers 52% quand il gagne
            p['dynamic_threshold'] = max(52.0, round(cur_thresh - 2.0, 1))
        else:
            # Monte son exigence (+4%) après une perte pour couper les séries perdantes (max 78%)
            p['dynamic_threshold'] = min(78.0, round(cur_thresh + 4.0, 1))

    # 4. Mise à jour des poids RL (Online Policy Gradient)
    lr = meta.get('lr', 0.0)
    if lr <= 0 or not signals_snapshot:
        return

    weights = p.get('custom_weights') or dict(TRADER_PROFILES[bot_name])
    if not weights:
        return

    direction = 1.0 if trade_type == 'LONG' else -1.0
    reward_sign = 1.0 if profit > 0 else -1.0

    new_weights = {}
    for k, w in weights.items():
        sig_val = signals_snapshot.get(k, 0.0)
        alignment = sig_val * direction
        delta = lr * reward_sign * alignment
        new_weights[k] = max(0.03, min(0.65, w + delta))

    total_w = sum(new_weights.values())
    if total_w > 0:
        new_weights = {k: round(v / total_w, 4) for k, v in new_weights.items()}
        p['custom_weights'] = new_weights
        TRADER_PROFILES[bot_name] = dict(new_weights)


# =====================================================================
# SAUVEGARDE ET CHARGEMENT JSONBIN
# =====================================================================
async def load_portfolio():
    global paper_portfolio, human_trader, meta_state
    if not JSONBIN_ID or not JSONBIN_KEY:
        print("⚠️ Clés JSONBin manquantes dans les variables d'environnement.", flush=True)
        return
    try:
        r = await asyncio.wait_for(
            asyncio.to_thread(
                requests.get,
                f"https://api.jsonbin.io/v3/b/{JSONBIN_ID}",
                headers={'X-Master-Key': JSONBIN_KEY},
                timeout=8
            ),
            timeout=12
        )
        if r.status_code == 200:
            data = r.json().get('record', {})
            for p_name, s in data.items():
                if p_name in paper_portfolio and isinstance(s, dict):
                    paper_portfolio[p_name].update(s)
                    if paper_portfolio[p_name].get('custom_weights'):
                        TRADER_PROFILES[p_name] = dict(paper_portfolio[p_name]['custom_weights'])
            if '__human__' in data:
                human_trader.update(data['__human__'])
            if '__meta__' in data:
                meta_state.update(data['__meta__'])
            print(f"🟢 Portfolio V8.5 ({len(paper_portfolio)} bots) chargé depuis JSONBin.", flush=True)
        else:
            print(f"⚠️ JSONBin load HTTP {r.status_code}", flush=True)
    except Exception as e:
        print(f"⚠️ Erreur DB load : {e}", flush=True)

async def save_portfolio():
    if not JSONBIN_ID or not JSONBIN_KEY:
        return
    try:
        payload = dict(paper_portfolio)
        payload['__human__'] = human_trader
        payload['__meta__'] = meta_state
        await asyncio.wait_for(
            asyncio.to_thread(
                requests.put,
                f"https://api.jsonbin.io/v3/b/{JSONBIN_ID}",
                json=payload,
                headers={'Content-Type': 'application/json', 'X-Master-Key': JSONBIN_KEY},
                timeout=8
            ),
            timeout=12
        )
    except Exception as e:
        print(f"⚠️ Erreur DB save : {e}", flush=True)


# =====================================================================
# ACTUALITÉS : FINNHUB + GOOGLE NEWS RSS
# =====================================================================
def _rss_fetch(url: str, max_items: int = 5) -> list:
    results = []
    try:
        headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/rss+xml, */*'}
        resp = requests.get(url, headers=headers, timeout=6)
        if resp.status_code != 200:
            return []
        root = ET.fromstring(resp.content)
        for item in root.findall('.//item')[:max_items]:
            title_el = item.find('title')
            link_el  = item.find('link')
            title = title_el.text.strip() if title_el is not None and title_el.text else ''
            link  = link_el.text.strip()  if link_el  is not None and link_el.text  else ''
            if title and link:
                results.append({'title': title, 'link': link})
    except Exception:
        pass
    return results

def fetch_news_safe(ticker_str: str) -> list:
    asset_name = TICKER_TO_NAME.get(ticker_str)
    if not asset_name:
        return []
    results = []
    seen_titles = set()
    symbols = FINNHUB_SYMBOLS.get(asset_name, [])
    if finnhub_client:
        for sym in symbols:
            try:
                from datetime import datetime as _dt, timedelta as _td
                _today = _dt.now().strftime('%Y-%m-%d')
                _week  = (_dt.now() - _td(days=7)).strftime('%Y-%m-%d')
                news = finnhub_client.company_news(sym, _from=_week, to=_today)
                for item in (news or [])[:4]:
                    title = (item.get('headline') or '').strip()
                    link  = (item.get('url') or '').strip()
                    if title and link and title not in seen_titles:
                        seen_titles.add(title)
                        results.append({'title': title, 'link': link})
                    if len(results) >= 6:
                        break
            except Exception:
                pass
            if len(results) >= 6:
                break
    if not results:
        rss_url = RSS_FALLBACK.get(asset_name)
        if rss_url:
            for item in _rss_fetch(rss_url, max_items=6):
                if item['title'] not in seen_titles:
                    seen_titles.add(item['title'])
                    results.append(item)
    return results


# =====================================================================
# INDICATEURS ET FILTRES FINANCIERS V8.5
# =====================================================================
def score_rsi_retournement(rsi_val: float) -> float:
    if rsi_val <= 22: return 1.0
    elif rsi_val <= 38: return (38 - rsi_val) / 16.0
    elif rsi_val >= 78: return -1.0
    elif rsi_val >= 62: return -(rsi_val - 62) / 16.0
    return 0.0

def score_rsi_confirmation(rsi_val: float) -> float:
    if 52 <= rsi_val <= 72:
        return (rsi_val - 50) / 22.0
    elif rsi_val > 72:
        return 0.2
    elif 28 <= rsi_val <= 48:
        return (rsi_val - 50) / 22.0
    elif rsi_val < 28:
        return -0.2
    return 0.0

def score_stoch_retournement(stoch_val: float) -> float:
    if stoch_val <= 20: return 1.0 - (stoch_val / 20.0) * 0.5
    elif stoch_val >= 80: return -0.5 - ((stoch_val - 80) / 20.0) * 0.5
    return 0.0

def score_stoch_confirmation(stoch_val: float) -> float:
    return max(-1.0, min(1.0, (stoch_val - 50.0) / 40.0))

def atr_is_favorable(atr: float, prix: float, asset_name: str) -> bool:
    if prix <= 0 or atr <= 0:
        return False
    atr_pct = (atr / prix) * 100
    if asset_name in ('Bitcoin', 'Solana'):
        return 0.04 <= atr_pct <= 8.0
    return 0.02 <= atr_pct <= 5.0

def compute_true_kelly_fraction(wins: int, trades: int, rr_ratio: float = 1.8) -> float:
    if trades < 8:
        return MARGIN_PER_TRADE
    p = wins / trades
    full_kelly = p - ((1.0 - p) / rr_ratio)
    if full_kelly <= 0:
        return 0.12
    half_kelly = full_kelly * 0.65
    return max(0.12, min(0.35, half_kelly))


# =====================================================================
# CERVEAU QUANTITATIF V8.5 (AVEC PULLBACK MTF, SQUEEZE & STOP-HUNT)
# =====================================================================
async def analyze_asset(name, ticker):
    try:
        def fetch_data_hybrid():
            is_crypto = ticker.endswith('USDT') or ticker.endswith('USD')
            if is_crypto:
                ccxt_ticker = ticker if '/' in ticker else ticker.replace('USDT', '/USDT')
                ohlcv_micro = binance.fetch_ohlcv(ccxt_ticker, timeframe='5m', limit=500)
                ohlcv_macro = binance.fetch_ohlcv(ccxt_ticker, timeframe='1h', limit=300)
                df_micro_res = pd.DataFrame(ohlcv_micro, columns=['Datetime', 'Open', 'High', 'Low', 'Close', 'Volume'])
                df_macro_res = pd.DataFrame(ohlcv_macro, columns=['Datetime', 'Open', 'High', 'Low', 'Close', 'Volume'])
                w_m = 4.0
            else:
                stock = yf.Ticker(ticker)
                df_micro_res = stock.history(period="5d", interval="5m")
                df_macro_res = stock.history(period="3mo", interval="1h")
                w_m = 2.5
            return df_micro_res, df_macro_res, w_m

        df_micro, df_macro, wm = await asyncio.to_thread(fetch_data_hybrid)

        if df_micro.empty or df_macro.empty or len(df_macro) < 50 or len(df_micro) < 60:
            return {}, 0, False, 0, 0, {}, {}

        # ── 1. TENDANCE MACRO 1H (EMA 50 vs EMA 200) ──
        df_macro['EMA_50'] = df_macro['Close'].ewm(span=50, adjust=False).mean()
        df_macro['EMA_200'] = df_macro['Close'].ewm(span=200, adjust=False).mean()
        m_ema50 = float(df_macro['EMA_50'].iloc[-1])
        m_ema200 = float(df_macro['EMA_200'].iloc[-1])
        ema_diff_macro_pct = (m_ema50 - m_ema200) / max(1e-9, m_ema200) * 100
        macro_trend = max(-1.0, min(1.0, ema_diff_macro_pct / 1.5))

        # ── 2. INDICATEURS MICRO 5M ──
        delta = df_micro['Close'].diff()
        up = delta.clip(lower=0)
        down = -1 * delta.clip(upper=0)
        ema_up = up.ewm(com=13, adjust=False).mean()
        ema_down = down.ewm(com=13, adjust=False).mean()
        df_micro['RSI_14'] = 100 - (100 / (1 + (ema_up / ema_down.replace(0, 1e-9))))

        df_micro['MACD_12_26_9'] = df_micro['Close'].ewm(span=12, adjust=False).mean() - df_micro['Close'].ewm(span=26, adjust=False).mean()
        df_micro['MACDs_12_26_9'] = df_micro['MACD_12_26_9'].ewm(span=9, adjust=False).mean()
        df_micro['MACD_hist'] = df_micro['MACD_12_26_9'] - df_micro['MACDs_12_26_9']

        l14 = df_micro['Low'].rolling(14).min()
        h14 = df_micro['High'].rolling(14).max()
        df_micro['STOCHk_14_3_3'] = (100 * ((df_micro['Close'] - l14) / (h14 - l14).replace(0, 1e-9))).rolling(3).mean()

        hl = df_micro['High'] - df_micro['Low']
        hc = (df_micro['High'] - df_micro['Close'].shift()).abs()
        lc = (df_micro['Low'] - df_micro['Close'].shift()).abs()
        df_micro['ATRr_14'] = pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(14).mean()

        sma20 = df_micro['Close'].rolling(20).mean()
        std20 = df_micro['Close'].rolling(20).std()
        df_micro['BBL_20_2.0'] = sma20 - (2 * std20)
        df_micro['BBU_20_2.0'] = sma20 + (2 * std20)

        df_micro = df_micro.ffill().bfill()
        last = df_micro.iloc[-1]
        prix = float(last['Close'])
        open_p = float(last['Open'])
        high_p = float(last['High'])
        low_p  = float(last['Low'])
        atr = float(last.get('ATRr_14', prix * 0.02))
        rsi_now = float(last['RSI_14'])

        whale = bool(last['Volume'] > (df_micro['Volume'].rolling(20).mean().iloc[-2] * wm)) if len(df_micro) > 20 else False

        # Confirmation de bougie (Anti-Couteau qui tombe)
        candle_range = max(1e-9, high_p - low_p)
        lower_wick_ratio = (min(open_p, prix) - low_p) / candle_range
        upper_wick_ratio = (high_p - max(open_p, prix)) / candle_range
        bullish_rebound_candle = (prix >= open_p) or (lower_wick_ratio >= 0.45)
        bearish_rebound_candle = (prix <= open_p) or (upper_wick_ratio >= 0.45)

        # MACD normalisé
        macd_range = df_micro['MACD_hist'].abs().rolling(50).max().iloc[-1]
        s_macd = max(-1.0, min(1.0, float(last['MACD_hist'] / macd_range))) if macd_range > 0 else 0.0

        # Position Bollinger
        bb_range = last['BBU_20_2.0'] - last['BBL_20_2.0']
        bb_pos = float((prix - last['BBL_20_2.0']) / bb_range) if bb_range > 0 else 0.5
        s_bb_retourn = max(-1.0, min(1.0, -((bb_pos - 0.5) * 2.2)))
        s_bb_confirm = max(-1.0, min(1.0, (bb_pos - 0.5) * 2.2))

        # ── 3. INDICATEURS AVANCÉS & NOUVEAUX SIGNAUX (PULLBACK, SQUEEZE, STOPHUNT) ──
        # A. OBV Confirmation vs Divergence
        obv_series = (np.sign(df_micro['Close'].diff()) * df_micro['Volume']).fillna(0).cumsum()
        obv_sma20 = obv_series.rolling(20).mean()
        obv_std20 = obv_series.rolling(20).std().iloc[-1]
        s_obv_confirm = max(-1.0, min(1.0, float((obv_series.iloc[-1] - obv_sma20.iloc[-1]) / (2 * obv_std20)))) if obv_std20 > 0 else 0.0

        price_slope_10 = (df_micro['Close'].iloc[-1] - df_micro['Close'].iloc[-10]) / max(1e-9, atr * 3)
        obv_slope_10 = (obv_series.iloc[-1] - obv_series.iloc[-10]) / max(1e-9, obv_std20 * 2) if obv_std20 > 0 else 0.0
        s_obv_retourn = max(-1.0, min(1.0, float(obv_slope_10 - price_slope_10)))

        # B. Vrai Supertrend
        hl2 = (df_micro['High'] + df_micro['Low']) / 2
        upper_band = (hl2 + 2.5 * df_micro['ATRr_14']).values
        lower_band = (hl2 - 2.5 * df_micro['ATRr_14']).values
        close_arr = df_micro['Close'].values
        st_dir = 1.0
        for i in range(max(1, len(close_arr) - 60), len(close_arr)):
            if close_arr[i] > upper_band[i - 1]:
                st_dir = 1.0
            elif close_arr[i] < lower_band[i - 1]:
                st_dir = -1.0
        s_supertrend = st_dir

        # C. Ichimoku
        tenkan = (df_micro['High'].rolling(9).max() + df_micro['Low'].rolling(9).min()) / 2
        kijun = (df_micro['High'].rolling(26).max() + df_micro['Low'].rolling(26).min()) / 2
        senkou_a = (tenkan + kijun) / 2
        senkou_b = (df_micro['High'].rolling(52).max() + df_micro['Low'].rolling(52).min()) / 2
        cloud_top = max(senkou_a.iloc[-1], senkou_b.iloc[-1])
        cloud_bot = min(senkou_a.iloc[-1], senkou_b.iloc[-1])
        tk_cross = 0.4 if tenkan.iloc[-1] > kijun.iloc[-1] else -0.4
        s_ichimoku = min(1.0, 0.6 + tk_cross) if prix > cloud_top else (max(-1.0, -0.6 + tk_cross) if prix < cloud_bot else tk_cross * 0.5)

        # D. VWAP Session
        df_session = df_micro.iloc[-96:]
        typ_p = (df_session['High'] + df_session['Low'] + df_session['Close']) / 3
        vwap_val = float((typ_p * df_session['Volume']).sum() / max(1e-9, df_session['Volume'].sum()))
        vwap_z = (prix - vwap_val) / max(1e-9, float(std20.iloc[-1]))
        s_vwap_confirm = max(-1.0, min(1.0, vwap_z / 2.0))
        s_vwap_retourn = max(-1.0, min(1.0, -vwap_z / 2.0))

        # E. Williams %R
        w_range = max(1e-9, float(h14.iloc[-1] - l14.iloc[-1]))
        williams_r = -100 * (float(h14.iloc[-1]) - prix) / w_range
        s_williams_retourn = 1.0 if williams_r < -80 else (-1.0 if williams_r > -20 else -(williams_r + 50) / 30.0)
        s_williams_confirm = (williams_r + 50) / 50.0

        # F. NOUVEAU : Signal Pullback Multi-Timeframe (Tendance 1h forte + Repli 5m + Bougie de reprise)
        s_pullback = 0.0
        if macro_trend > 0.15 and (rsi_now < 48 or bb_pos < 0.38) and bullish_rebound_candle:
            s_pullback = min(1.0, 0.65 + (48 - min(48, rsi_now)) / 30.0)
        elif macro_trend < -0.15 and (rsi_now > 52 or bb_pos > 0.62) and bearish_rebound_candle:
            s_pullback = max(-1.0, -0.65 - (max(52, rsi_now) - 52) / 30.0)
        else:
            s_pullback = macro_trend * 0.35

        # G. NOUVEAU : Signal Volatility Squeeze (Bollinger comprimé par rapport à Keltner + Explosion)
        keltner_width = 3.0 * df_micro['ATRr_14']
        bb_width = df_micro['BBU_20_2.0'] - df_micro['BBL_20_2.0']
        was_squeezed = bool((bb_width.iloc[-6:-1] < keltner_width.iloc[-6:-1]).any())
        if was_squeezed and abs(s_macd) > 0.25:
            s_squeeze = 1.0 if s_macd > 0 else -1.0
        else:
            s_squeeze = s_macd * 0.5

        # H. NOUVEAU : Signal Stop-Hunt / Liquidity Sweep (Mèche qui balaye le plus haut/bas de 20 bougies puis réintègre)
        prev_low_20 = float(df_micro['Low'].iloc[-21:-1].min())
        prev_high_20 = float(df_micro['High'].iloc[-21:-1].max())
        if low_p <= prev_low_20 and prix > prev_low_20 and bullish_rebound_candle:
            s_stophunt = 1.0
        elif high_p >= prev_high_20 and prix < prev_high_20 and bearish_rebound_candle:
            s_stophunt = -1.0
        elif lower_wick_ratio >= 0.55 and rsi_now < 42:
            s_stophunt = 0.85
        elif upper_wick_ratio >= 0.55 and rsi_now > 58:
            s_stophunt = -0.85
        else:
            s_stophunt = s_bb_retourn * 0.4

        # I. ADX (14) & Régime de Marché
        plus_dm = df_micro['High'].diff().clip(lower=0)
        minus_dm = (-df_micro['Low'].diff()).clip(lower=0)
        plus_dm = plus_dm.where(plus_dm > minus_dm, 0)
        minus_dm = minus_dm.where(minus_dm > plus_dm, 0)
        atr_s = df_micro['ATRr_14'].replace(0, 1e-9)
        plus_di = 100 * (plus_dm.ewm(span=14, adjust=False).mean() / atr_s)
        minus_di = 100 * (minus_dm.ewm(span=14, adjust=False).mean() / atr_s)
        dx = (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, 1e-9)) * 100
        adx_val = float(dx.ewm(span=14, adjust=False).mean().iloc[-1])
        market_regime = 'TREND' if adx_val >= 25.0 else 'RANGE'

        # ── 4. SENTIMENT NEWS ──
        n_score, n_count = 0.0, 0
        try:
            news_items = await asyncio.wait_for(asyncio.to_thread(fetch_news_safe, ticker), timeout=8)
            for ni in news_items:
                title = ni.get('title', '')
                if not title:
                    continue
                compound = analyzer.polarity_scores(title)['compound']
                n_score += compound
                n_count += 1
        except Exception:
            pass
        n_score_norm = max(-1.0, min(1.0, n_score / max(1, n_count)))

        # ── 5. MACHINE LEARNING V8.5 ──
        if ml_engine.needs_retrain(name):
            try:
                await asyncio.to_thread(ml_engine.train, name, df_micro)
            except Exception as ml_err:
                print(f"⚠️ ML retrain {name}: {ml_err}")

        ml_features = ml_engine.extract_latest_feature_dict(df_micro)
        s_ml = ml_engine.predict(name, ml_features)

        # ── 6. VECTEURS DE SIGNAUX (CONFIRMATION vs RETOURNEMENT) ──
        sig_confirm = {
            'ema': macro_trend,
            'rsi': score_rsi_confirmation(rsi_now),
            'stoch': score_stoch_confirmation(float(last['STOCHk_14_3_3'])),
            'macd': s_macd,
            'bb': s_bb_confirm,
            'news': n_score_norm,
            'obv': s_obv_confirm,
            'supertrend': s_supertrend,
            'ichimoku': s_ichimoku,
            'vwap': s_vwap_confirm,
            'williams': s_williams_confirm,
            'pullback': s_pullback,
            'squeeze': s_squeeze,
            'stophunt': s_stophunt,
            'ml': s_ml
        }

        sig_retourn = {
            'ema': -macro_trend * 0.4,
            'rsi': score_rsi_retournement(rsi_now),
            'stoch': score_stoch_retournement(float(last['STOCHk_14_3_3'])),
            'macd': -s_macd * 0.4,
            'bb': s_bb_retourn,
            'news': n_score_norm,
            'obv': s_obv_retourn,
            'supertrend': -s_supertrend * 0.4,
            'ichimoku': -s_ichimoku * 0.4,
            'vwap': s_vwap_retourn,
            'williams': s_williams_retourn,
            'pullback': s_pullback,
            'squeeze': s_squeeze,
            'stophunt': s_stophunt,
            'ml': s_ml
        }

        # ── 7. PASSE 1 : SCORES DES BOTS STANDARDS, CAMÉLÉONS, ML ET RL ──
        scores = {}
        bot_snapshots = {}

        for n_bot, weights in TRADER_PROFILES.items():
            meta = BOT_META.get(n_bot, {})
            mode = meta.get('mode', 'CONFIRM')

            if mode == 'TEMOIN':
                if "Singe" in n_bot:
                    scores[n_bot] = random.uniform(-100, 100)
                elif "Permabull" in n_bot:
                    scores[n_bot] = 100.0
                else:
                    scores[n_bot] = -100.0
                bot_snapshots[n_bot] = {}
                continue

            if mode == 'META':
                continue

            active_mode = mode
            if mode == 'CAMELEON':
                active_mode = 'CONFIRM' if market_regime == 'TREND' else 'RETOURN'

            vec = sig_confirm if active_mode == 'CONFIRM' else sig_retourn
            b = sum(vec.get(k, 0.0) * w for k, w in weights.items())
            raw_score = max(-100.0, min(100.0, b * 100.0))

            # PROTECTION ANTI-COUTEAU QUI TOMBE :
            # Un bot en mode RETOURNEMENT ne peut ouvrir que si la bougie 5m montre un rejet dans son sens !
            if active_mode == 'RETOURN':
                if raw_score > 0 and not bullish_rebound_candle:
                    raw_score *= 0.65
                elif raw_score < 0 and not bearish_rebound_candle:
                    raw_score *= 0.65
                # Empêche aussi de shorter un train haussier violent (ADX > 38) sans mèche de rejet
                if adx_val > 38 and (raw_score * macro_trend < 0) and abs(s_stophunt) < 0.8:
                    raw_score *= 0.50

            scores[n_bot] = raw_score
            bot_snapshots[n_bot] = {k: vec.get(k, 0.0) for k in weights.keys()}

        # ── 8. PASSE 2 : MÉTA-BOTS (ESSAIM, CORRÉLATION, FADE THE BOTTOM) ──
        incubation_elapsed = (time.time() - meta_state.get('experiment_start_time', time.time())) >= (INCUBATION_DAYS * 86400)

        sorted_by_cap = sorted(paper_portfolio.items(), key=lambda x: x[1]['capital'], reverse=True)
        top10_bots = [n for n, _ in sorted_by_cap[:10]]
        top5_bots = [n for n, _ in sorted_by_cap[:5]]
        top3_bots = [n for n, _ in sorted_by_cap[:3]]
        bottom5_bots = [n for n, _ in sorted_by_cap[-5:]]
        bottom10_bots = [n for n, _ in sorted_by_cap[-10:]]

        def group_avg_score(bot_list):
            vals = []
            for b_name in bot_list:
                pos_b = paper_portfolio[b_name]['positions'].get(name)
                if pos_b:
                    vals.append(80.0 if pos_b['type'] == 'LONG' else -80.0)
                elif b_name in scores:
                    vals.append(scores[b_name])
            return sum(vals) / len(vals) if vals else 0.0

        fam_confirm_avg = group_avg_score([n for n, m in BOT_META.items() if m['famille'] == 'Confirmation'])
        fam_retourn_avg = group_avg_score([n for n, m in BOT_META.items() if m['famille'] == 'Retournement'])
        fam_ml_avg      = group_avg_score([n for n, m in BOT_META.items() if m['famille'] == 'Machine Learning'])
        fam_rl_avg      = group_avg_score([n for n, m in BOT_META.items() if m['famille'] == 'Auto-Adaptatif RL'])
        fam_cam_avg     = group_avg_score([n for n, m in BOT_META.items() if m['famille'] == 'Caméléon'])
        all_standard_avg = group_avg_score(list(scores.keys()))

        for n_bot, meta in BOT_META.items():
            if meta.get('mode') != 'META':
                continue
            if not incubation_elapsed:
                scores[n_bot] = 0.0
                bot_snapshots[n_bot] = {}
                continue

            m_type = meta.get('meta_type')
            m_score = 0.0
            if m_type == "TOP10_FOLLOW":
                m_score = group_avg_score(top10_bots) * 1.25
            elif m_type == "TOP5_FOLLOW":
                m_score = group_avg_score(top5_bots) * 1.30
            elif m_type == "FADE_BOTTOM5":
                m_score = -group_avg_score(bottom5_bots) * 1.35
            elif m_type == "FADE_BOTTOM10":
                m_score = -group_avg_score(bottom10_bots) * 1.30
            elif m_type == "DARWIN_TOP3":
                m_score = group_avg_score(top3_bots) * 1.30
            elif m_type == "CORREL_CONF_ML":
                if fam_confirm_avg * fam_ml_avg > 0:
                    m_score = (fam_confirm_avg + fam_ml_avg) / 2 * 1.35
            elif m_type == "CORREL_RET_ML":
                if fam_retourn_avg * fam_ml_avg > 0:
                    m_score = (fam_retourn_avg + fam_ml_avg) / 2 * 1.35
            elif m_type == "CORREL_RL_CAM":
                if fam_rl_avg * fam_cam_avg > 0:
                    m_score = (fam_rl_avg + fam_cam_avg) / 2 * 1.30
            elif m_type == "GLOBAL_FOLLOW":
                m_score = all_standard_avg * 1.25
            elif m_type == "GLOBAL_FADE":
                m_score = -all_standard_avg * 1.40 if abs(all_standard_avg) >= 45 else 0.0
            elif m_type == "WINRATE_LEADERS":
                wr_leaders = sorted(
                    [n for n, d in paper_portfolio.items() if d['trades'] >= 5],
                    key=lambda x: paper_portfolio[x]['wins'] / max(1, paper_portfolio[x]['trades']),
                    reverse=True
                )[:5]
                m_score = group_avg_score(wr_leaders or top5_bots) * 1.25
            elif m_type == "TOP10_VS_BOT10":
                m_score = (group_avg_score(top10_bots) - group_avg_score(bottom10_bots)) * 0.85

            scores[n_bot] = max(-100.0, min(100.0, m_score))
            bot_snapshots[n_bot] = {}

        raw_data = {
            'rsi': rsi_now,
            'stoch': float(last['STOCHk_14_3_3']),
            'macd': float(last['MACD_12_26_9']),
            'sig': float(last['MACDs_12_26_9']),
            'macd_hist': float(last['MACD_hist']),
            'ema50': m_ema50,
            'ema200': m_ema200,
            'bb_pos': bb_pos,
            'atr_pct': (atr / prix * 100) if prix > 0 else 0.0,
            'adx': adx_val,
            'ml_score': s_ml,
            'market_regime': market_regime
        }

        return scores, n_score_norm, whale, prix, atr, raw_data, bot_snapshots

    except Exception as e:
        print(f"❌ Erreur critique analyse {name}: {e}")
        return {}, 0, False, 0, 0, {}, {}


# =====================================================================
# TRAILING STOP DYNAMIQUE V8.5
# =====================================================================
def compute_trailing_stop(pos: dict, prix: float, atr: float) -> float:
    entry = pos['price']
    if pos['type'] == 'LONG':
        profit_atr = (prix - entry) / atr if atr > 0 else 0
        if profit_atr < 1.5:
            return pos['sl']
        new_sl = prix - (atr * 1.6)
        return max(pos['sl'], new_sl)
    else:
        profit_atr = (entry - prix) / atr if atr > 0 else 0
        if profit_atr < 1.5:
            return pos['sl']
        new_sl = prix + (atr * 1.6)
        return min(pos['sl'], new_sl)


# =====================================================================
# BOUCLE DE SCAN DES MARCHÉS V8.5 (TP1 50% + PROTECTION VENDREDI SOIR)
# =====================================================================
@tasks.loop(seconds=60)
async def market_scanner():
    await bot.wait_until_ready()
    now = datetime.now()
    if now.minute % 5 != 0:
        return
    print(f"\n[{now.strftime('%H:%M:%S')}] ⚙️ Scan Symbiosis V8.5 (100 Bots) en cours...")
    try:
        await asyncio.wait_for(_scan_inner(), timeout=180)
    except asyncio.TimeoutError:
        print("⚠️ market_scanner : timeout global 3min dépassé.")
    except Exception as e:
        print(f"❌ market_scanner erreur : {type(e).__name__}: {e}")


async def _scan_inner():
    try:
        channel = bot.get_channel(int(CHANNEL_ID)) or await bot.fetch_channel(int(CHANNEL_ID))
    except Exception as e:
        print(f"❌ Salon Discord introuvable {CHANNEL_ID}: {e}")
        return

    modified = False

    # ── 1. VÉRIFICATION DE L'OUVERTURE DE LA CHASSE (APRÈS 14 JOURS D'INCUBATION) ──
    elapsed_days = (time.time() - meta_state.get('experiment_start_time', time.time())) / 86400
    if elapsed_days >= INCUBATION_DAYS and not meta_state.get('hunt_opened_alert_sent', False):
        meta_state['hunt_opened_alert_sent'] = True
        modified = True
        await channel.send(
            content=(
                f"@everyone 🎺🐺 **LA CHASSE EST OFFICIELLEMENT OUVERTE !**\n"
                f"> Les **{INCUBATION_DAYS} jours d'incubation** sont terminés.\n"
                f"> Les **12 Méta-Bots** (`Fade_Bottom5_Meta_Retourn`, `Crowd_Top10_Meta_Confirm`, `Darwin_Top3`, Corrélations) "
                f"entrent dès maintenant en chasse active !"
            )
        )

    top_10_names = [
        n for n, d in sorted(paper_portfolio.items(), key=lambda x: x[1]['capital'], reverse=True)[:10]
    ]

    for name, ticker in ASSETS.items():
        if not is_market_open(name):
            continue

        try:
            scores, n_score, whale, prix, atr, raw, bot_snapshots = await asyncio.wait_for(
                analyze_asset(name, ticker), timeout=35
            )
        except Exception as ae:
            print(f"⚠️ analyze_asset({name}) erreur/timeout : {ae}")
            continue

        if not scores or prix == 0:
            continue

        atr_ok = atr_is_favorable(atr, prix, name)
        levier = LEVERAGE_MAP.get(name, 10)
        friday_shield_active = is_friday_pre_close_window(name)

        for n_bot, score in scores.items():
            p = paper_portfolio[n_bot]
            pos = p['positions'].get(name)

            # ── A. GESTION DES POSITIONS OUVERTES (TP1 50% + BREAK-EVEN, VENDREDI, TP FINAL, SL) ──
            if pos:
                pos_atr = pos.get('atr', atr)
                profit_atr = ((prix - pos['price']) / pos_atr) if pos['type'] == 'LONG' else ((pos['price'] - prix) / pos_atr)

                # 1. PROTECTION ANTI-GAP DU VENDREDI SOIR (21h00-21h59 UTC sur Futures)
                friday_exit = False
                if friday_shield_active:
                    age_hours = (time.time() - pos['open_time']) / 3600
                    # Si la position est en perte, proche du Break-Even (< 1.5 ATR) ou ouverte depuis moins de 2h -> On ferme !
                    if profit_atr < 1.5 or age_hours < 2.0:
                        friday_exit = True
                    else:
                        # Sinon elle est très gagnante : on verrouille le SL au Break-Even + frais pour le week-end
                        be_offset = pos['price'] * (COUT_PAR_LEG * 2.5)
                        if pos['type'] == 'LONG':
                            pos['sl'] = max(pos['sl'], pos['price'] + be_offset)
                        else:
                            pos['sl'] = min(pos['sl'], pos['price'] - be_offset)
                        modified = True

                # 2. PRISE DE PROFIT PARTIELLE TP1 (50% à +1.8 ATR) + MISE À BREAK-EVEN AUTOMATIQUE
                if not friday_exit and not pos.get('tp1_hit', False) and profit_atr >= 1.8:
                    days_tp1 = (time.time() - pos['open_time']) / 86400
                    diff_pct_tp1 = (prix - pos['price']) / pos['price'] if pos['type'] == 'LONG' else (pos['price'] - prix) / pos['price']
                    half_notional = pos.get('notional', pos['margin'] * levier) * 0.50

                    gross_tp1 = half_notional * diff_pct_tp1
                    fees_tp1 = half_notional * (COUT_PAR_LEG * 2 + days_tp1 * FUNDING_RATE_DAY)
                    net_tp1 = gross_tp1 - fees_tp1

                    # On encaisse immédiatement 50% en banque !
                    p['capital'] += net_tp1
                    p['total_fees'] = p.get('total_fees', 0.0) + fees_tp1
                    pos['margin'] *= 0.50
                    pos['notional'] = half_notional
                    pos['tp1_hit'] = True
                    pos['realized_tp1'] = net_tp1
                    pos['fees_tp1'] = fees_tp1

                    # Déplacement du Stop-Loss exactement au Break-Even (+ frais couverts)
                    be_buffer = pos['price'] * (COUT_PAR_LEG * 2.2)
                    if pos['type'] == 'LONG':
                        pos['sl'] = max(pos['sl'], pos['price'] + be_buffer)
                    else:
                        pos['sl'] = min(pos['sl'], pos['price'] - be_buffer)
                    modified = True

                # 3. MISE À JOUR DU TRAILING STOP & VÉRIFICATION DE CLÔTURE TOTALE
                pos['sl'] = compute_trailing_stop(pos, prix, atr)

                hit_tp = (pos['type'] == 'LONG' and prix >= pos['tp']) or \
                         (pos['type'] == 'SHORT' and prix <= pos['tp'])
                hit_sl = (pos['type'] == 'LONG' and prix <= pos['sl']) or \
                         (pos['type'] == 'SHORT' and prix >= pos['sl'])

                # Sortie sur signal inverse UNIQUEMENT si retournement extrême (>= 80%)
                extreme_reversal = (score <= -80.0 and pos['type'] == 'LONG') or \
                                   (score >= 80.0 and pos['type'] == 'SHORT')

                if hit_tp or hit_sl or friday_exit or extreme_reversal:
                    days = (time.time() - pos['open_time']) / 86400
                    price_diff_pct = (prix - pos['price']) / pos['price'] if pos['type'] == 'LONG' else (pos['price'] - prix) / pos['price']

                    rem_notional = pos.get('notional', pos['margin'] * levier)
                    gross_pnl = rem_notional * price_diff_pct

                    fee_exchange = rem_notional * (FRAIS_EXCHANGE * 2)
                    fee_slip_spread = rem_notional * ((SPREAD + SLIPPAGE) * 2)
                    fee_funding = rem_notional * (days * FUNDING_RATE_DAY)
                    frais_rem = fee_exchange + fee_slip_spread + fee_funding

                    profit_rem = gross_pnl - frais_rem

                    p['capital'] += profit_rem
                    p['trades'] += 1
                    p['total_fees'] = p.get('total_fees', 0.0) + frais_rem

                    # Profit total du trade (incluant le TP1 à 50% s'il avait été touché !)
                    total_trade_profit = profit_rem + pos.get('realized_tp1', 0.0)
                    total_trade_fees = frais_rem + pos.get('fees_tp1', 0.0)
                    initial_notional = rem_notional * 2 if pos.get('tp1_hit') else rem_notional

                    if total_trade_profit > 0:
                        p['wins'] += 1

                    # Apprentissage RL, Mémoire d'actif, Seuil dynamique & Cooldown
                    record_bot_experience(
                        n_bot, name, pos.get('signals_snapshot', {}),
                        pos['type'], total_trade_profit, is_sl=(hit_sl and total_trade_profit < 0)
                    )

                    del p['positions'][name]
                    modified = True

                    # Alerte de clôture UNIQUEMENT pour le Top 10 avec @everyone
                    if n_bot in top_10_names:
                        rank_b = top_10_names.index(n_bot) + 1
                        emoji_pf = "🟢" if total_trade_profit > 0 else "🔴"
                        if friday_exit:
                            reason_str = "🛡️ Protection Vendredi Soir (Anti-Gap)"
                        elif hit_tp:
                            reason_str = "🎯 TP Final atteint"
                        elif hit_sl and pos.get('tp1_hit'):
                            reason_str = "🛡️ Stop Break-Even après TP1 (+1.8 ATR encaissé)"
                        elif hit_sl:
                            reason_str = "🛑 SL touché"
                        else:
                            reason_str = "🔄 Retournement extrême"

                        await channel.send(
                            content=(
                                f"@everyone {emoji_pf} 💰 **[#{rank_b} TOP 10] {n_bot}** ferme **{name}** ({reason_str})\n"
                                f"> **P&L Net Total : {total_trade_profit:+.2f}$** | Capital bot : **{p['capital']:.2f}$** "
                                f"(WR: {p['wins']}/{p['trades']})\n"
                                f"> 🧾 *Valeur initiale trade : {initial_notional:,.0f}$ | Frais totaux payés : **-{total_trade_fees:.2f}$***"
                            )
                        )

            # ── B. OUVERTURE DE POSITION (AVEC FILTRES COOLDOWN, VENDREDI, KILLZONE & SPÉCIALISTE) ──
            elif not pos and atr_ok:
                if len(p['positions']) >= 3:
                    continue

                # 1. Vérification Protection Vendredi Soir / Dimanche & Killzone
                if not can_open_new_trade(name, n_bot):
                    continue

                # 2. Vérification Cooldown Anti-Revenge Trading (30 min après un SL sur cet actif)
                cooldown_until = p.get('cooldowns', {}).get(name, 0)
                if time.time() < cooldown_until:
                    continue

                # 3. Seuil d'entrée dynamique (s'adapte pour les bots AUTOTHRESH et RL)
                bot_threshold = p.get('dynamic_threshold', float(SIGNAL_THRESHOLD))
                if abs(score) < bot_threshold:
                    continue

                # 4. Filtre Mémoire par Actif (pour les bots SPECIALIST)
                meta = BOT_META.get(n_bot, {})
                ast_stat = p.get('asset_stats', {}).get(name, {'wins': 0, 'trades': 0, 'pnl': 0.0})
                specialist_mult = 1.0
                if meta.get('special') == 'SPECIALIST' and ast_stat['trades'] >= 4:
                    ast_wr = ast_stat['wins'] / ast_stat['trades']
                    if ast_wr < 0.30 and ast_stat['pnl'] < 0:
                        # Le bot est mauvais sur cet actif : il exige un signal exceptionnel (>75%) et réduit sa mise de moitié
                        if abs(score) < 75.0:
                            continue
                        specialist_mult = 0.50
                    elif ast_wr >= 0.55 and ast_stat['pnl'] > 0:
                        # C'est son actif fétiche : bonus de taille de +25%
                        specialist_mult = 1.25

                # Assiette de mise (Capital négatif autorisé pour nourrir Fade_Bottom, mais assiette >= 100$)
                base_capital = max(100.0, p['capital'])
                famille = meta.get('famille', '')

                if "Kelly" in n_bot or famille in ('Auto-Adaptatif RL', 'Machine Learning'):
                    kelly_f = compute_true_kelly_fraction(p['wins'], p['trades'], rr_ratio=1.8)
                    m_target = base_capital * kelly_f * specialist_mult
                else:
                    m_target = base_capital * MARGIN_PER_TRADE * specialist_mult

                # Réduction de 30% si déjà exposé dans le même sens sur un actif corrélé
                type_p = 'LONG' if score >= bot_threshold else 'SHORT'
                for g_assets in CORREL_GROUPS.values():
                    if name in g_assets:
                        if any(oa != name and opos['type'] == type_p and oa in g_assets for oa, opos in p['positions'].items()):
                            m_target *= 0.70
                        break

                notional_value = m_target * levier
                frais_aller_retour_est = notional_value * (COUT_PAR_LEG * 2)

                sl_distance = atr * 2.0
                tp1_distance = atr * 1.8  # Encaisse 50% + Break-Even
                tp2_distance = atr * 3.8  # Cible finale pour les 50% restants

                p['positions'][name] = {
                    'type': type_p,
                    'price': prix,
                    'margin': m_target,
                    'notional': notional_value,
                    'sl': prix - sl_distance if type_p == 'LONG' else prix + sl_distance,
                    'tp1': prix + tp1_distance if type_p == 'LONG' else prix - tp1_distance,
                    'tp': prix + tp2_distance if type_p == 'LONG' else prix - tp2_distance,
                    'tp1_hit': False,
                    'realized_tp1': 0.0,
                    'fees_tp1': 0.0,
                    'open_time': time.time(),
                    'atr': atr,
                    'score_entry': score,
                    'signals_snapshot': bot_snapshots.get(n_bot, {})
                }
                modified = True

                # Alerte d'ouverture UNIQUEMENT si le bot fait partie du Top 10 (avec @everyone)
                if n_bot in top_10_names:
                    rank_b = top_10_names.index(n_bot) + 1
                    atr_str = f"{raw.get('atr_pct', 0):.2f}%"
                    regime_str = raw.get('market_regime', 'TREND')
                    pos_created = p['positions'][name]
                    await channel.send(
                        content=(
                            f"@everyone 🏆🚀 **[#{rank_b} TOP 10] {n_bot}** ouvre **{type_p}** sur **{name}** à **{prix:,.2f}$**\n"
                            f"> 💵 **Valeur du trade : {notional_value:,.2f}$** (Marge : {m_target:.2f}$ × Levier {levier}x) | "
                            f"Frais A/R estimés : ~{frais_aller_retour_est:.2f}$\n"
                            f"> 🎯 **TP1 (50% + BE) : {pos_created['tp1']:,.2f}$** | 🎯 **TP2 : {pos_created['tp']:,.2f}$** | "
                            f"🛑 **SL : {pos_created['sl']:,.2f}$**\n"
                            f"> 📊 Confiance : {abs(score):.0f}% (Seuil bot: {bot_threshold:.0f}%) | Régime : {regime_str} (ATR {atr_str})"
                        )
                    )

            # Mise à jour du Max Drawdown
            if p['capital'] > p['peak_capital']:
                p['peak_capital'] = p['capital']
            if p['peak_capital'] > 0:
                dd = (p['peak_capital'] - p['capital']) / p['peak_capital'] * 100
                if dd > p.get('max_drawdown', 0):
                    p['max_drawdown'] = dd

        # ── C. ALERTE MOUVEMENT DE FOULE DU TOP 10 (AVEC @everyone ET ANTI-SPAM) ──
        top_10_names = [
            n for n, d in sorted(paper_portfolio.items(), key=lambda x: x[1]['capital'], reverse=True)[:10]
        ]
        top10_long = sum(1 for n in top_10_names if paper_portfolio[n]['positions'].get(name, {}).get('type') == 'LONG')
        top10_short = sum(1 for n in top_10_names if paper_portfolio[n]['positions'].get(name, {}).get('type') == 'SHORT')

        prev_crowd_state = meta_state.setdefault('last_crowd_alert', {}).get(name, 'NONE')

        if top10_long >= 6 and prev_crowd_state != f"LONG_{top10_long}":
            meta_state['last_crowd_alert'][name] = f"LONG_{top10_long}"
            modified = True
            await channel.send(
                content=(
                    f"@everyone 📊🔥 **MOUVEMENT DE FOULE TOP 10** : **{top10_long}/10** bots de l'élite sont **LONG** sur **{name}** "
                    f"(Prix : **{prix:,.2f}$** | Levier {levier}x) ! 🟢 Signal fort haussier."
                )
            )
        elif top10_short >= 6 and prev_crowd_state != f"SHORT_{top10_short}":
            meta_state['last_crowd_alert'][name] = f"SHORT_{top10_short}"
            modified = True
            await channel.send(
                content=(
                    f"@everyone 📊🚨 **MOUVEMENT DE FOULE TOP 10** : **{top10_short}/10** bots de l'élite sont **SHORT** sur **{name}** "
                    f"(Prix : **{prix:,.2f}$** | Levier {levier}x) ! 🔴 Signal fort baissier."
                )
            )
        elif top10_long < 6 and top10_short < 6:
            meta_state['last_crowd_alert'][name] = 'NONE'

    # ── D. VÉRIFICATION TP/SL TRADER HUMAIN ──
    for asset_name, hpos in list(human_trader['positions'].items()):
        hticker = ASSETS.get(asset_name)
        if not hticker:
            continue
        try:
            if hticker.endswith('USDT'):
                ohlcv = binance.fetch_ohlcv(hticker, '1m', limit=1)
                hprix = float(ohlcv[-1][4]) if ohlcv else 0
            else:
                hist = yf.Ticker(hticker).history(period='1d', interval='1m')
                hprix = float(hist['Close'].iloc[-1]) if not hist.empty else 0
        except Exception:
            continue
        if hprix == 0:
            continue

        hpos['sl'] = compute_trailing_stop(hpos, hprix, hpos.get('atr', hprix * 0.02))
        hit_tp = (hpos['type'] == 'LONG' and hprix >= hpos['tp']) or (hpos['type'] == 'SHORT' and hprix <= hpos['tp'])
        hit_sl = (hpos['type'] == 'LONG' and hprix <= hpos['sl']) or (hpos['type'] == 'SHORT' and hprix >= hpos['sl'])

        if hit_tp or hit_sl:
            hlevier = LEVERAGE_MAP.get(asset_name, 10)
            days = (time.time() - hpos['open_time']) / 86400
            diff_pct = (hprix - hpos['price']) / hpos['price'] if hpos['type'] == 'LONG' else (hpos['price'] - hprix) / hpos['price']
            notional = hpos.get('notionnel', hpos['margin'] * hlevier)
            gross = notional * diff_pct
            frais = notional * (COUT_PAR_LEG * 2 + days * FUNDING_RATE_DAY)
            profit = gross - frais

            human_trader['capital'] += profit
            human_trader['trades'] += 1
            human_trader['total_fees'] = human_trader.get('total_fees', 0.0) + frais
            if profit > 0:
                human_trader['wins'] += 1
            if human_trader['capital'] > human_trader['peak_capital']:
                human_trader['peak_capital'] = human_trader['capital']
            dd = (human_trader['peak_capital'] - human_trader['capital']) / human_trader['peak_capital'] * 100
            if dd > human_trader['max_drawdown']:
                human_trader['max_drawdown'] = dd

            human_trader['trade_history'].append({
                'asset': asset_name, 'type': hpos['type'], 'entry': hpos['price'],
                'exit': hprix, 'profit': profit, 'fees': frais, 'reason': 'TP' if hit_tp else 'SL',
                'closed_at': time.time(), 'duration_h': days * 24
            })
            del human_trader['positions'][asset_name]
            modified = True
            reason = "🎯 TP atteint" if hit_tp else "🛑 SL déclenché"
            icon = "🟢" if profit > 0 else "🔴"
            await channel.send(
                content=(
                    f"@everyone {icon} **[VOUS]** {reason} sur **{asset_name}** | "
                    f"P&L Net : **{profit:+.2f}$** (Frais : -{frais:.2f}$) | Capital : **{human_trader['capital']:.2f}$**"
                )
            )

    if modified:
        await save_portfolio()
        print("💾 Portefeuille Symbiosis V8.5 sauvegardé.")


# =====================================================================
# COMMANDES DISCORD V8.5
# =====================================================================
@bot.command()
async def help(ctx):
    e = discord.Embed(title="📚 Commandes Symbiosis V8.5 (100 Bots)", color=0x9b59b6)
    e.add_field(name="🎯 Trading, Chasse & Classement", inline=False, value=(
        "`!sniper` : Radar interactif des 6 actifs\n"
        "`!portfolio` : Top 10 bots actuels\n"
        "`!lb` : Classement général paginé (Toi + 100 bots)\n"
        "`!chasse` : État de l'incubation (14j) et des Méta-Bots\n"
        "`!allpos` : Toutes les positions actives"
    ))
    e.add_field(name="🧠 IA, RL & Statistiques", inline=False, value=(
        "`!ml` : Statut des modèles GradientBoosting V8.5\n"
        "`!rl` : Poids appris et seuils dynamiques des bots RL\n"
        "`!metrics` : Performance par famille\n"
        "`!marches` : État des marchés et du Bouclier Vendredi Soir\n"
        "`!couts` : Analyse des leviers et frais par actif\n"
        "`!resume` : Résumé exécutif du laboratoire"
    ))
    e.add_field(name="👤 Trader Humain", inline=False, value=(
        "`!buy <actif>` / `!sell <actif>` / `!close <actif>`\n"
        "`!mypos` / `!mystats` / `!rank`"
    ))
    await ctx.send(embed=e)


@bot.command()
async def marches(ctx):
    e = discord.Embed(title="🕐 État des Marchés & Bouclier Anti-Gap", color=0x2c3e50)
    now_utc = datetime.now(timezone.utc)
    for name in ASSETS:
        open_st = "🟢 Ouvert" if is_market_open(name) else "🔴 Fermé"
        can_enter = "✅ Entrées autorisées" if can_open_new_trade(name, "Standard") else "🛡️ Entrées bloquées (Protection Week-end)"
        e.add_field(name=name, value=f"{open_st}\n*{can_enter}*", inline=True)
    e.set_footer(text=f"Heure UTC : {now_utc.strftime('%A %H:%M')} | Vendredi 19h UTC = Gel entrées Futures | 21h UTC = Clôture préventive")
    await ctx.send(embed=e)


@bot.command()
async def chasse(ctx):
    start_t = meta_state.get('experiment_start_time', time.time())
    elapsed_s = time.time() - start_t
    target_s = INCUBATION_DAYS * 86400
    remaining_s = max(0.0, target_s - elapsed_s)
    days_done = elapsed_s / 86400

    if remaining_s == 0:
        status_str = "🟢 **LA CHASSE EST OUVERTE !** Les 12 Méta-Bots tradent activement."
        color = 0x2ecc71
    else:
        rem_d = int(remaining_s // 86400)
        rem_h = int((remaining_s % 86400) // 3600)
        status_str = f"⏳ **En incubation** : encore **{rem_d}j {rem_h}h** avant l'entrée en chasse."
        color = 0xf1c40f

    e = discord.Embed(title="🐺 Statut des Méta-Bots & Corrélation", description=status_str, color=color)
    e.add_field(name="Progression", value=f"`{create_pb(days_done, 0, INCUBATION_DAYS, 15)}` ({days_done:.1f} / {INCUBATION_DAYS} jours)", inline=False)

    sorted_b = sorted(paper_portfolio.items(), key=lambda x: x[1]['capital'], reverse=True)
    top5 = ", ".join(f"**{n}** ({d['capital']:.0f}$)" for n, d in sorted_b[:5])
    bot5 = ", ".join(f"**{n}** ({d['capital']:.0f}$)" for n, d in sorted_b[-5:])
    e.add_field(name="🏆 Cibles actuelles `Crowd_Top10` / `Top5`", value=top5, inline=False)
    e.add_field(name="💀 Cibles inversées par `Fade_Bottom5_Meta_Retourn`", value=bot5, inline=False)
    await ctx.send(embed=e)


@bot.command()
async def rl(ctx):
    e = discord.Embed(
        title="🧬 Bots Auto-Adaptatifs (RL & Seuil Dynamique)",
        description="Coefficients et seuils réajustés automatiquement selon l'expérience :",
        color=0x9b59b6
    )
    rl_bots = [n for n, m in BOT_META.items() if m.get('famille') == 'Auto-Adaptatif RL']
    for n in sorted(rl_bots, key=lambda x: paper_portfolio[x]['capital'], reverse=True)[:10]:
        d = paper_portfolio[n]
        w = d.get('custom_weights') or TRADER_PROFILES[n]
        w_str = " • ".join(f"`{k}`:{v*100:.0f}%" for k, v in sorted(w.items(), key=lambda item: item[1], reverse=True))
        thresh = d.get('dynamic_threshold', SIGNAL_THRESHOLD)
        pnl = d['capital'] - d['initial_capital']
        e.add_field(
            name=f"{'🟢' if pnl>=0 else '🔴'} {n} ({d['capital']:.2f}$ | {d['wins']}W/{d['trades']}T | Seuil: {thresh:.0f}%)",
            value=w_str,
            inline=False
        )
    await ctx.send(embed=e)


@bot.command()
async def portfolio(ctx):
    e = discord.Embed(title="🏆 Top 10 Bots — Symbiosis V8.5", color=0xf1c40f)
    for idx, (n, d) in enumerate(sorted(paper_portfolio.items(), key=lambda x: x[1]['capital'], reverse=True)[:10], 1):
        pnl_pct = (d['capital'] - d['initial_capital']) / d['initial_capital'] * 100
        wr = (d['wins'] / d['trades'] * 100) if d['trades'] > 0 else 0
        fees = d.get('total_fees', 0.0)
        e.add_field(
            name=f"#{idx} {n}",
            value=f"**{d['capital']:.2f}$** ({pnl_pct:+.1f}%) | WR: **{wr:.0f}%** ({d['wins']}/{d['trades']}) | Frais: -{fees:.2f}$",
            inline=False
        )
    await ctx.send(embed=e)


@bot.command(aliases=['mlstatus'])
async def ml(ctx):
    status_dict = ml_engine.get_status()
    e = discord.Embed(
        title="🧠 Moteur Machine Learning V8.5 (Seuil ATR Dynamique)",
        description=(
            "**Algorithme** : `GradientBoostingClassifier` équilibré (`max_depth=3`)\n"
            "**Horizon** : `+30 min` (+6 bougies 5m) | **Seuil** : `±0.85 × ATR_5m`"
        ),
        color=0x3498db
    )
    for asset, s in status_dict.items():
        if s['trained']:
            ld = s.get('label_distribution', {})
            total_l = max(1, sum(ld.values()))
            up_pct = ld.get(1, 0) / total_l * 100
            down_pct = ld.get(-1, 0) / total_l * 100
            flat_pct = ld.get(0, 0) / total_l * 100
            f_imp = s.get('feature_importance', {})
            sorted_f = sorted(f_imp.items(), key=lambda x: x[1], reverse=True)[:3]
            top_f_str = " • ".join([f"`{f}` ({val*100:.1f}%)" for f, val in sorted_f])
            val_str = (
                f"📈 **Val : `{s['accuracy']:.2%}`** *(Train: `{s['train_accuracy']:.2%}`)* | `{s['samples_train']}` samples\n"
                f"⚖️ 🟢 Hausse `{up_pct:.0f}%` | 🔴 Baisse `{down_pct:.0f}%` | ⚪ Neutre `{flat_pct:.0f}%`\n"
                f"🔑 {top_f_str}"
            )
        else:
            val_str = "🟡 *En attente du premier cycle d'entraînement...*"
        e.add_field(name=f"🤖 Modèle {asset}", value=val_str, inline=False)
    await ctx.send(embed=e)


@bot.command()
async def lb(ctx):
    all_entries = list(paper_portfolio.items()) + [(HUMAN_NAME, human_trader)]
    sorted_bots = sorted(all_entries, key=lambda x: x[1]['capital'], reverse=True)
    chunk_size = 15
    nb_pages = -(-len(sorted_bots) // chunk_size)

    def build_page(page):
        chunk = sorted_bots[page*chunk_size:(page+1)*chunk_size]
        lines = []
        for rank, (name, d) in enumerate(chunk, start=page*chunk_size+1):
            pnl = ((d['capital'] - d['initial_capital']) / d['initial_capital']) * 100
            wr = (d['wins'] / d['trades'] * 100) if d['trades'] > 0 else 0
            famille = "Humain" if name == HUMAN_NAME else BOT_META.get(name, {}).get("famille", "Bot")
            medals = {1: "🥇", 2: "🥈", 3: "🥉"}
            medal = medals.get(rank, f"`#{rank:>3}`")
            pnl_icon = "🟢" if pnl >= 0 else "🔴"
            fees = d.get('total_fees', 0.0)
            lines.append(
                f"{medal} **{name}** ({famille})\n"
                f"   {pnl_icon} **{d['capital']:.2f}$** ({pnl:+.1f}%) | WR: {wr:.0f}% ({d['wins']}/{d['trades']}) | Frais: -{fees:.1f}$"
            )
        return "\n".join(lines)

    class LBView(discord.ui.View):
        def __init__(self, page=0):
            super().__init__(timeout=120)
            self.page = page

        def build_embed(self):
            tc = sum(d['capital'] for _, d in sorted_bots)
            ti = sum(d['initial_capital'] for _, d in sorted_bots)
            e = discord.Embed(
                title=f"🏆 Classement Général V8.5 — {len(sorted_bots)} Participants",
                description=build_page(self.page),
                color=0xf1c40f
            )
            e.set_footer(text=f"Page {self.page+1}/{nb_pages} | AUM Global: {tc:,.2f}$ ({((tc-ti)/ti*100):+.2f}%)")
            return e

        @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
        async def prev(self, interaction, button):
            self.page = max(0, self.page - 1)
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

        @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
        async def next(self, interaction, button):
            self.page = min(nb_pages - 1, self.page + 1)
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

    v = LBView()
    await ctx.send(embed=v.build_embed(), view=v)


@bot.command()
async def metrics(ctx):
    from collections import defaultdict
    familles = defaultdict(list)
    for n in paper_portfolio:
        fam = BOT_META.get(n, {}).get("famille", "Autre")
        familles[fam].append(n)

    e = discord.Embed(title="📊 Performance par Famille V8.5 (100 Bots)", color=0x2ecc71)
    fam_results = []
    for fam, noms in familles.items():
        tc = sum(paper_portfolio[n]['capital'] for n in noms)
        ti = sum(paper_portfolio[n]['initial_capital'] for n in noms)
        tf = sum(paper_portfolio[n].get('total_fees', 0.0) for n in noms)
        tt = sum(paper_portfolio[n]['trades'] for n in noms)
        tw = sum(paper_portfolio[n]['wins'] for n in noms)
        wr = (tw / tt * 100) if tt > 0 else 0.0
        pnl = ((tc - ti) / ti) * 100 if ti > 0 else 0
        fam_results.append((fam, tc, pnl, len(noms), tf, wr))
    fam_results.sort(key=lambda x: x[2], reverse=True)

    for fam, tc, pnl, count, tf, wr in fam_results:
        pnl_icon = "🟢" if pnl >= 0 else "🔴"
        e.add_field(
            name=f"🏷️ {fam} ({count} bots)",
            value=f"{pnl_icon} Cap: **{tc:,.1f}$** ({pnl:+.2f}%) | WR Moy: **{wr:.1f}%** | Frais: -{tf:.2f}$",
            inline=False
        )
    await ctx.send(embed=e)


@bot.command()
async def couts(ctx):
    e = discord.Embed(title="💸 Leviers & Coûts de Friction V8.5", color=0xe74c3c)
    for name in ASSETS:
        lev = LEVERAGE_MAP.get(name, 10)
        notional_ex = 75.0 * lev
        fee_ar_dollar = notional_ex * (COUT_PAR_LEG * 2)
        e.add_field(
            name=name,
            value=(
                f"Levier : **{lev}×**\n"
                f"Position type (75$ marge) : **{notional_ex:,.0f}$**\n"
                f"Frais A/R : **{fee_ar_dollar:.2f}$** ({COUT_PAR_LEG*2*100:.2f}% du notionnel)"
            ),
            inline=True
        )
    await ctx.send(embed=e)


@bot.command()
async def allpos(ctx):
    actives = {n: d for n, d in paper_portfolio.items() if d['positions']}
    if not actives:
        return await ctx.send("😴 Aucun bot n'a de position ouverte actuellement.")
    desc = ""
    for n, d in sorted(actives.items(), key=lambda x: x[1]['capital'], reverse=True)[:25]:
        pos_str = ", ".join([
            f"{p['type']} **{ast}** ({p.get('notional', p['margin']*10):.0f}${' ✅TP1' if p.get('tp1_hit') else ''})"
            for ast, p in d['positions'].items()
        ])
        desc += f"🤖 **{n}** ({d['capital']:.1f}$) : {pos_str}\n"
    await ctx.send(embed=discord.Embed(title=f"📜 Positions Actives ({len(actives)} bots)", description=desc, color=0x3498db))


@bot.command()
async def resume(ctx):
    all_bots = list(paper_portfolio.items())
    tc = sum(d['capital'] for _, d in all_bots)
    ti = sum(d['initial_capital'] for _, d in all_bots)
    tt = sum(d['trades'] for _, d in all_bots)
    tw = sum(d['wins'] for _, d in all_bots)
    tf = sum(d.get('total_fees', 0.0) for _, d in all_bots)
    wr = (tw / tt * 100) if tt > 0 else 0
    positives = sum(1 for _, d in all_bots if d['capital'] > d['initial_capital'])
    best = max(all_bots, key=lambda x: x[1]['capital'])
    worst = min(all_bots, key=lambda x: x[1]['capital'])

    e = discord.Embed(title="📋 Résumé Exécutif Symbiosis V8.5 (100 Bots)", color=0x2c3e50)
    e.add_field(name="💰 AUM Global", value=f"**{tc:,.2f}$** ({((tc-ti)/ti*100):+.2f}%)\nFrais totaux : **-{tf:,.2f}$**", inline=True)
    e.add_field(name="🎯 Activité & Rentabilité", value=f"Trades : **{tt}** (WR: **{wr:.1f}%**)\nBots positifs : **{positives}/100**", inline=True)
    e.add_field(name="🏆 Meilleur vs 💀 Pire", value=f"🥇 **{best[0]}** : {best[1]['capital']:.2f}$\n💀 **{worst[0]}** : {worst[1]['capital']:.2f}$", inline=False)
    await ctx.send(embed=e)


# =====================================================================
# COMMANDES TRADER HUMAIN
# =====================================================================
ASSET_ALIASES = {
    'btc': 'Bitcoin', 'bitcoin': 'Bitcoin',
    'sol': 'Solana', 'solana': 'Solana',
    'or': 'Or', 'gold': 'Or',
    'argent': 'Argent', 'silver': 'Argent',
    'platine': 'Platine', 'platinum': 'Platine',
    'oil': 'Crude Oil', 'petrole': 'Crude Oil', 'crude': 'Crude Oil',
}

def resolve_asset(arg: str):
    return ASSET_ALIASES.get(arg.lower().strip())

async def open_human_position(ctx, asset_name: str, direction: str):
    if not is_market_open(asset_name):
        return await ctx.send(f"🔴 Le marché **{asset_name}** est fermé.")
    if asset_name in human_trader['positions']:
        return await ctx.send(f"⚠️ Position déjà ouverte sur **{asset_name}**.")
    if len(human_trader['positions']) >= 3:
        return await ctx.send("⚠️ Maximum 3 positions simultanées.")

    msg = await ctx.send("🔍 Analyse du marché en cours...")
    _, _, _, prix, atr, raw, _ = await analyze_asset(asset_name, ASSETS[asset_name])
    if prix == 0 or atr == 0:
        return await msg.edit(content="❌ Impossible de récupérer le prix.")

    base_cap = max(100.0, human_trader['capital'])
    marge = base_cap * MARGIN_PER_TRADE
    levier = LEVERAGE_MAP.get(asset_name, 10)
    notional = marge * levier
    sl = (prix - atr * 2.0) if direction == 'LONG' else (prix + atr * 2.0)
    tp = (prix + atr * 3.8) if direction == 'LONG' else (prix - atr * 3.8)

    human_trader['positions'][asset_name] = {
        'type': direction, 'price': prix, 'margin': marge,
        'sl': sl, 'tp': tp, 'open_time': time.time(), 'atr': atr,
        'notionnel': notional,
    }
    await save_portfolio()
    e = discord.Embed(title=f"{'🟢' if direction=='LONG' else '🔴'} Position Humaine Ouverte — {asset_name}", color=0x2ecc71 if direction=='LONG' else 0xe74c3c)
    e.add_field(name="Valeur du Trade", value=f"**{notional:,.2f}$** (Marge {marge:.1f}$ × {levier}x)", inline=False)
    e.add_field(name="Entrée / TP / SL", value=f"Entrée: **{prix:,.2f}$** | 🎯 TP: **{tp:,.2f}$** | 🛑 SL: **{sl:,.2f}$**", inline=False)
    await msg.edit(content=None, embed=e)

@bot.command()
async def buy(ctx, *, asset_arg: str = None):
    asset_name = resolve_asset(asset_arg or "")
    if not asset_name: return await ctx.send("Usage: `!buy btc|sol|or|argent|platine|oil`")
    await open_human_position(ctx, asset_name, 'LONG')

@bot.command()
async def sell(ctx, *, asset_arg: str = None):
    asset_name = resolve_asset(asset_arg or "")
    if not asset_name: return await ctx.send("Usage: `!sell btc|sol|or|argent|platine|oil`")
    await open_human_position(ctx, asset_name, 'SHORT')

@bot.command()
async def close(ctx, *, asset_arg: str = None):
    asset_name = resolve_asset(asset_arg or "")
    if not asset_name or asset_name not in human_trader['positions']:
        return await ctx.send("Aucune position active sur cet actif.")
    pos = human_trader['positions'][asset_name]
    ticker = ASSETS[asset_name]
    if ticker.endswith('USDT'):
        ohlcv = binance.fetch_ohlcv(ticker, '1m', limit=1)
        prix_exit = float(ohlcv[-1][4]) if ohlcv else pos['price']
    else:
        hist = yf.Ticker(ticker).history(period='1d', interval='1m')
        prix_exit = float(hist['Close'].iloc[-1]) if not hist.empty else pos['price']

    levier = LEVERAGE_MAP.get(asset_name, 10)
    days = (time.time() - pos['open_time']) / 86400
    diff_pct = (prix_exit - pos['price']) / pos['price'] if pos['type'] == 'LONG' else (pos['price'] - prix_exit) / pos['price']
    notional = pos.get('notionnel', pos['margin'] * levier)
    gross = notional * diff_pct
    frais = notional * (COUT_PAR_LEG * 2 + days * FUNDING_RATE_DAY)
    profit = gross - frais

    human_trader['capital'] += profit
    human_trader['trades'] += 1
    human_trader['total_fees'] = human_trader.get('total_fees', 0.0) + frais
    if profit > 0: human_trader['wins'] += 1
    del human_trader['positions'][asset_name]
    await save_portfolio()
    await ctx.send(f"{'🟢' if profit>0 else '🔴'} Position **{asset_name}** fermée : **{profit:+.2f}$** net (Brut: {gross:+.2f}$ | Frais: -{frais:.2f}$) | Capital: **{human_trader['capital']:.2f}$**")


@tasks.loop(seconds=120)
async def watchdog():
    await bot.wait_until_ready()
    if not market_scanner.is_running():
        try:
            market_scanner.restart()
        except Exception:
            market_scanner.start()

@bot.event
async def on_ready():
    await load_portfolio()
    print(f"✅ Symbiosis Algorithm Trading V8.5 prêt ({len(paper_portfolio)} bots en ligne).", flush=True)
    market_scanner.start()
    watchdog.start()

keep_alive()
bot.run(TOKEN)
