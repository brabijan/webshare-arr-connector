"""Main Flask application"""
from flask import Flask
import logging
from logging.handlers import RotatingFileHandler
import config
from models.database import init_db, cleanup_expired
from routes.web import web_bp
from routes.api import api_bp
from routes.webhooks import webhooks_bp

# Create Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = config.SECRET_KEY

# Setup logging
config.LOG_DIR.mkdir(exist_ok=True)

# File handler
file_handler = RotatingFileHandler(
    config.LOG_DIR / 'app.log',
    maxBytes=config.LOG_MAX_BYTES,
    backupCount=config.LOG_BACKUP_COUNT
)
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter(
    '%(asctime)s %(levelname)s [%(name)s] %(message)s'
)
file_handler.setFormatter(file_formatter)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO if not config.DEBUG else logging.DEBUG)
console_formatter = logging.Formatter(
    '%(levelname)s [%(name)s] %(message)s'
)
console_handler.setFormatter(console_formatter)

# Root logger
root_logger = logging.getLogger()
root_logger.setLevel(getattr(logging, config.LOG_LEVEL))
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

logger = logging.getLogger(__name__)

# Register blueprints
app.register_blueprint(web_bp)
app.register_blueprint(api_bp)
app.register_blueprint(webhooks_bp)


@app.before_request
def before_first_request():
    """Initialize database on first request"""
    if not hasattr(app, 'db_initialized'):
        logger.info("Initializing database...")
        init_db()
        app.db_initialized = True
        logger.info("Database initialized successfully")


@app.cli.command('cleanup')
def cleanup_command():
    """CLI command to cleanup expired cache and old history"""
    logger.info("Running cleanup...")
    cleanup_expired()
    logger.info("Cleanup completed")


@app.cli.command('search-missing')
def search_missing_command():
    """CLI command to search for missing items in Sonarr/Radarr"""
    from services import search

    logger.info("Searching for missing Sonarr episodes...")
    sonarr_pending = search.search_missing_items(source='sonarr', limit=10)
    logger.info(f"Created {len(sonarr_pending)} pending confirmations from Sonarr")

    logger.info("Searching for missing Radarr movies...")
    radarr_pending = search.search_missing_items(source='radarr', limit=10)
    logger.info(f"Created {len(radarr_pending)} pending confirmations from Radarr")

    logger.info(f"Total: {len(sonarr_pending) + len(radarr_pending)} pending confirmations")


if __name__ == '__main__':
    logger.info(f"Starting Webshare Downloader on {config.HOST}:{config.PORT}")
    logger.info(f"Debug mode: {config.DEBUG}")
    logger.info(f"Database: {config.DATABASE_PATH}")

    app.run(
        host=config.HOST,
        port=config.PORT,
        debug=config.DEBUG
    )
