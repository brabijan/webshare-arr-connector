"""Video metadata extraction service using ffprobe"""
import subprocess
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_video_metadata(file_path):
    """
    Extract detailed metadata from a video file using ffprobe

    Args:
        file_path (str): Path to video file

    Returns:
        dict: Metadata containing resolution, codecs, audio/subtitle tracks, etc.
        None if extraction fails
    """
    try:
        file_path = str(file_path)

        if not Path(file_path).exists():
            logger.warning(f"File does not exist: {file_path}")
            return None

        # Run ffprobe to get JSON output
        command = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            '-show_streams',
            file_path
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            logger.error(f"ffprobe failed for {file_path}: {result.stderr}")
            return None

        # Parse JSON output
        data = json.loads(result.stdout)

        # Extract metadata
        metadata = {
            'container': None,
            'duration': None,
            'file_size': None,
            'video': {
                'codec': None,
                'codec_name': None,
                'resolution': None,
                'width': None,
                'height': None,
                'fps': None,
                'bitrate': None
            },
            'audio_tracks': [],
            'subtitle_tracks': []
        }

        # Container format
        if 'format' in data:
            fmt = data['format']
            metadata['container'] = fmt.get('format_name', '').split(',')[0].upper()
            metadata['duration'] = float(fmt.get('duration', 0))
            metadata['file_size'] = int(fmt.get('size', 0))

        # Process streams
        for stream in data.get('streams', []):
            stream_type = stream.get('codec_type')

            if stream_type == 'video':
                # Video stream
                codec_name = stream.get('codec_name', '').upper()
                width = stream.get('width', 0)
                height = stream.get('height', 0)

                # Map codec names to common names
                codec_map = {
                    'H264': 'H.264',
                    'HEVC': 'H.265',
                    'H265': 'H.265',
                    'AV1': 'AV1',
                    'VP9': 'VP9',
                    'MPEG2VIDEO': 'MPEG-2',
                    'MPEG4': 'MPEG-4'
                }
                codec = codec_map.get(codec_name, codec_name)

                # Determine resolution label
                if height >= 2160:
                    resolution = '2160p'
                elif height >= 1080:
                    resolution = '1080p'
                elif height >= 720:
                    resolution = '720p'
                elif height >= 576:
                    resolution = '576p'
                elif height >= 480:
                    resolution = '480p'
                else:
                    resolution = f'{height}p'

                # FPS
                fps_str = stream.get('r_frame_rate', '0/1')
                try:
                    num, den = map(int, fps_str.split('/'))
                    fps = round(num / den, 2) if den != 0 else 0
                except:
                    fps = 0

                metadata['video'] = {
                    'codec': codec,
                    'codec_name': codec_name,
                    'resolution': resolution,
                    'width': width,
                    'height': height,
                    'fps': fps,
                    'bitrate': int(stream.get('bit_rate', 0))
                }

            elif stream_type == 'audio':
                # Audio stream
                codec = stream.get('codec_name', '').upper()
                channels = stream.get('channels', 0)

                # Get language tag
                tags = stream.get('tags', {})
                language = tags.get('language', 'und')

                # Normalize language codes
                lang_map = {
                    'cze': 'cs',
                    'ces': 'cs',
                    'eng': 'en',
                    'ger': 'de',
                    'deu': 'de',
                    'fre': 'fr',
                    'fra': 'fr',
                    'spa': 'es',
                    'ita': 'it',
                    'jpn': 'ja',
                    'rus': 'ru',
                    'pol': 'pl',
                    'por': 'pt'
                }
                language = lang_map.get(language.lower(), language.lower())

                # Audio codec mapping
                codec_map = {
                    'AAC': 'AAC',
                    'AC3': 'AC3',
                    'EAC3': 'E-AC3',
                    'DTS': 'DTS',
                    'TRUEHD': 'TrueHD',
                    'FLAC': 'FLAC',
                    'MP3': 'MP3',
                    'OPUS': 'Opus',
                    'VORBIS': 'Vorbis'
                }
                codec_display = codec_map.get(codec, codec)

                # Channel layout
                channel_layout = stream.get('channel_layout', '')

                metadata['audio_tracks'].append({
                    'index': stream.get('index'),
                    'language': language,
                    'codec': codec_display,
                    'channels': channels,
                    'channel_layout': channel_layout,
                    'bitrate': int(stream.get('bit_rate', 0)),
                    'title': tags.get('title', '')
                })

            elif stream_type == 'subtitle':
                # Subtitle stream
                codec = stream.get('codec_name', '').upper()

                # Get language tag
                tags = stream.get('tags', {})
                language = tags.get('language', 'und')

                # Normalize language codes (same as audio)
                lang_map = {
                    'cze': 'cs',
                    'ces': 'cs',
                    'eng': 'en',
                    'ger': 'de',
                    'deu': 'de',
                    'fre': 'fr',
                    'fra': 'fr',
                    'spa': 'es',
                    'ita': 'it',
                    'jpn': 'ja',
                    'rus': 'ru',
                    'pol': 'pl',
                    'por': 'pt'
                }
                language = lang_map.get(language.lower(), language.lower())

                # Subtitle codec mapping
                codec_map = {
                    'SUBRIP': 'SRT',
                    'ASS': 'ASS',
                    'SSA': 'SSA',
                    'WEBVTT': 'WebVTT',
                    'MOV_TEXT': 'MOV_TEXT',
                    'HDMV_PGS_SUBTITLE': 'PGS',
                    'DVD_SUBTITLE': 'VobSub',
                    'DVDSUB': 'VobSub'
                }
                codec_display = codec_map.get(codec, codec)

                metadata['subtitle_tracks'].append({
                    'index': stream.get('index'),
                    'language': language,
                    'codec': codec_display,
                    'forced': tags.get('forced', '0') == '1',
                    'title': tags.get('title', '')
                })

        logger.info(f"Successfully extracted metadata from {file_path}")
        logger.debug(f"Metadata: {metadata}")
        return metadata

    except subprocess.TimeoutExpired:
        logger.error(f"ffprobe timeout for {file_path}")
        return None
    except Exception as e:
        logger.error(f"Error extracting metadata from {file_path}: {str(e)}", exc_info=True)
        return None


