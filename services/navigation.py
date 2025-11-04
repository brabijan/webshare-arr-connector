"""Navigation helper for determining where to go after download"""
import logging
from services import sonarr, radarr

logger = logging.getLogger(__name__)


def get_navigation_info(source, series_id=None, season_num=None):
    """
    Determine navigation after downloading an item

    Args:
        source: 'sonarr' or 'radarr'
        series_id: Sonarr series ID (for TV shows)
        season_num: Season number (for TV shows)

    Returns:
        dict: {
            'next_action': 'stay' | 'go_to_seasons' | 'go_to_series_list',
            'remaining_in_season': int,
            'remaining_in_series': int,
            'has_other_missing_series': bool
        }
    """
    try:
        if source == 'radarr':
            # Movies always go back to main list
            return {
                'next_action': 'go_to_series_list',
                'remaining_in_season': 0,
                'remaining_in_series': 0,
                'has_other_missing_series': True  # Assume there might be other content
            }

        elif source == 'sonarr' and series_id:
            sonarr_client = sonarr.get_client()

            # Get missing episodes for this series
            seasons_dict = sonarr_client.get_series_missing_episodes(series_id)

            # Count remaining in current season
            remaining_in_season = len(seasons_dict.get(season_num, []))

            # Count remaining in all seasons
            remaining_in_series = sum(len(episodes) for episodes in seasons_dict.values())

            # Check if other series have missing episodes
            all_series = sonarr_client.get_all_series()
            has_other_missing = False
            for s in all_series:
                if s.get('id') != series_id:
                    stats = s.get('statistics', {})
                    missing = stats.get('episodeCount', 0) - stats.get('episodeFileCount', 0)
                    if missing > 0:
                        has_other_missing = True
                        break

            # Determine next action
            if remaining_in_season > 0:
                next_action = 'stay'
            elif remaining_in_series > 0:
                next_action = 'go_to_seasons'
            else:
                next_action = 'go_to_series_list'

            logger.info(f"Navigation info: {next_action}, remaining in season: {remaining_in_season}, in series: {remaining_in_series}")

            return {
                'next_action': next_action,
                'remaining_in_season': remaining_in_season,
                'remaining_in_series': remaining_in_series,
                'has_other_missing_series': has_other_missing
            }

        else:
            # Fallback
            return {
                'next_action': 'go_to_series_list',
                'remaining_in_season': 0,
                'remaining_in_series': 0,
                'has_other_missing_series': False
            }

    except Exception as e:
        logger.error(f"Error getting navigation info: {e}", exc_info=True)
        # Fallback to series list on error
        return {
            'next_action': 'go_to_series_list',
            'remaining_in_season': 0,
            'remaining_in_series': 0,
            'has_other_missing_series': False
        }
