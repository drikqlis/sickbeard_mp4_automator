#!/usr/bin/env python
import os
import sys
import logging
import requests
import time
from extensions import valid_tagging_extensions
from readSettings import ReadSettings
from autoprocess import plex
from tvdb_mp4 import Tvdb_mp4
from mkvtomp4 import MkvtoMp4
from post_processor import PostProcessor
from logging.config import fileConfig

logpath = '/var/log/sickbeard_mp4_automator'

if os.environ.get('sonarr_eventtype') == "Test":
    sys.exit(0)

if os.name == 'nt':
    logpath = os.path.dirname(sys.argv[0])
elif not os.path.isdir(logpath):
    try:
        os.mkdir(logpath)
    except:
        logpath = os.path.dirname(sys.argv[0])
configPath = os.path.abspath(os.path.join(os.path.dirname(sys.argv[0]), 'logging.ini')).replace("\\", "\\\\")
logPath = os.path.abspath(os.path.join(logpath, 'index.log')).replace("\\", "\\\\")
fileConfig(configPath, defaults={'logfilename': logPath})
log = logging.getLogger("SonarrPre")

log.info("Sonarr extra script pre processing started.")

settings = ReadSettings(os.path.dirname(sys.argv[0]), "autoProcessPost.ini")


tvdb_id = int(os.environ.get('sonarr_series_tvdbid'))
season = int(os.environ.get('sonarr_release_seasonnumber'))

try:
    episodes = [int(os.environ.get('sonarr_release_episodenumbers'))]
except:
    episode_list = os.environ.get('sonarr_release_episodenumbers').split(",")
    episodes = [int(i) for i in episode_list]

converter = MkvtoMp4(settings)

log.debug("TVDB ID: %s." % tvdb_id)

# Update Sonarr to remove monitored status
try:
    host = settings.Sonarr['host']
    port = settings.Sonarr['port']
    webroot = settings.Sonarr['web_root']
    apikey = settings.Sonarr['apikey']
    if apikey != '':
        try:
            ssl = int(settings.Sonarr['ssl'])
        except:
            ssl = 0
        if ssl:
            protocol = "https://"
        else:
            protocol = "http://"

        seriesID = os.environ.get('sonarr_series_id')
        log.debug("Sonarr host: %s." % host)
        log.debug("Sonarr port: %s." % port)
        log.debug("Sonarr webroot: %s." % webroot)
        log.debug("Sonarr apikey: %s." % apikey)
        log.debug("Sonarr protocol: %s." % protocol)
        log.debug("Sonarr sonarr_series_id: %s." % seriesID)
        headers = {'X-Api-Key': apikey}

        # First trigger rescan
        payload = {'name': 'RescanSeries', 'seriesId': seriesID}
        url = protocol + host + ":" + port + webroot + "/api/command"
        r = requests.post(url, json=payload, headers=headers)
        rstate = r.json()
        try:
            rstate = rstate[0]
        except:
            pass
        log.info("Sonarr response: ID %d %s." % (rstate['id'], rstate['state']))
        log.info(str(rstate)) # debug

        # Then wait for it to finish
        url = protocol + host + ":" + port + webroot + "/api/command/" + str(rstate['id'])
        log.info("Requesting episode information from Sonarr for series ID %s." % seriesID)
        r = requests.get(url, headers=headers)
        command = r.json()
        attempts = 0
        while command['state'].lower() not in ['complete', 'completed']  and attempts < 6:
            log.info(str(command['state']))
            time.sleep(10)
            r = requests.get(url, headers=headers)
            command = r.json()
            attempts += 1
        log.info("Command completed")
        log.info(str(command))
        for episode in episodes:
            # Then get episode information
            url = protocol + host + ":" + port + webroot + "/api/episode?seriesId=" + seriesID
            log.info("Requesting updated episode information from Sonarr for series ID %s." % seriesID)
            r = requests.get(url, headers=headers)
            payload = r.json()
            sonarrepinfo = None
            for ep in payload:
                if int(ep['episodeNumber']) == episode and int(ep['seasonNumber']) == season:
                    sonarrepinfo = ep
                    break
            sonarrepinfo['monitored'] = False

            # Then set that episode to monitored
            log.info("Sending PUT request with following payload:") # debug
            log.info(str(sonarrepinfo)) # debug

            url = protocol + host + ":" + port + webroot + "/api/episode/" + str(sonarrepinfo['id'])
            r = requests.put(url, json=sonarrepinfo, headers=headers)
            success = r.json()

            log.info("PUT request returned:") # debug
            log.info(str(success)) # debug
            log.info("Sonarr monitoring information updated for episode %s." % success['title'])
    else:
        log.error("Your Sonarr API Key can not be blank. Update autoProcess.ini.")
except:
    log.exception("Sonarr monitor status update failed.")

sys.exit(0)
