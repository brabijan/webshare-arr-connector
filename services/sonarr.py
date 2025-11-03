"""Sonarr API client"""
import requests
import logging
import config

logger = logging.getLogger(__name__)


class SonarrClient:
    """Client for Sonarr API"""

    def __init__(self):
        self.base_url = config.SONARR_URL.rstrip('/')
        self.api_key = config.SONARR_API_KEY
        self.headers = {'X-Api-Key': self.api_key}

    def get_missing_episodes(self, page_size=100, monitored=True):
        """
        Get list of missing episodes

        Args:
            page_size (int): Number of results per page
            monitored (bool): Only return monitored episodes

        Returns:
            list: List of missing episodes
        """
        url = f"{self.base_url}/api/v3/wanted/missing"
        params = {
            'pageSize': page_size,
            'monitored': str(monitored).lower(),
            'includeSeries': 'true'
        }

        try:
            logger.info("Fetching missing episodes from Sonarr")
            response = requests.get(
                url,
                headers=self.headers,
                params=params,
                timeout=15
            )

            if response.status_code == 200:
                data = response.json()
                records = data.get('records', [])
                logger.info(f"Found {len(records)} missing episodes")
                return records
            else:
                logger.error(f"Sonarr API error: {response.status_code} - {response.text[:200]}")
                return []

        except Exception as e:
            logger.error(f"Error fetching missing episodes: {e}")
            return []

    def parse_webhook(self, webhook_data):
        """
        Parse Sonarr webhook payload

        Args:
            webhook_data (dict): Webhook payload

        Returns:
            dict: Parsed information for searching
        """
        event_type = webhook_data.get('eventType')
        series = webhook_data.get('series', {})
        episodes = webhook_data.get('episodes', [])

        if not episodes:
            logger.warning("No episodes in webhook payload")
            return None

        episode = episodes[0]  # Take first episode

        return {
            'source': 'sonarr',
            'event_type': event_type,
            'series_id': series.get('id'),
            'series_title': series.get('title'),
            'series_year': series.get('year'),
            'tvdb_id': series.get('tvdbId'),
            'imdb_id': series.get('imdbId'),
            'episode_id': episode.get('id'),
            'season': episode.get('seasonNumber'),
            'episode': episode.get('episodeNumber'),
            'episode_title': episode.get('title'),
            'air_date': episode.get('airDate')
        }

    def generate_search_queries(self, item_info):
        """
        Generate multiple search query variations for an episode

        Args:
            item_info (dict): Parsed item information

        Returns:
            list: List of search query strings
        """
        queries = []
        title = item_info.get('series_title', '')
        season = item_info.get('season')
        episode = item_info.get('episode')

        if not title or season is None or episode is None:
            logger.warning("Missing title or episode info for query generation")
            return queries

        # Primary query: "Series Title S01E01"
        queries.append(f"{title} S{season:02d}E{episode:02d}")

        # Variation without spaces in S/E
        queries.append(f"{title} S{season:02d}E{episode:02d}".replace(" S", "S"))

        # Variation with dots instead of spaces
        queries.append(f"{title.replace(' ', '.')} S{season:02d}E{episode:02d}")

        # With year if available
        if item_info.get('series_year'):
            queries.append(f"{title} {item_info['series_year']} S{season:02d}E{episode:02d}")

        # Alternative format: "Series Title 1x01"
        queries.append(f"{title} {season}x{episode:02d}")

        logger.info(f"Generated {len(queries)} search queries for {title} S{season:02d}E{episode:02d}")
        return queries


# Singleton instance
_client = None

def get_client():
    """Get Sonarr client singleton"""
    global _client
    if _client is None:
        _client = SonarrClient()
    return _client
