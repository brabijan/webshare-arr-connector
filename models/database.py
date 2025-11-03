"""Database models for Webshare Downloader"""
from datetime import datetime, timedelta
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import json
import config

Base = declarative_base()

class SearchCache(Base):
    """Cache for Webshare search results"""
    __tablename__ = 'search_cache'

    id = Column(Integer, primary_key=True)
    query = Column(String(500), unique=True, nullable=False, index=True)
    results_json = Column(Text, nullable=False)  # JSON array of results
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)

    def __init__(self, query, results):
        self.query = query
        self.results_json = json.dumps(results)
        self.created_at = datetime.utcnow()
        self.expires_at = self.created_at + timedelta(days=config.CACHE_TTL_DAYS)

    @property
    def results(self):
        """Parse JSON results"""
        return json.loads(self.results_json)

    @property
    def is_expired(self):
        """Check if cache entry is expired"""
        return datetime.utcnow() > self.expires_at


class DownloadHistory(Base):
    """History of downloaded items"""
    __tablename__ = 'download_history'

    id = Column(Integer, primary_key=True)
    source = Column(String(20), nullable=False)  # 'sonarr' or 'radarr'
    source_id = Column(Integer, nullable=True)  # ID from Sonarr/Radarr
    item_title = Column(String(500), nullable=False)
    season = Column(Integer, nullable=True)  # For TV shows
    episode = Column(Integer, nullable=True)  # For TV shows
    year = Column(Integer, nullable=True)  # For movies

    webshare_ident = Column(String(100), nullable=False)
    filename = Column(String(500), nullable=False)
    file_size = Column(Integer, nullable=True)  # In bytes
    quality = Column(String(20), nullable=True)  # 720p, 1080p, etc.
    language = Column(String(50), nullable=True)  # CZ, EN, etc.

    pyload_package_id = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False, default='pending')  # pending, sent, failed
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        if self.episode is not None:
            return f"<DownloadHistory {self.item_title} S{self.season:02d}E{self.episode:02d}>"
        return f"<DownloadHistory {self.item_title} ({self.year})>"


class PendingConfirmation(Base):
    """Items waiting for user confirmation"""
    __tablename__ = 'pending_confirmations'

    id = Column(Integer, primary_key=True)
    source = Column(String(20), nullable=False)  # 'sonarr' or 'radarr'
    source_id = Column(Integer, nullable=True)
    item_title = Column(String(500), nullable=False)
    season = Column(Integer, nullable=True)
    episode = Column(Integer, nullable=True)
    year = Column(Integer, nullable=True)

    search_query = Column(String(500), nullable=False)
    results_json = Column(Text, nullable=False)  # JSON array of top results

    status = Column(String(20), nullable=False, default='pending')  # pending, confirmed, rejected
    selected_index = Column(Integer, nullable=True)  # Index of selected result

    created_at = Column(DateTime, default=datetime.utcnow)
    confirmed_at = Column(DateTime, nullable=True)

    @property
    def results(self):
        """Parse JSON results"""
        return json.loads(self.results_json)

    @results.setter
    def results(self, value):
        """Set results as JSON"""
        self.results_json = json.dumps(value)

    def __repr__(self):
        if self.episode is not None:
            return f"<PendingConfirmation {self.item_title} S{self.season:02d}E{self.episode:02d}>"
        return f"<PendingConfirmation {self.item_title} ({self.year})>"


# Database engine and session
engine = None
SessionLocal = None

def init_db():
    """Initialize database"""
    global engine, SessionLocal

    # Create engine
    engine = create_engine(
        f'sqlite:///{config.DATABASE_PATH}',
        echo=config.DEBUG,
        connect_args={'check_same_thread': False}
    )

    # Create tables
    Base.metadata.create_all(bind=engine)

    # Create session factory
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    return engine


def get_db():
    """Get database session (for context manager)"""
    global SessionLocal
    if SessionLocal is None:
        init_db()

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_session():
    """Get database session (direct call)"""
    global SessionLocal
    if SessionLocal is None:
        init_db()
    return SessionLocal()


def cleanup_expired():
    """Clean up expired cache entries and old history"""
    db = get_db_session()
    try:
        # Delete expired cache
        db.query(SearchCache).filter(SearchCache.expires_at < datetime.utcnow()).delete()

        # Delete old history
        history_cutoff = datetime.utcnow() - timedelta(days=config.HISTORY_TTL_DAYS)
        db.query(DownloadHistory).filter(DownloadHistory.created_at < history_cutoff).delete()

        # Delete old confirmed/rejected pending items (keep for 7 days)
        pending_cutoff = datetime.utcnow() - timedelta(days=7)
        db.query(PendingConfirmation).filter(
            PendingConfirmation.status.in_(['confirmed', 'rejected']),
            PendingConfirmation.confirmed_at < pending_cutoff
        ).delete()

        db.commit()
    finally:
        db.close()
