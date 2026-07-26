# -*- coding: utf-8 -*-
import gettext

_ = gettext.gettext

import json
import os
import logging
from typing import Optional

from env_secrets import get_env_secret

import urllib.request
import urllib.error
import urllib.parse
import base64
import re

WELCOME_MSG = _("")
HELP_MSG = _("Welcome to {}. You can play, stop, resume listening.  How can I help you ?")
UNHANDLED_MSG = _("Sorry, I could not understand what you've just said.")
CANNOT_SKIP_MSG = _("This is radio, you have to wait for previous or next track to play.")
RESUME_MSG = _("Resuming {}")
NOT_POSSIBLE_MSG = _("This is radio, you can not do that.  You can ask me to stop or pause to stop listening.")
STOP_MSG = _("")
DEVICE_NOT_SUPPORTED = _("Sorry, this skill is not supported on this device")

TEST = _("test english")
TEST_PARAMS = _("test with parameters {} and {}")


# en = {
#     "url": 'https://streams.80s80s.de/web/mp3-192/streams.80s80s.de',
#     "audioSources": 'https://streams.80s80s.de/web/mp3-192/streams.80s80s.de',
#     "backgroundImageSource": "https://d2o906d8ln7ui1.cloudfront.net/images/response_builder/background-rose.png",
#     "coverImageSource": "https://d2o906d8ln7ui1.cloudfront.net/images/response_builder/card-rose.jpeg",
#     "headerAttributionImage": "",
#     "headerTitle": "title", # Music Assistant
#     "headerSubtitle": "subtitle", # Media Type
#     "primaryText": "prime", # Song Title
#     "secondaryText": "second", # Artist Name + Album Name
#     "sliderType": "determinate"
# }

info = {
            "audioSources": "",
            "backgroundImageSource": "",
            "coverImageSource": "",
            "headerAttributionImage": "",
            "headerTitle": "",
            "headerSubtitle": "",
            "primaryText": "",
            "secondaryText": ""
}

# Track the last version we've seen to avoid unnecessary updates
_last_version = None


def _mapped_audio(payload: dict) -> dict:
    """Map bridge command data to the fields used by the skill."""
    stream_url = payload.get('streamUrl') or ''
    title = payload.get('title', '') or ''
    artist = payload.get('artist', '') or ''
    album = payload.get('album', '') or ''
    image = payload.get('imageUrl') or ''

    secondary = ''
    if artist and album:
        secondary = f"{artist} - {album}"
    elif artist:
        secondary = artist
    elif album:
        secondary = album

    if stream_url and isinstance(stream_url, str):
        try:
            stream_url = re.sub(r'(?i)\.flac(?=$|\?)', '.mp3', stream_url)
        except Exception:
            logging.exception('Failed rewriting stream URL extension for %s', stream_url)

    return {
        'audioSources': stream_url,
        'backgroundImageSource': image,
        'coverImageSource': image,
        'headerAttributionImage': '',
        'headerTitle': '',
        'headerSubtitle': '',
        'primaryText': title,
        'secondaryText': secondary,
        'commandId': payload.get('commandId'),
        'playerId': payload.get('playerId'),
        'targetDeviceSerial': payload.get('targetDeviceSerial'),
        'targetDeviceFamily': payload.get('targetDeviceFamily'),
        'targetDeviceName': payload.get('targetDeviceName'),
        'version': payload.get('version'),
    }


def _fetch_payload(
        api_hostname: Optional[str],
        path: str,
        scheme: str,
        timeout: int,
        username: Optional[str],
        password: Optional[str],
        query: Optional[dict] = None,
) -> dict | None:
    """Fetch one JSON object from the local bridge API."""
    port = os.environ.get('PORT')
    api_hostname = f'127.0.0.1:{port}'

    request_path = path if path.startswith('/') else '/' + path
    if query:
        request_path = f"{request_path}?{urllib.parse.urlencode(query)}"
    url = f"{scheme}://{api_hostname.rstrip('/')}{request_path}"
    headers = {}

    env_user = get_env_secret('APP_USERNAME')
    env_pass = get_env_secret('APP_PASSWORD')
    if not username and env_user:
        username = env_user
    if not password and env_pass:
        password = env_pass
    if username and password:
        credentials = base64.b64encode(
            f"{username}:{password}".encode('utf-8')
        ).decode('ascii')
        headers['Authorization'] = f"Basic {credentials}"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = (
                getattr(resp, 'status', None)
                or getattr(resp, 'getcode', lambda: None)()
            )
            if code and int(code) != 200:
                logging.warning('Request to %s returned status %s', url, code)
                return None
            payload = json.loads(resp.read().decode('utf-8'))
            if not isinstance(payload, dict):
                logging.warning('Unexpected payload shape from %s', url)
                return None
            return payload
    except urllib.error.HTTPError as error:
        if error.code != 404:
            logging.warning('Request to %s returned status %s', url, error.code)
    except urllib.error.URLError as error:
        logging.warning('Could not reach %s: %s', url, error)
    except Exception:
        logging.exception('Error while loading data from %s', url)
    return None

def get_latest(api_hostname: Optional[str] = None,
               path: str = '/ma/latest-url',
               scheme: str = 'http',
               timeout: int = 5,
               username: Optional[str] = None,
               password: Optional[str] = None,
               alexa_device_id: Optional[str] = None) -> dict:
    """Fetch latest stream info from music-assistant API and map to APL fields.

    Expected JSON shape: {"streamUrl":..., "title":..., "artist":..., "album":..., "imageUrl":..., "version":..., "timestamp":...}

    Returns a dict with 'changed': bool indicating if the data actually changed.
    """
    global info, _last_version

    query = {}
    if alexa_device_id:
        query['alexaDeviceId'] = alexa_device_id
    payload = _fetch_payload(
        api_hostname,
        path,
        scheme,
        timeout,
        username,
        password,
        query=query,
    )
    if payload is None:
        return {'changed': False}

    current_version = payload.get('version')
    if current_version is not None and current_version == _last_version:
        logging.debug(
            "Data version %s unchanged, skipping update",
            current_version,
        )
        return {'changed': False}

    info.update(_mapped_audio(payload))
    if current_version is not None:
        _last_version = current_version
    return {'changed': True}


def claim_latest(
    alexa_device_id: Optional[str] = None,
    api_hostname: Optional[str] = None,
    scheme: str = 'http',
    timeout: int = 5,
    username: Optional[str] = None,
    password: Optional[str] = None,
) -> dict:
    """Claim and return one pending Music Assistant playback command."""
    query = {}
    if alexa_device_id:
        query['alexaDeviceId'] = alexa_device_id
    payload = _fetch_payload(
        api_hostname,
        '/ma/claim-url',
        scheme,
        timeout,
        username,
        password,
        query=query,
    )
    if payload is None:
        return {}
    mapped = _mapped_audio(payload)
    info.update(mapped)
    return mapped
