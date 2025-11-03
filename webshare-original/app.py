from flask import Flask, request, jsonify, render_template
import requests
import os
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

app = Flask(__name__)

# Webshare credentials from environment
WEBSHARE_USER = os.getenv('WEBSHARE_USER', 'mates91')
WEBSHARE_PASS = os.getenv('WEBSHARE_PASS', 'afdm54F3')

# pyLoad settings
PYLOAD_URL = os.getenv('PYLOAD_URL', 'http://pyload.homelab.carpiftw.cz')
PYLOAD_USER = os.getenv('PYLOAD_USER', 'admin')
PYLOAD_PASS = os.getenv('PYLOAD_PASS', 'admin')


def get_webshare_direct_link(url):
    """Convert Webshare URL to direct download link"""
    try:
        # Extract ident from URL
        # Supports both formats:
        # - https://webshare.cz/file/abc123/
        # - https://webshare.cz/#/file/abc123/filename
        parsed = urlparse(url)

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
            return None, f"Cannot extract file identifier from URL: {url}"
        
        # Webshare API endpoint
        api_url = f"https://webshare.cz/api/file_link/"
        
        payload = {
            'ident': ident,
            'wst': ''  # Can be empty for direct link
        }
        
        response = requests.post(
            api_url,
            data=payload,
            auth=(WEBSHARE_USER, WEBSHARE_PASS),
            timeout=10
        )

        if response.status_code == 200:
            # Webshare API returns XML, not JSON
            try:
                root = ET.fromstring(response.text)
                link = root.find('link')
                if link is not None and link.text:
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
        return None, f"Error: {str(e)}"


def add_to_pyload(direct_links, package_name='Webshare Download'):
    """Add download(s) to pyLoad API

    Args:
        direct_links: Single link (string) or list of links
        package_name: Name of the package in pyLoad
    """
    try:
        # Convert single link to list
        if isinstance(direct_links, str):
            direct_links = [direct_links]

        if not direct_links:
            return False, "No links provided"

        # pyLoad API endpoint
        api_url = f"{PYLOAD_URL}/api/addPackage"

        # Package parameters
        params = {
            'name': package_name,
            'links': direct_links
        }

        # Use HTTP Basic Auth
        response = requests.post(
            api_url,
            json=params,
            auth=(PYLOAD_USER, PYLOAD_PASS),
            timeout=10
        )

        if response.status_code == 200:
            package_id = response.text.strip().strip('"')
            count = len(direct_links)
            return True, f"Successfully added {count} file(s) to pyLoad (Package ID: {package_id})"
        elif response.status_code == 401:
            return False, f"pyLoad authentication failed - check credentials"
        else:
            return False, f"pyLoad error: {response.status_code} - {response.text[:200]}"

    except Exception as e:
        return False, f"pyLoad error: {str(e)}"


@app.route('/')
def index():
    """Web form for URL submission"""
    return render_template('index.html')


@app.route('/convert', methods=['POST'])
def convert():
    """Convert URLs and add to pyLoad (web form handler)"""
    urls_text = request.form.get('urls', '')
    urls = [url.strip() for url in urls_text.split('\n') if url.strip()]

    if not urls:
        return render_template('index.html', error="No URLs provided")

    # First, convert all URLs to direct links
    results = []
    direct_links = []

    for url in urls:
        direct_link, error = get_webshare_direct_link(url)

        if error:
            results.append({
                'url': url,
                'status': 'error',
                'message': error,
                'direct_link': None
            })
        else:
            results.append({
                'url': url,
                'status': 'converting',
                'message': 'Converted to direct link',
                'direct_link': direct_link
            })
            direct_links.append(direct_link)

    # Add all successful links to pyLoad in one package
    if direct_links:
        success, message = add_to_pyload(direct_links)

        # Update results with pyLoad status
        for result in results:
            if result['status'] == 'converting':
                result['status'] = 'success' if success else 'error'
                result['message'] = message

    return render_template('index.html', results=results)


@app.route('/api/convert', methods=['POST'])
def api_convert():
    """API endpoint to convert URL and add to pyLoad"""
    data = request.get_json()
    
    if not data or 'url' not in data:
        return jsonify({'error': 'Missing URL parameter'}), 400
    
    url = data['url'].strip()
    if not url:
        return jsonify({'error': 'Empty URL'}), 400
    
    # Convert to direct link
    direct_link, error = get_webshare_direct_link(url)
    if error:
        return jsonify({'error': error}), 400
    
    # Add to pyLoad
    success, message = add_to_pyload(direct_link)
    
    if success:
        return jsonify({
            'success': True,
            'url': url,
            'direct_link': direct_link,
            'message': message
        })
    else:
        return jsonify({
            'success': False,
            'url': url,
            'direct_link': direct_link,
            'error': message
        }), 500


@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
