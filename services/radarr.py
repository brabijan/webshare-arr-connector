"""Radarr API client"""
import requests
import logging
import config

logger = logging.getLogger(__name__)


class RadarrClient:
    """Client for Radarr API"""

    def __init__(self):
        self.base_url = config.RADARR_URL.rstrip('/')
        self.api_key = config.RADARR_API_KEY
        self.headers = {'X-Api-Key': self.api_key}

    def get_missing_movies(self, page_size=100, monitored=True):
        """
        Get list of missing movies

        Args:
            page_size (int): Number of results per page
            monitored (bool): Only return monitored movies

        Returns:
            list: List of missing movies
        """
        url = f"{self.base_url}/api/v3/wanted/missing"
        params = {
            'pageSize': page_size,
            'monitored': str(monitored).lower()
        }

        try:
            logger.info("Fetching missing movies from Radarr")
            response = requests.get(
                url,
                headers=self.headers,
                params=params,
                timeout=15
            )

            if response.status_code == 200:
                data = response.json()
                records = data.get('records', [])
                logger.info(f"Found {len(records)} missing movies")
                return records
            else:
                logger.error(f"Radarr API error: {response.status_code} - {response.text[:200]}")
                return []

        except Exception as e:
            logger.error(f"Error fetching missing movies: {e}")
            return []

    def get_all_monitored_movies(self):
        """
        Get all monitored movies without files from Radarr
        Uses /api/v3/movie endpoint for full movie objects with path field

        Returns:
            list: List of monitored movies without files
        """
        url = f"{self.base_url}/api/v3/movie"

        try:
            logger.info("Fetching all movies from Radarr")
            response = requests.get(
                url,
                headers=self.headers,
                timeout=15
            )

            if response.status_code == 200:
                all_movies = response.json()

                # Filter for monitored movies without files
                missing_movies = [
                    m for m in all_movies
                    if m.get('monitored') and not m.get('hasFile')
                ]

                logger.info(f"Found {len(missing_movies)} monitored movies without files")
                return missing_movies
            else:
                logger.error(f"Radarr API error: {response.status_code} - {response.text[:200]}")
                return []

        except Exception as e:
            logger.error(f"Error fetching movies: {e}")
            return []

    def parse_webhook(self, webhook_data):
        """
        Parse Radarr webhook payload

        Args:
            webhook_data (dict): Webhook payload

        Returns:
            dict: Parsed information for searching
        """
        event_type = webhook_data.get('eventType')
        movie = webhook_data.get('movie', {})

        if not movie:
            logger.warning("No movie in webhook payload")
            return None

        return {
            'source': 'radarr',
            'event_type': event_type,
            'movie_id': movie.get('id'),
            'title': movie.get('title'),
            'year': movie.get('year'),
            'tmdb_id': movie.get('tmdbId'),
            'imdb_id': movie.get('imdbId'),
            'release_date': movie.get('releaseDate'),
            'folder_path': movie.get('folderPath')
        }

    def generate_search_queries(self, item_info):
        """
        Generate multiple search query variations for a movie

        Args:
            item_info (dict): Parsed item information

        Returns:
            list: List of search query strings
        """
        queries = []
        title = item_info.get('title', '')
        year = item_info.get('year')

        if not title:
            logger.warning("Missing title for query generation")
            return queries

        # Primary query: "Movie Title Year"
        if year:
            queries.append(f"{title} {year}")
        else:
            queries.append(title)

        # Variation with dots instead of spaces
        if year:
            queries.append(f"{title.replace(' ', '.')} {year}")
        else:
            queries.append(title.replace(' ', '.'))

        # Without year (for wider search)
        queries.append(title)

        # With parentheses around year
        if year:
            queries.append(f"{title} ({year})")

        # Alternative: dot separated with year
        if year:
            queries.append(f"{title.replace(' ', '.')}.{year}")

        logger.info(f"Generated {len(queries)} search queries for {title} ({year})")
        return queries


# Singleton instance
_client = None

def get_client():
    """Get Radarr client singleton"""
    global _client
    if _client is None:
        _client = RadarrClient()
    return _client
