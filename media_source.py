from __future__ import annotations

import logging
from typing import Tuple

from homeassistant.components.media_source.error import MediaSourceError, Unresolvable
from homeassistant.components.media_source.models import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
)
from homeassistant.core import HomeAssistant, callback

from homeassistant.components.media_player import BrowseError, BrowseMedia
from homeassistant.components.media_source.const import MEDIA_MIME_TYPES, URI_SCHEME

from homeassistant.const import (  # pylint: disable=import-error
    CONF_URL,
)
from homeassistant.components.media_player.const import (
    MEDIA_CLASS_ALBUM,
    MEDIA_CLASS_ARTIST,
    MEDIA_CLASS_CHANNEL,
    MEDIA_CLASS_DIRECTORY,
    MEDIA_CLASS_EPISODE,
    MEDIA_CLASS_MOVIE,
    MEDIA_CLASS_MUSIC,
    MEDIA_CLASS_PLAYLIST,
    MEDIA_CLASS_SEASON,
    MEDIA_CLASS_TRACK,
    MEDIA_CLASS_TV_SHOW,
    MEDIA_TYPE_ALBUM,
    MEDIA_TYPE_ARTIST,
    MEDIA_TYPE_CHANNEL,
    MEDIA_TYPE_EPISODE,
    MEDIA_TYPE_MOVIE,
    MEDIA_TYPE_PLAYLIST,
    MEDIA_TYPE_SEASON,
    MEDIA_TYPE_TRACK,
    MEDIA_TYPE_TVSHOW,
)

from . import JellyfinClientManager, JellyfinDevice, autolog

from .const import (
    DOMAIN,
    USER_APP_NAME,
)

PLAYABLE_MEDIA_TYPES = [
    MEDIA_TYPE_ALBUM,
    MEDIA_TYPE_ARTIST,
    MEDIA_TYPE_TRACK,
]

CONTAINER_TYPES_SPECIFIC_MEDIA_CLASS = {
    MEDIA_TYPE_ALBUM: MEDIA_CLASS_ALBUM,
    MEDIA_TYPE_ARTIST: MEDIA_CLASS_ARTIST,
    MEDIA_TYPE_PLAYLIST: MEDIA_CLASS_PLAYLIST,
    MEDIA_TYPE_SEASON: MEDIA_CLASS_SEASON,
    MEDIA_TYPE_TVSHOW: MEDIA_CLASS_TV_SHOW,
}

CHILD_TYPE_MEDIA_CLASS = {
    MEDIA_TYPE_SEASON: MEDIA_CLASS_SEASON,
    MEDIA_TYPE_ALBUM: MEDIA_CLASS_ALBUM,
    MEDIA_TYPE_ARTIST: MEDIA_CLASS_ARTIST,
    MEDIA_TYPE_MOVIE: MEDIA_CLASS_MOVIE,
    MEDIA_TYPE_PLAYLIST: MEDIA_CLASS_PLAYLIST,
    MEDIA_TYPE_TRACK: MEDIA_CLASS_TRACK,
    MEDIA_TYPE_TVSHOW: MEDIA_CLASS_TV_SHOW,
    MEDIA_TYPE_CHANNEL: MEDIA_CLASS_CHANNEL,
    MEDIA_TYPE_EPISODE: MEDIA_CLASS_EPISODE,
}

IDENTIFIER_SPLIT = "~~"

_LOGGER = logging.getLogger(__name__)

class UnknownMediaType(BrowseError):
    """Unknown media type."""

async def async_get_media_source(hass: HomeAssistant):
    """Set up Netatmo media source."""
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    jelly_cm: JellyfinClientManager = hass.data[DOMAIN][entry.data[CONF_URL]]["manager"]
    return JellyfinSource(hass, jelly_cm)

