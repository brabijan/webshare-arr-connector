"""File parsing and ranking using GuessIt"""
from guessit import guessit
import logging
import config

logger = logging.getLogger(__name__)


def extract_audio_languages(parsed_info):
    """
    Extract audio languages from guessit parsed info

    Args:
        parsed_info: Dict from guessit

    Returns:
        list: List of language codes (e.g., ["cs", "en"])
    """
    audio_langs = parsed_info.get('audio_language', [])

    # Handle both list and single value
    if not isinstance(audio_langs, list):
        audio_langs = [audio_langs]

    # Convert to lowercase 2-letter codes
    result = []
    for lang in audio_langs:
        lang_str = str(lang).lower()
        # Try to extract 2-letter code
        if len(lang_str) >= 2:
            result.append(lang_str[:2])

    return result


def extract_subtitle_languages(parsed_info):
    """
    Extract subtitle languages from guessit parsed info

    Args:
        parsed_info: Dict from guessit

    Returns:
        list: List of language codes (e.g., ["cs", "en", "de"])
    """
    subtitle_langs = parsed_info.get('subtitle_language', [])

    # Handle both list and single value
    if not isinstance(subtitle_langs, list):
        subtitle_langs = [subtitle_langs]

    # Convert to lowercase 2-letter codes
    result = []
    for lang in subtitle_langs:
        lang_str = str(lang).lower()
        # Try to extract 2-letter code
        if len(lang_str) >= 2:
            result.append(lang_str[:2])

    return result


def normalize_video_codec(parsed_info):
    """
    Normalize video codec names

    Args:
        parsed_info: Dict from guessit

    Returns:
        str: Normalized codec name ("HEVC", "H.265", "H.264", "x264", etc.)
    """
    video_codec = parsed_info.get('video_codec', '')
    if not video_codec:
        return ''

    codec_str = str(video_codec).upper()

    # Normalize common codec representations
    if codec_str in ['H265', 'H.265', 'HEVC', 'X265']:
        return 'HEVC'
    elif codec_str in ['H264', 'H.264', 'X264', 'AVC']:
        return 'H.264'
    elif codec_str in ['VP9']:
        return 'VP9'
    elif codec_str in ['AV1']:
        return 'AV1'

    return codec_str


def normalize_source_type(parsed_info):
    """
    Normalize source type

    Args:
        parsed_info: Dict from guessit

    Returns:
        str: Normalized source ("Blu-ray", "WEB-DL", "HDTV", etc.)
    """
    source = parsed_info.get('source', '')
    if not source:
        return ''

    source_str = str(source)

    # Normalize common source types
    source_mapping = {
        'Blu-ray': 'Blu-ray',
        'BluRay': 'Blu-ray',
        'Ultra HD Blu-ray': 'UHD Blu-ray',
        'Web': 'WEB-DL',
        'WEB': 'WEB-DL',
        'HDTV': 'HDTV',
        'DVD': 'DVD',
        'DVDRip': 'DVD',
        'SDTV': 'SDTV',
        'Satellite': 'Satellite'
    }

    return source_mapping.get(source_str, source_str)


def parse_filename(filename):
    """
    Parse filename using GuessIt with extended metadata extraction

    Args:
        filename (str): Filename to parse

    Returns:
        dict: Parsed information with additional metadata fields:
            - audio_languages: list of audio language codes
            - subtitle_languages: list of subtitle language codes
            - video_codec_normalized: normalized video codec name
            - source_type_normalized: normalized source type
    """
    try:
        parsed_info = guessit(filename)

        # Add extended metadata
        parsed_info['audio_languages'] = extract_audio_languages(parsed_info)
        parsed_info['subtitle_languages'] = extract_subtitle_languages(parsed_info)
        parsed_info['video_codec_normalized'] = normalize_video_codec(parsed_info)
        parsed_info['source_type_normalized'] = normalize_source_type(parsed_info)

        return parsed_info
    except Exception as e:
        logger.error(f"Error parsing filename '{filename}': {e}")
        return {}


def extract_quality(parsed_info):
    """
    Extract quality score from parsed info

    Args:
        parsed_info (dict): GuessIt parsed information

    Returns:
        tuple: (quality_string, quality_score)
    """
    screen_size = parsed_info.get('screen_size', '')
    quality_str = str(screen_size).replace('p', '') if screen_size else ''

    score = config.QUALITY_SCORES.get(str(screen_size), 0)

    return quality_str, score


def extract_source(parsed_info):
    """
    Extract source quality score

    Args:
        parsed_info (dict): GuessIt parsed information

    Returns:
        tuple: (source_string, source_score)
    """
    source = parsed_info.get('source', '')
    source_str = str(source)

    score = config.SOURCE_SCORES.get(source_str, 0)

    return source_str, score


def extract_codec(parsed_info):
    """
    Extract codec score

    Args:
        parsed_info (dict): GuessIt parsed information

    Returns:
        tuple: (codec_string, codec_score)
    """
    video_codec = parsed_info.get('video_codec', '')
    codec_str = str(video_codec)

    score = config.CODEC_SCORES.get(codec_str, 0)

    return codec_str, score


def extract_language(parsed_info):
    """
    Extract language information

    Args:
        parsed_info (dict): GuessIt parsed information

    Returns:
        tuple: (language_list, has_czech, language_string)
    """
    languages = parsed_info.get('language', [])

    # Ensure it's a list
    if not isinstance(languages, list):
        languages = [languages]

    # Convert to strings for checking
    language_strings = [str(lang).lower() for lang in languages]

    # Check for Czech
    has_czech = any(
        czech_variant in lang_str
        for lang_str in language_strings
        for czech_variant in ['czech', 'cs', 'cz']
    )

    # Format for display
    if languages:
        language_display = ', '.join([str(lang) for lang in languages])
    else:
        language_display = 'Unknown'

    return languages, has_czech, language_display


