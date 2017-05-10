#
# TvplexendChannel.bundle - A Tvheadend Channel Plugin for PLEX Media Server
# Copyright (C) 2015 Patrick Gaubatz <patrick@gaubatz.at>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#


import base64

from urlparse import urlparse, urlunparse


#
# Constants
#


NAME = 'Tvheadend'
PREFIX = '/video/tvplexend'
MIN_URL_LEN = len('http://x')
CONTAINER = 'mpegts'
DURATION = 6*60*60*1000 # 6 hours seem to work...
DURATION_ADDED = 15*60 # add 15 minutes to duration


#
# Plugin Hooks
#


def Start():
    ObjectContainer.title1 = NAME


def ValidatePrefs():
    if not Prefs['url'] or len(Prefs['url']) < MIN_URL_LEN:
        Log.Error('You need to provide the URL of your Tvheadend server')
        return False

    Dict['auth'] = None
    Dict['url'] = Prefs['url']

    if Prefs['username'] and Prefs['password']:
        u = Prefs['username']
        p = Prefs['password']
        Dict['auth'] = 'Basic ' + base64.b64encode(u + ':' + p)

        url = urlparse(Prefs['url'])
        netloc = '%s:%s@%s' % (u, p, url.netloc)
        Dict['url'] = urlunparse((url.scheme, netloc, url.path, None, None, None))

    try:
        info = Tvheadend.ServerInfo()
        if not info:
            Log.Error('URL, Username, or Password are wrong')
            return False

        if info['api_version'] < 15:
            Log.Error('Tvheadend server too old')
            return False

    except TvplexendException as e:
        Log.Error(str(e))
        return False

    Log.Info('Successfully connected to Tvheadend server')


@handler(PREFIX, NAME, thumb='icon-default.png', art='art-default.png')
def MainMenu():
    try:
        oc = ObjectContainer(title2=L('livetv'))

        channels = Tvheadend.Channels()
        channels.sort(key=lambda channel: float(channel['number']))
        maxNum = max(channels, key=lambda channel: channel['number'])['number']

        Dict['channels'] = dict()
        Dict['channelNumPadding'] = len(str(maxNum))
        Dict['epg'] = Tvheadend.EPG(len(channels))

        for channel in channels:
            id = channel['uuid']
            Dict['channels'][id] = channel
            oc.add(Channel(channelId=id))

        return oc

    except TvplexendException as e:
        return ObjectContainer(header=L('error'), message=str(e))


@route(PREFIX + '/{channelId}')
def Channel(channelId, container=False, **kwargs):
    channel = Dict['channels'][channelId]
    epg = Dict['epg'][channelId] if channelId in Dict['epg'] else dict()

    title = channel['name']
    summary = ''
    tagline = None
    thumb = None
    remaining_duration = DURATION

    if Client.Platform == ClientPlatform.Android and 'title' in epg:
        title = '%s (%s)' % (title, epg['title'])

    if Prefs['displayChannelsNumbers']:
        chanNum = str(channel['number']).zfill(Dict['channelNumPadding'])
        title = '%s. %s' % (chanNum, title)

    if 'description' in epg:
        summary = epg['description']

    if 'title' in epg:
        tagline = epg['title']

    if Prefs['displayChannelIcons'] and 'icon_public_url' in channel:
        if channel['icon_public_url'].startswith('http'):
            thumb = channel['icon_public_url']
        else:
            thumb = Dict['url'] + '/' + channel['icon_public_url']

    if 'stop' in epg:
        remaining_duration = (epg['stop'] - int(Datetime.TimestampFromDatetime(Datetime.Now())) + DURATION_ADDED) * 1000

    if 'start' in epg and 'stop' in epg:
        startDateTime = Datetime.FromTimestamp(epg['start'])
        start = startDateTime.strftime('%H:%M')

        stop = Datetime.FromTimestamp(epg['stop']).strftime('%H:%M')

        duration = (epg['stop'] - epg['start']) / 60

        progress = (Datetime.Now() - startDateTime).total_seconds() / 60
        relProgress = (progress / duration) * 100

        summary = '%s - %s (%i min) ★ %i%% ★ %s ★ %s' % (
            start, stop, duration, relProgress, epg['title'], summary
        )


    vco = VideoClipObject(
        key=Callback(Channel, channelId=channelId, container=True),
        rating_key=PREFIX + '/' + channelId,
        title=title,
        summary=summary,
        tagline=tagline,
        thumb=thumb,
        duration=remaining_duration, # at least the android client needs a duration to work properly...
        items=[
            MediaObject(
                optimized_for_streaming=True,
                video_resolution = 1080,
                video_codec=VideoCodec.H264,
                audio_codec=AudioCodec.AAC,
                container=CONTAINER,
                parts=[
                    PartObject(
                        key=Callback(StreamChannel, channelId=channelId)
                    )
                ]
            )
        ]
    )

    if container:
        return ObjectContainer(objects=[vco])

    return vco


@route(PREFIX + '/{channelId}/livestream')
def StreamChannel(channelId):
    url = '%s/stream/channel/%s?profile=pass' % (Dict['url'], channelId)
    return Redirect(url)


#
# Utilities
#


class Tvheadend(object):
    @staticmethod
    def ServerInfo():
        return Tvheadend.fetch('/api/serverinfo')

    @staticmethod
    def Channels():
        channels = Tvheadend.fetch('/api/channel/grid?start=0&limit=999999')
        return channels['entries']

    @staticmethod
    def EPG(channelCount):
        entries = Tvheadend.fetch(
            '/api/epg/events/grid',
            values=dict(start=0, limit=channelCount)
        )['entries']
        epg = dict()
        for channel in entries:
            if not channel['channelUuid'] in epg:
                epg[channel['channelUuid']] = channel
        return epg

    @staticmethod
    def fetch(path, headers=dict(), values=None):
        url = Prefs['url'] + path

        if 'auth' in Dict:
            headers['Authorization'] = Dict['auth']

        try:
            return JSON.ObjectFromURL(url=url, headers=headers, values=values, encoding='utf8')

        except Ex.HTTPError as e:
            Log.Error('An HTTP error occured: ' + repr(e))
            if e.code == 401 or e.code == 403:
                raise TvplexendException(L('error_auth'))
            else:
                raise TvplexendException(L('error_net'))

        except Exception as e:
            Log.Exception('An exception occured: ' + repr(e))
            raise TvplexendException(L('error_net'))


class TvplexendException(Exception):
    pass