class JellyfinSource(MediaSource):
    """Media source for Jellyfin"""

    @staticmethod
    def parse_mediasource_identifier(identifier: str):
        prefix = f"{URI_SCHEME}{DOMAIN}/"
        text = identifier
        if identifier.startswith(prefix):
            text = identifier[len(prefix):]

        return text.split(IDENTIFIER_SPLIT, 2)

    def __init__(self, hass: HomeAssistant, manager: JellyfinClientManager):
        """Initialize Netatmo source."""
        super().__init__(DOMAIN)
        self.hass = hass
        self.jelly_cm = manager

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        """Resolve a media item to a playable item."""
        autolog("<<<")

        if not item or not item.identifier:
            return None

        media_content_type, media_content_id = self.parse_mediasource_identifier(item.identifier)

        profile = {
            "Name": USER_APP_NAME,
            "MaxStreamingBitrate": 25000 * 1000,
            "MusicStreamingTranscodingBitrate": 1920000,
            "TimelineOffsetSeconds": 5,
            "TranscodingProfiles": [
                {
                    "Type": "Audio",
                    "Container": "mp3",
                    "Protocol": "http",
                    "AudioCodec": "mp3",
                    "MaxAudioChannels": "2",
                },
                {
                    "Type": "Video",
                    "Container": "mp4",
                    "Protocol": "http",
                    "AudioCodec": "aac,mp3,opus,flac,vorbis",
                    "VideoCodec": "h264,mpeg4,mpeg2video",
                    "MaxAudioChannels": "6",
                },
                {"Container": "jpeg", "Type": "Photo"},
            ],
            "DirectPlayProfiles": [
                {
                    "Type": "Audio",
                    "Container": "mp3",
                    "AudioCodec": "mp3"
                },
                {
                    "Type": "Audio",
                    "Container": "m4a,m4b",
                    "AudioCodec": "aac"
                },
                {
                    "Type": "Video",
                    "Container": "mp4,m4v",
                    "AudioCodec": "aac,mp3,opus,flac,vorbis",
                    "VideoCodec": "h264,mpeg4,mpeg2video",
                    "MaxAudioChannels": "6",
                },
            ],
            "ResponseProfiles": [],
            "ContainerProfiles": [],
            "CodecProfiles": [],
            "SubtitleProfiles": [
                {"Format": "srt", "Method": "External"},
                {"Format": "srt", "Method": "Embed"},
                {"Format": "ass", "Method": "External"},
                {"Format": "ass", "Method": "Embed"},
                {"Format": "sub", "Method": "Embed"},
                {"Format": "sub", "Method": "External"},
                {"Format": "ssa", "Method": "Embed"},
                {"Format": "ssa", "Method": "External"},
                {"Format": "smi", "Method": "Embed"},
                {"Format": "smi", "Method": "External"},
                # Jellyfin currently refuses to serve these subtitle types as external.
                {"Format": "pgssub", "Method": "Embed"},
                # {
                #    "Format": "pgssub",
                #    "Method": "External"
                # },
                {"Format": "dvdsub", "Method": "Embed"},
                # {
                #    "Format": "dvdsub",
                #    "Method": "External"
                # },
                {"Format": "pgs", "Method": "Embed"},
                # {
                #    "Format": "pgs",
                #    "Method": "External"
                # }
            ],
        }

        playback_info = await self.jelly_cm.get_play_info(media_content_id, profile)
        _LOGGER.debug("playbackinfo: %s", str(playback_info))
        if playback_info is None or "MediaSources" not in playback_info:
            _LOGGER.error(f"No playback info for item id {media_content_id}")
            return None

        selected = None
        weight_selected = 0
        for media_source in playback_info["MediaSources"]:
            weight = (media_source.get("SupportsDirectStream") or 0) * 50000 + (
                media_source.get("Bitrate") or 0
            ) / 1000
            if weight > weight_selected:
                weight_selected = weight
                selected = media_source
        
        if selected is None:
            return None

        if selected["SupportsDirectStream"]:
            if media_content_type == MEDIA_TYPE_TRACK:
                mimetype = "audio/" + selected["Container"]
                url = self.jelly_cm.get_server_url() + "/Audio/%s/stream?static=true&MediaSourceId=%s&api_key=%s" % (
                        media_content_id,
                        selected["Id"],
                        self.jelly_cm.get_auth_token()
                    )
            else:
                mimetype = "video/" + selected["Container"]
                url = self.jelly_cm.get_server_url() + "/Videos/%s/stream?static=true&MediaSourceId=%s&api_key=%s" % (
                        media_content_id,
                        selected["Id"],
                        self.jelly_cm.get_auth_token()
                    )
        elif selected["SupportsTranscoding"]:
            url = self.jelly_cm.get_server_url() + selected.get("TranscodingUrl")
            container = selected["TranscodingContainer"] if "TranscodingContainer" in selected else selected["Container"]
            if media_content_type == MEDIA_TYPE_TRACK:
                mimetype = "audio/" + container
            else:
                mimetype = "video/" + container

        _LOGGER.debug("cast url: %s", url)
        return PlayMedia(url, mimetype)

        return None

    async def async_browse_media(
        self, item: MediaSourceItem, media_types: Tuple[str] = MEDIA_MIME_TYPES
    ) -> BrowseMediaSource:
        """Browse media."""
        autolog("<<<")

        media_contant_type, media_content_id = async_parse_identifier(item)
        return await async_library_items(self.jelly_cm, media_contant_type, media_content_id, canPlayList=False)

