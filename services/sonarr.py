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

    def get_all_series(self):
        """
        Get all monitored series from Sonarr

        Returns:
            list: List of series with statistics
        """
        url = f"{self.base_url}/api/v3/series"

        try:
            logger.info("Fetching all series from Sonarr")
            response = requests.get(
                url,
                headers=self.headers,
                timeout=15
            )

            if response.status_code == 200:
                all_series = response.json()
                # Filter for monitored series
                monitored_series = [s for s in all_series if s.get('monitored')]
                logger.info(f"Found {len(monitored_series)} monitored series")
                return monitored_series
            else:
                logger.error(f"Sonarr API error: {response.status_code} - {response.text[:200]}")
                return []

        except Exception as e:
            logger.error(f"Error fetching series: {e}")
            return []

    def get_series_by_id(self, series_id):
        """
        Get series details by ID

        Args:
            series_id (int): Sonarr series ID

        Returns:
            dict: Series details, or None if not found
        """
        url = f"{self.base_url}/api/v3/series/{series_id}"

        try:
            logger.info(f"Fetching series {series_id} from Sonarr")
            response = requests.get(
                url,
                headers=self.headers,
                timeout=15
            )

            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Sonarr API error: {response.status_code} - {response.text[:200]}")
                return None

        except Exception as e:
            logger.error(f"Error fetching series {series_id}: {e}")
            return None

    def get_episodes(self, series_id):
        """
        Get all episodes for a series

        Args:
            series_id (int): Sonarr series ID

        Returns:
            list: List of episodes
        """
        url = f"{self.base_url}/api/v3/episode"
        params = {'seriesId': series_id}

        try:
            logger.debug(f"Fetching episodes for series {series_id}")
            response = requests.get(
                url,
                headers=self.headers,
                params=params,
                timeout=15
            )

            if response.status_code == 200:
                episodes = response.json()
                logger.debug(f"Found {len(episodes)} episodes for series {series_id}")
                return episodes
            else:
                logger.error(f"Sonarr API error: {response.status_code} - {response.text[:200]}")
                return []

        except Exception as e:
            logger.error(f"Error fetching episodes for series {series_id}: {e}")
            return []

    def get_series_missing_episodes(self, series_id):
        """
        Get missing episodes for a specific series, grouped by season

        Args:
            series_id (int): Sonarr series ID

        Returns:
            dict: Episodes grouped by season number
                  {1: [{episode1}, {episode2}], 2: [{episode3}]}
        """
        url = f"{self.base_url}/api/v3/episode"
        params = {
            'seriesId': series_id
        }

        try:
            logger.info(f"Fetching episodes for series ID {series_id}")
            response = requests.get(
                url,
                headers=self.headers,
                params=params,
                timeout=15
            )

            if response.status_code == 200:
                all_episodes = response.json()

                # Filter for monitored episodes without files
                missing_episodes = [
                    ep for ep in all_episodes
                    if ep.get('monitored') and not ep.get('hasFile')
                ]

                # Group by season
                seasons = {}
                for episode in missing_episodes:
                    season_num = episode.get('seasonNumber')
                    if season_num is not None:
                        if season_num not in seasons:
                            seasons[season_num] = []
                        seasons[season_num].append(episode)

                logger.info(f"Found {len(missing_episodes)} missing episodes across {len(seasons)} seasons")
                return seasons
            else:
                logger.error(f"Sonarr API error: {response.status_code} - {response.text[:200]}")
                return {}

        except Exception as e:
            logger.error(f"Error fetching episodes: {e}")
            return {}

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

    def get_episode_file(self, episode_file_id):
        """
        Get episode file details by ID

        Args:
            episode_file_id: Episode file ID from Sonarr

        Returns:
            dict: Episode file details, or None if error
        """
        try:
            url = f"{self.base_url}/api/v3/episodefile/{episode_file_id}"
            headers = {"X-Api-Key": self.api_key}

            logger.debug(f"Getting episode file {episode_file_id} from Sonarr")
            response = requests.get(url, headers=headers, timeout=30)

            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get episode file {episode_file_id}: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Error getting episode file {episode_file_id}: {str(e)}")
            return None

    def delete_episode_file(self, episode_file_id):
        """
        Delete episode file from Sonarr

        Args:
            episode_file_id: Episode file ID to delete

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            url = f"{self.base_url}/api/v3/episodefile/{episode_file_id}"
            headers = {"X-Api-Key": self.api_key}

            logger.info(f"Deleting episode file {episode_file_id} from Sonarr")
            response = requests.delete(url, headers=headers, timeout=30)

            if response.status_code in [200, 204]:
                logger.info(f"Episode file {episode_file_id} deleted successfully")
                return True
            else:
                logger.error(f"Failed to delete episode file {episode_file_id}: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Error deleting episode file {episode_file_id}: {str(e)}")
            return False

    def get_series_files(self, series_id):
        """
        Get all episode files for a series

        Args:
            series_id: Sonarr series ID

        Returns:
            list: List of episode file dicts, or empty list if error
        """
        try:
            url = f"{self.base_url}/api/v3/episodefile"
            headers = {"X-Api-Key": self.api_key}
            params = {"seriesId": series_id}

            logger.debug(f"Getting episode files for series {series_id}")
            response = requests.get(url, headers=headers, params=params, timeout=30)

            if response.status_code == 200:
                files = response.json()
                logger.debug(f"Found {len(files)} episode files for series {series_id}")
                return files
            else:
                logger.error(f"Failed to get episode files for series {series_id}: {response.status_code}")
                return []

        except Exception as e:
            logger.error(f"Error getting episode files for series {series_id}: {str(e)}")
            return []

    def trigger_series_rescan(self, series_id):
        """
        Trigger rescan for specific series (PLACEHOLDER for future use)

        Args:
            series_id (int): Sonarr series ID

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            url = f"{self.base_url}/api/v3/command"
            payload = {
                'name': 'RescanSeries',
                'seriesId': series_id
            }

            logger.info(f"Triggering rescan for series {series_id}")

            response = requests.post(url, json=payload, headers=self.headers, timeout=30)

            if response.status_code in [200, 201]:
                logger.info(f"Successfully triggered rescan for series {series_id}")
                return True
            else:
                logger.error(f"Failed to trigger rescan: {response.status_code} - {response.text[:200]}")
                return False

        except Exception as e:
            logger.error(f"Error triggering series rescan: {str(e)}")
            return False

    def trigger_season_rescan(self, series_id, season_number):
        """
        Trigger rescan for specific season (PLACEHOLDER for future use)

        Args:
            series_id (int): Sonarr series ID
            season_number (int): Season number

        Returns:
            bool: True if successful, False otherwise
        """
        # Sonarr doesn't have season-specific rescan, so trigger series rescan
        logger.info(f"Triggering series rescan for series {series_id} (season {season_number})")
        return self.trigger_series_rescan(series_id)


# Singleton instance
_client = None

def get_client():
    """Get Sonarr client singleton"""
    global _client
    if _client is None:
        _client = SonarrClient()
    return _client
