"""Webshare API client"""
import requests
import xml.etree.ElementTree as ET
import logging
import config

logger = logging.getLogger(__name__)


class WebshareClient:
    """Client for Webshare.cz API"""

    def __init__(self):
        self.api_url = config.WEBSHARE_API_URL
        self.auth = (config.WEBSHARE_USER, config.WEBSHARE_PASS)

    def search(self, query, category='video', limit=None, sort='rating'):
        """
        Search for files on Webshare

        Args:
            query (str): Search query
            category (str): Category filter (video, audio, images, docs, archives)
            limit (int): Maximum number of results
            sort (str): Sort order (recent, rating, largest, smallest)

        Returns:
            list: List of file dictionaries
        """
        if limit is None:
            limit = config.SEARCH_LIMIT

        url = f"{self.api_url}/search/"
        payload = {
            'what': query,
            'category': category,
            'sort': sort,
            'limit': limit
        }

        try:
            logger.info(f"Searching Webshare for: {query} (limit={limit})")
            response = requests.post(
                url,
                data=payload,
                auth=self.auth,
                timeout=15
            )

            if response.status_code != 200:
                logger.error(f"Webshare search failed: {response.status_code} - {response.text[:200]}")
                return []

            # Parse XML response
            root = ET.fromstring(response.text)
            files = []

            for file_elem in root.findall('file'):
                try:
                    file_data = {
                        'ident': file_elem.find('ident').text,
                        'name': file_elem.find('name').text,
                        'size': int(file_elem.find('size').text) if file_elem.find('size') is not None else 0,
                        'type': file_elem.find('type').text if file_elem.find('type') is not None else '',
                        'positive_votes': int(file_elem.find('positive_votes').text) if file_elem.find('positive_votes') is not None else 0,
                        'negative_votes': int(file_elem.find('negative_votes').text) if file_elem.find('negative_votes') is not None else 0,
                        'password': file_elem.find('password').text == 'true' if file_elem.find('password') is not None else False
                    }
                    files.append(file_data)
                except Exception as e:
                    logger.warning(f"Error parsing file element: {e}")
                    continue

            logger.info(f"Found {len(files)} results for query: {query}")
            return files

        except requests.exceptions.RequestException as e:
            logger.error(f"Webshare search request failed: {e}")
            return []
        except ET.ParseError as e:
            logger.error(f"XML parse error: {e} - Response: {response.text[:200]}")
            return []

    def get_file_info(self, ident):
        """
        Get detailed information about a file

        Args:
            ident (str): File identifier

        Returns:
            dict: File information or None
        """
        url = f"{self.api_url}/file_info/"
        payload = {'ident': ident}

        try:
            logger.debug(f"Getting file info for: {ident}")
            response = requests.post(
                url,
                data=payload,
                auth=self.auth,
                timeout=10
            )

            if response.status_code != 200:
                logger.error(f"File info request failed: {response.status_code}")
                return None

            root = ET.fromstring(response.text)

            return {
                'name': root.find('name').text if root.find('name') is not None else '',
                'description': root.find('description').text if root.find('description') is not None else '',
                'size': int(root.find('size').text) if root.find('size') is not None else 0,
                'type': root.find('type').text if root.find('type') is not None else '',
                'available': root.find('available').text == 'true' if root.find('available') is not None else False,
                'positive_votes': int(root.find('positive_votes').text) if root.find('positive_votes') is not None else 0,
                'negative_votes': int(root.find('negative_votes').text) if root.find('negative_votes') is not None else 0
            }

        except Exception as e:
            logger.error(f"Error getting file info: {e}")
            return None

    def get_direct_link(self, url_or_ident):
        """
        Convert Webshare URL or ident to direct download link
        (Reused from original app)

        Args:
            url_or_ident (str): Webshare URL or file identifier

        Returns:
            tuple: (direct_link, error_message)
        """
        try:
            # If it looks like a URL, extract ident
            if 'webshare.cz' in url_or_ident:
                from urllib.parse import urlparse

                parsed = urlparse(url_or_ident)

                if 'webshare.cz' not in parsed.netloc:
                    return None, "Invalid Webshare URL - must be webshare.cz domain"

                # Check fragment first (for SPA URLs with #)
                path_to_parse = parsed.fragment if parsed.fragment else parsed.path
                path_parts = [p for p in path_to_parse.split('/') if p]

                # Find 'file' in path and get the next part as ident
                try:
                    file_index = path_parts.index('file')
                    ident = path_parts[file_index + 1] if len(path_parts) > file_index + 1 else None
                except (ValueError, IndexError):
                    ident = None

                if not ident:
                    return None, f"Cannot extract file identifier from URL: {url_or_ident}"
            else:
                # Assume it's already an ident
                ident = url_or_ident

            # Webshare API endpoint
            api_url = f"{self.api_url}/file_link/"

            payload = {
                'ident': ident,
                'wst': ''  # Can be empty for direct link
            }

            logger.debug(f"Getting direct link for ident: {ident}")
            response = requests.post(
                api_url,
                data=payload,
                auth=self.auth,
                timeout=10
            )

            if response.status_code == 200:
                # Webshare API returns XML
                try:
                    root = ET.fromstring(response.text)
                    link = root.find('link')
                    if link is not None and link.text:
                        logger.info(f"Got direct link for ident: {ident}")
                        return link.text, None
                    else:
                        status = root.find('status')
                        status_text = status.text if status is not None else 'Unknown'
                        return None, f"No link in response. Status: {status_text}"
                except ET.ParseError as e:
                    return None, f"XML parse error: {str(e)} - Response: {response.text[:200]}"
            else:
                return None, f"API error: {response.status_code} - {response.text[:200]}"

        except Exception as e:
            logger.error(f"Error getting direct link: {e}")
            return None, f"Error: {str(e)}"


# Singleton instance
_client = None

def get_client():
    """Get Webshare client singleton"""
    global _client
    if _client is None:
        _client = WebshareClient()
    return _client