@callback
def async_parse_identifier(
    item: MediaSourceItem,
) -> tuple[str | None, str | None]:
        """Parse identifier."""
        if not item.identifier:
            # Empty source_dir_id and location
            return None, None

        return item.identifier, item.identifier

def Type2Mediatype(type):
    switcher = {
        "Movie": MEDIA_TYPE_MOVIE,
        "Series": MEDIA_TYPE_TVSHOW,
        "Season": MEDIA_TYPE_SEASON,
        "Episode": MEDIA_TYPE_EPISODE,
        "Music": MEDIA_TYPE_ALBUM,
        "Audio": MEDIA_TYPE_TRACK,
        "BoxSet": MEDIA_CLASS_DIRECTORY,
        "Folder": MEDIA_CLASS_DIRECTORY,
        "CollectionFolder": MEDIA_CLASS_DIRECTORY,
        "Playlist": MEDIA_CLASS_DIRECTORY,
        "MusicArtist": MEDIA_TYPE_ARTIST,
        "MusicAlbum": MEDIA_TYPE_ALBUM,
    }
    return switcher[type]

def Type2Mediaclass(type):
    switcher = {
        "Movie": MEDIA_CLASS_MOVIE,
        "Series": MEDIA_CLASS_TV_SHOW,
        "Season": MEDIA_CLASS_SEASON,
        "Episode": MEDIA_CLASS_EPISODE,
        "Music": MEDIA_CLASS_DIRECTORY,
        "BoxSet": MEDIA_CLASS_DIRECTORY,
        "Folder": MEDIA_CLASS_DIRECTORY,
        "CollectionFolder": MEDIA_CLASS_DIRECTORY,
        "Playlist": MEDIA_CLASS_DIRECTORY,
        "MusicArtist": MEDIA_CLASS_ARTIST,
        "MusicAlbum": MEDIA_CLASS_ALBUM,
        "Audio": MEDIA_CLASS_TRACK,
    }
    return switcher[type]

def IsPlayable(type, canPlayList):
    switcher = {
        "Movie": True,
        "Series": canPlayList,
        "Season": canPlayList,
        "Episode": True,
        "Music": False,
        "BoxSet": canPlayList,
        "Folder": False,
        "CollectionFolder": False,
        "Playlist": canPlayList,
        "MusicArtist": canPlayList,
        "MusicAlbum": canPlayList,
        "Audio": True,
    }
    return switcher[type]