def rank_result(file_info, parsed_info=None, expected_title=None, expected_season=None, expected_episode=None):
    """
    Calculate ranking score for a search result

    Args:
        file_info (dict): File information from Webshare
        parsed_info (dict, optional): Pre-parsed GuessIt info
        expected_title (str, optional): Expected series/movie title
        expected_season (int, optional): Expected season number
        expected_episode (int, optional): Expected episode number

    Returns:
        dict: File info with added ranking fields
    """
    filename = file_info.get('name', '')

    # Parse if not provided
    if parsed_info is None:
        parsed_info = parse_filename(filename)

    # Extract components
    quality_str, quality_score = extract_quality(parsed_info)
    source_str, source_score = extract_source(parsed_info)
    codec_str, codec_score = extract_codec(parsed_info)
    languages, has_czech, language_display = extract_language(parsed_info)

    # Calculate total score
    total_score = quality_score + source_score + codec_score

    # CRITICAL: Check if this matches expected title/season/episode
    title_match_bonus = 0
    parsed_title = str(parsed_info.get('title', '')).lower()
    parsed_season = parsed_info.get('season')
    parsed_episode = parsed_info.get('episode')

    # For TV shows, season/episode MUST match
    if expected_season is not None and expected_episode is not None:
        if parsed_season == expected_season and parsed_episode == expected_episode:
            title_match_bonus = 200  # HUGE bonus for exact match
        else:
            # Wrong season/episode = disqualify
            total_score = -1000

    # Title matching (loose)
    if expected_title:
        expected_title_lower = expected_title.lower().replace('the ', '').replace(' ', '')
        parsed_title_clean = parsed_title.replace('the ', '').replace(' ', '')

        if expected_title_lower in parsed_title_clean or parsed_title_clean in expected_title_lower:
            title_match_bonus += 50

    total_score += title_match_bonus

    # Add language bonus
    if config.PREFER_CZECH and has_czech:
        total_score += config.CZECH_LANGUAGE_BONUS

    # Add positive votes bonus (small)
    positive_votes = file_info.get('positive_votes', 0)
    total_score += min(positive_votes, 10)  # Max 10 bonus points from votes

    # Check file size constraint
    file_size_gb = file_info.get('size', 0) / (1024 ** 3)
    size_penalty = 0
    if file_size_gb > config.MAX_SIZE_GB:
        size_penalty = -100  # Heavy penalty for oversized files

    total_score += size_penalty

    # Check minimum quality
    if config.MIN_QUALITY:
        min_quality_value = config.QUALITY_SCORES.get(config.MIN_QUALITY, 0)
        if quality_score < min_quality_value:
            total_score -= 50  # Penalty for below minimum quality

    # Build enhanced file info
    return {
        **file_info,
        'parsed': {
            'quality': quality_str or 'Unknown',
            'source': source_str or 'Unknown',
            'codec': codec_str or 'Unknown',
            'language': language_display,
            'has_czech': has_czech,
            'title': str(parsed_info.get('title', '')) if parsed_info.get('title') else '',
            'year': parsed_info.get('year'),
            'season': parsed_info.get('season'),
            'episode': parsed_info.get('episode')
        },
        'score': {
            'quality': quality_score,
            'source': source_score,
            'codec': codec_score,
            'language': config.CZECH_LANGUAGE_BONUS if has_czech else 0,
            'votes': min(positive_votes, 10),
            'size_penalty': size_penalty,
            'total': total_score
        },
        'file_size_gb': round(file_size_gb, 2)
    }


def rank_results(results, min_results=5, expected_title=None, expected_season=None, expected_episode=None):
    """
    Rank multiple search results

    Args:
        results (list): List of file info dictionaries
        min_results (int): Minimum number of results to return
        expected_title (str, optional): Expected title for matching
        expected_season (int, optional): Expected season for matching
        expected_episode (int, optional): Expected episode for matching

    Returns:
        list: Ranked and enriched results
    """
    if not results:
        return []

    logger.info(f"Ranking {len(results)} results")

    # Parse and rank each result
    ranked = []
    for result in results:
        try:
            ranked_result = rank_result(
                result,
                expected_title=expected_title,
                expected_season=expected_season,
                expected_episode=expected_episode
            )
            ranked.append(ranked_result)
        except Exception as e:
            logger.error(f"Error ranking result: {e}")
            continue

    # Filter out disqualified results (score < 0)
    ranked = [r for r in ranked if r['score']['total'] >= 0]

    # Sort by total score (descending)
    ranked.sort(key=lambda x: x['score']['total'], reverse=True)

    # Log top results
    logger.info(f"Top {min(min_results, len(ranked))} results:")
    for i, result in enumerate(ranked[:min_results]):
        logger.info(
            f"  {i+1}. {result['name'][:80]} - "
            f"Score: {result['score']['total']} "
            f"(Q:{result['parsed']['quality']} "
            f"Lang:{result['parsed']['language']} "
            f"CZ:{result['parsed']['has_czech']})"
        )

    return ranked


def get_best_result(results):
    """
    Get the single best result from ranked results

    Args:
        results (list): List of file info dictionaries

    Returns:
        dict or None: Best result or None
    """
    ranked = rank_results(results, min_results=1)

    if not ranked:
        return None

    best = ranked[0]

    logger.info(
        f"Best result: {best['name'][:80]} - "
        f"Score: {best['score']['total']}"
    )

    return best