def format_metadata_for_display(metadata):
    """
    Format extracted metadata for display in UI

    Args:
        metadata (dict): Raw metadata from extract_video_metadata

    Returns:
        dict: Formatted metadata for UI display
    """
    if not metadata:
        return None

    # Get unique audio languages
    audio_languages = list(set([
        track['language']
        for track in metadata.get('audio_tracks', [])
        if track['language'] != 'und'
    ]))

    # Get unique subtitle languages
    subtitle_languages = list(set([
        track['language']
        for track in metadata.get('subtitle_tracks', [])
        if track['language'] != 'und'
    ]))

    video = metadata.get('video', {})

    return {
        'resolution': video.get('resolution', 'Unknown'),
        'video_codec': video.get('codec', 'Unknown'),
        'width': video.get('width', 0),
        'height': video.get('height', 0),
        'fps': video.get('fps', 0),
        'container': metadata.get('container', 'Unknown'),
        'duration': metadata.get('duration', 0),
        'file_size': metadata.get('file_size', 0),
        'audio_languages': sorted(audio_languages),
        'subtitle_languages': sorted(subtitle_languages),
        'audio_tracks': metadata.get('audio_tracks', []),
        'subtitle_tracks': metadata.get('subtitle_tracks', [])
    }


def is_ffprobe_available():
    """
    Check if ffprobe is available on the system

    Returns:
        bool: True if ffprobe is available, False otherwise
    """
    try:
        result = subprocess.run(
            ['ffprobe', '-version'],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