async def async_library_items(jelly_cm: JellyfinClientManager, 
            media_content_type_in=None, 
            media_content_id_in=None,
            canPlayList=True
        ) -> BrowseMediaSource:
    """
    Create response payload to describe contents of a specific library.

    Used by async_browse_media.
    """
    _LOGGER.debug(f'>> async_library_items: {media_content_id_in}')

    library_info = None
    query = None

    if (media_content_type_in is None):
        media_content_type = None
        media_content_id = None
    else:
        media_content_type, media_content_id = JellyfinSource.parse_mediasource_identifier(media_content_id_in)
    _LOGGER.debug(f'>> {media_content_type} / {media_content_id}')

    if media_content_type in [None, "library"]:
        library_info = BrowseMediaSource(
            domain=DOMAIN,
            identifier=f'library{IDENTIFIER_SPLIT}library',
            media_class=MEDIA_CLASS_DIRECTORY,
            media_content_type="library",
            title="Media Library",
            can_play=False,
            can_expand=True,
            children=[],
        )
    elif media_content_type in [MEDIA_CLASS_DIRECTORY, MEDIA_TYPE_ARTIST, MEDIA_TYPE_ALBUM, MEDIA_TYPE_PLAYLIST, MEDIA_TYPE_TVSHOW, MEDIA_TYPE_SEASON]:
        query = {
            "ParentId": media_content_id,
            "sortBy": "SortName",
            "sortOrder": "Ascending"
        }

        parent_item = await jelly_cm.get_item(media_content_id)
        library_info = BrowseMediaSource(
            domain=DOMAIN,
            identifier=f'{media_content_type}{IDENTIFIER_SPLIT}{media_content_id}',
            media_class=media_content_type,
            media_content_type=media_content_type,
            title=parent_item["Name"],
            can_play=IsPlayable(parent_item["Type"], canPlayList),
            can_expand=True,
            thumbnail=jelly_cm.get_artwork_url(media_content_id),
            children=[],
        )
    else:
        query = {
            "Id": media_content_id
        }
        library_info = BrowseMediaSource(
            domain=DOMAIN,
            identifier=f'{media_content_type}{IDENTIFIER_SPLIT}{media_content_id}',
            media_class=MEDIA_CLASS_DIRECTORY,
            media_content_type=media_content_type,
            title="",
            can_play=True,
            can_expand=False,
            thumbnail=jelly_cm.get_artwork_url(media_content_id),
            children=[],
        )

    items = await jelly_cm.get_items(query)
    for item in items:
        if media_content_type in [None, "library", MEDIA_CLASS_DIRECTORY, MEDIA_TYPE_ARTIST, MEDIA_TYPE_ALBUM, MEDIA_TYPE_PLAYLIST, MEDIA_TYPE_TVSHOW, MEDIA_TYPE_SEASON]:
            if item["IsFolder"]:
                library_info.children.append(BrowseMediaSource(
                    domain=DOMAIN,
                    identifier=f'{Type2Mediatype(item["Type"])}{IDENTIFIER_SPLIT}{item["Id"]}',
                    media_class=Type2Mediaclass(item["Type"]),
                    media_content_type=Type2Mediatype(item["Type"]),
                    title=item["Name"],
                    can_play=IsPlayable(item["Type"], canPlayList),
                    can_expand=True,
                    children=[],
                    thumbnail=jelly_cm.get_artwork_url(item["Id"])
                ))
            else:
                library_info.children.append(BrowseMediaSource(
                    domain=DOMAIN,
                    identifier=f'{Type2Mediatype(item["Type"])}{IDENTIFIER_SPLIT}{item["Id"]}',
                    media_class=Type2Mediaclass(item["Type"]),
                    media_content_type=Type2Mediatype(item["Type"]),
                    title=item["Name"],
                    can_play=IsPlayable(item["Type"], canPlayList),
                    can_expand=False,
                    children=[],
                    thumbnail=jelly_cm.get_artwork_url(item["Id"])
                ))
        else:
            library_info.domain=DOMAIN
            library_info.identifier=f'{Type2Mediatype(item["Type"])}{IDENTIFIER_SPLIT}{item["Id"]}',
            library_info.title = item["Name"]
            library_info.media_content_type = Type2Mediatype(item["Type"])
            library_info.media_class = Type2Mediaclass(item["Type"])
            library_info.can_expand = False
            library_info.can_play=IsPlayable(item["Type"], canPlayList),
            break

    return library_info
