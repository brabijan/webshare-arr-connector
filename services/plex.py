"""Plex API client (PLACEHOLDER for future use)"""
import logging
import config

logger = logging.getLogger(__name__)


class PlexClient:
    """Client for Plex API (PLACEHOLDER)"""

    def __init__(self):
        self.base_url = config.PLEX_URL.rstrip('/') if config.PLEX_URL else None
        self.token = config.PLEX_TOKEN

        if not self.base_url or not self.token:
            logger.warning("Plex URL or token not configured - Plex integration disabled")

    def trigger_library_scan(self, path=None):
        """
        Trigger library scan for specific path

        Args:
            path (str): Optional path to scan. If None, scans all libraries.

        Returns:
            bool: True if successful, False otherwise
        """
        if not self.base_url or not self.token:
            logger.debug("Plex not configured, skipping library scan")
            return False

        try:
            from plexapi.server import PlexServer

            logger.debug(f"Connecting to Plex server: {self.base_url}")
            plex = PlexServer(self.base_url, self.token)

            if path:
                # Find library containing this path
                logger.debug(f"Searching for library containing path: {path}")
                for section in plex.library.sections():
                    for location in section.locations:
                        if path.startswith(location):
                            logger.info(f"Triggering Plex library scan for: {section.title} (path: {path})")
                            section.update()
                            logger.info(f"Successfully triggered Plex scan for library: {section.title}")
                            return True

                logger.warning(f"No Plex library found for path: {path}")
                return False
            else:
                # Scan all libraries
                logger.info("Triggering full Plex library scan (all libraries)")
                scanned_count = 0
                for section in plex.library.sections():
                    logger.debug(f"Scanning Plex library: {section.title}")
                    section.update()
                    scanned_count += 1

                logger.info(f"Successfully triggered Plex scan for {scanned_count} libraries")
                return True

        except ImportError:
            logger.error("plexapi module not installed - run 'pip install plexapi'")
            return False
        except Exception as e:
            logger.error(f"Error triggering Plex library scan: {str(e)}", exc_info=True)
            return False

    def trigger_full_library_scan(self):
        """
        Trigger full library scan (PLACEHOLDER for future use)

        Returns:
            bool: True if successful, False otherwise
        """
        return self.trigger_library_scan(path=None)


# Singleton instance
_client = None

def get_client():
    """Get Plex client singleton"""
    global _client
    if _client is None:
        _client = PlexClient()
    return _client
