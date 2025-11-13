"""Configuration module for Webshare Downloader"""
import os
from pathlib import Path

# Base directory
BASE_DIR = Path(__file__).parent.absolute()

# Database
DATABASE_PATH = os.getenv('DATABASE_PATH', str(BASE_DIR / 'data' / 'downloader.db'))

# Webshare credentials
WEBSHARE_USER = os.getenv('WEBSHARE_USER', 'mates91')
WEBSHARE_PASS = os.getenv('WEBSHARE_PASS', 'afdm54F3')
WEBSHARE_API_URL = 'https://webshare.cz/api'

# pyLoad settings
PYLOAD_URL = os.getenv('PYLOAD_URL', 'https://pyload.homelab.carpiftw.cz')
PYLOAD_USER = os.getenv('PYLOAD_USER', 'pyload')
PYLOAD_PASS = os.getenv('PYLOAD_PASS', 'v4G#2uPXj5dvL9%aWHLs')
PYLOAD_DOWNLOAD_DIR = os.getenv('PYLOAD_DOWNLOAD_DIR', '/mnt/sdb1/pyload_downlaoded')

# File mover settings
MONITOR_INTERVAL_SECONDS = int(os.getenv('MONITOR_INTERVAL_SECONDS', '60'))  # 1 minute

# Plex settings (for future rescan functionality)
PLEX_URL = os.getenv('PLEX_URL', '')
PLEX_TOKEN = os.getenv('PLEX_TOKEN', '')

# Sonarr settings
SONARR_URL = os.getenv('SONARR_URL', 'https://sonarr.homelab.carpiftw.cz')
SONARR_API_KEY = os.getenv('SONARR_API_KEY', '66bff25cbaa142b7b925a92078a065a9')

# Radarr settings
RADARR_URL = os.getenv('RADARR_URL', 'https://radarr.homelab.carpiftw.cz')
RADARR_API_KEY = os.getenv('RADARR_API_KEY', '')

# Search preferences
PREFER_CZECH = os.getenv('PREFER_CZECH', 'true').lower() == 'true'
MIN_QUALITY = os.getenv('MIN_QUALITY', '720p')
MAX_SIZE_GB = int(os.getenv('MAX_SIZE_GB', '50'))
SEARCH_LIMIT = int(os.getenv('SEARCH_LIMIT', '50'))

# Cache settings (in days)
CACHE_TTL_DAYS = int(os.getenv('CACHE_TTL_DAYS', '7'))
HISTORY_TTL_DAYS = int(os.getenv('HISTORY_TTL_DAYS', '30'))

# Logging
LOG_DIR = BASE_DIR / 'logs'
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
LOG_BACKUP_COUNT = 5

# Flask settings
SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'
HOST = os.getenv('HOST', '0.0.0.0')
PORT = int(os.getenv('PORT', '5050'))

# Quality scores for ranking
QUALITY_SCORES = {
    '2160p': 40,
    '1080p': 30,
    '720p': 20,
    '480p': 10,
    '360p': 5
}

# Source scores for ranking
SOURCE_SCORES = {
    'Ultra HD Blu-ray': 30,
    'Blu-ray': 25,
    'WEB-DL': 20,
    'HDTV': 10,
    'DVD': 5
}

# Codec scores for ranking
CODEC_SCORES = {
    'H.265': 10,
    'HEVC': 10,
    'H.264': 8,
    'x264': 8,
    'x265': 10,
    'XviD': 3
}

# Language priority bonus
CZECH_LANGUAGE_BONUS = 50
