#!/usr/bin/env python

import os
import re
import sys
import shutil
# Drik added 1 start
import hashlib
import struct
from joblib import Parallel, delayed
# Drik added 1 end
from autoprocess import autoProcessTV, autoProcessMovie, autoProcessTVSR, sonarr, radarr
from readSettings import ReadSettings
from mkvtomp4 import MkvtoMp4
import logging
from logging.config import fileConfig

logpath = '/var/log/sickbeard_mp4_automator'
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
log = logging.getLogger("qBittorrentPostProcess")

log.info("qBittorrent post processing started.")

if len(sys.argv) != 7:
    log.error("Not enough command line parameters present, are you launching this from qBittorrent?")
    log.error("#Args: %L %T %R %F %N %I Category, Tracker, RootPath, ContentPath , TorrentName, InfoHash")
    log.error("Length was %s" % str(len(sys.argv)))
    log.error(str(sys.argv[1:]))
    sys.exit()

settings = ReadSettings(os.path.dirname(sys.argv[0]), "autoProcess.ini")
label = sys.argv[1].lower()
root_path = str(sys.argv[3])
content_path = str(sys.argv[4])
name = sys.argv[5]
torrent_hash = sys.argv[6]
categories = [settings.qBittorrent['cp'], settings.qBittorrent['sb'], settings.qBittorrent['sonarr'], settings.qBittorrent['radarr'], settings.qBittorrent['sr'], settings.qBittorrent['bypass']]

log.debug("Root Path: %s." % root_path)
log.debug("Content Path: %s." % content_path)
log.debug("Label: %s." % label)
log.debug("Categories: %s." % categories)
log.debug("Torrent hash: %s." % torrent_hash)
log.debug("Torrent name: %s." % name)

# Drik modified 1 start
if os.path.isfile(content_path):
    single_file = True
else:
    single_file = False
# Drik modified 1 start

if label not in categories:
    log.error("No valid label detected.")
    sys.exit()

if len(categories) != len(set(categories)):
    log.error("Duplicate category detected. Category names must be unique.")
    sys.exit()

import time


# Import python-qbittorrent
try:
    from qbittorrent import Client
except ImportError:
    log.exception("Python module PYTHON-QBITTORRENT is required. Install with 'pip install python-qbittorrent' then try again.")
    sys.exit()    

delete_dir = False

qb = Client(settings.qBittorrent['host'])
qb.login(settings.qBittorrent['username'], settings.qBittorrent['password'])

try:
    if settings.qBittorrent['actionBefore']:
        if settings.qBittorrent['actionBefore'] == 'pause':  # currently only support pausing
            log.debug("Sending action %s to qBittorrent" % settings.qBittorrent['actionBefore'])
            torrent_prop = qb.info(hashes=torrent_hash)
            timeout = 600
            period = 30
            mustend = time.time() + timeout
            while time.time() < mustend:
                if torrent_prop[0].state not in ['checkingUP','missingFiles','error','allocating','downloading','metaDL','pausedDL','queuedDL','stalledDL','checkingDL','forceDL','checkingResumeData','moving','unknown']: break
                log.info("File is still processed. Waiting.")
                time.sleep(period)
            qb.pause(torrent_hash)
                
except:
    log.exception("Failed to send qBittorrent before action.")

if settings.qBittorrent['convert']:
    # Check for custom qBittorrent output_dir
    if settings.qBittorrent['output_dir']:
        settings.output_dir = settings.qBittorrent['output_dir']
        log.debug("Overriding output_dir to %s." % settings.qBittorrent['output_dir'])
        # Drik added 2 start
		# Setting output folder to separate sub folder
        if single_file:
            settings.output_dir = os.path.splitext(root_path.replace("/mnt/media/Pobrane","/mnt/media/Konwersja"))
            settings.output_dir = settings.output_dir[0]
        else:
            settings.output_dir = root_path.replace("/mnt/media/Pobrane","/mnt/media/Konwersja")
        log.info("Moving output_dir to separate folder %s." % settings.output_dir)
        download_folder = settings.output_dir
        if not os.path.exists(settings.output_dir):
            os.mkdir(settings.output_dir)
        # Drik added 2 stop

    # Perform conversion.
    log.info("Performing conversion")
    settings.delete = False
    if not settings.output_dir:
        # If the user hasn't set an output directory, go up one from the root path and create a directory there as [name]-convert
        suffix = "convert"
        settings.output_dir = os.path.abspath(os.path.join(root_path, '..', ("%s-%s" % (name, suffix))))
        if not os.path.exists(settings.output_dir):
            os.mkdir(settings.output_dir)

    converter = MkvtoMp4(settings)
    # Drik added 3 start
	# Function for generating napiprojekt hash and saving it to filename.napihash file
    def hash_napiprojekt(video_path, single_file):
        readsize = 1024 * 1024 * 10
        with open(video_path, 'rb') as f:
            data = f.read(readsize)
        hash = hashlib.md5(data).hexdigest()
        filename=os.path.splitext(os.path.basename(video_path))[0]
        dirpath=os.path.dirname(video_path)
        if single_file:
            converspath = os.path.abspath(os.path.join(dirpath.replace("/mnt/media/Pobrane","/mnt/media/Konwersja"), filename))
        else:
            converspath = dirpath.replace("/mnt/media/Pobrane","/mnt/media/Konwersja")
        if not os.path.exists(converspath):
            os.makedirs(converspath)
        filepath2 = os.path.abspath(os.path.join(converspath, filename + '.napihash'))
        file = open(filepath2, "w")
        file.write(hash)
        file.close()
        log.info("Saved .napihash file in %s." % filepath2)
        return hash
	# Function for generating opensubtitles hash and saving to filename.openhash file
    def hash_opensubtitles(video_path, single_file):
        bytesize = struct.calcsize(b'<q')
        with open(video_path, 'rb') as f:
            filesize = os.path.getsize(video_path)
            filehash = filesize
            if filesize < 65536 * 2:
                return
            for _ in range(65536 // bytesize):
                filebuffer = f.read(bytesize)
                (l_value,) = struct.unpack(b'<q', filebuffer)
                filehash += l_value
                filehash &= 0xFFFFFFFFFFFFFFFF  # to remain as 64bit number
            f.seek(max(0, filesize - 65536), 0)
            for _ in range(65536 // bytesize):
                filebuffer = f.read(bytesize)
                (l_value,) = struct.unpack(b'<q', filebuffer)
                filehash += l_value
                filehash &= 0xFFFFFFFFFFFFFFFF
        returnedhash = '%016x' % filehash
        filename=os.path.splitext(os.path.basename(video_path))[0]
        dirpath=os.path.dirname(video_path)
        if single_file:
            converspath = os.path.abspath(os.path.join(dirpath.replace("/mnt/media/Pobrane","/mnt/media/Konwersja"), filename))
        else:
            converspath = dirpath.replace("/mnt/media/Pobrane","/mnt/media/Konwersja")
        if not os.path.exists(converspath):
            os.makedirs(converspath)
        filepath2 = os.path.abspath(os.path.join(converspath, filename + '.openhash'))
        file = open(filepath2, "w")
        file.write(returnedhash + ";" + str(filesize))
        file.close()
        log.info("Saved .openhash file in w %s." % filepath2)
        return returnedhash
    def get_logger ():
        logging.root.handlers = []
        logging.basicConfig(format='%(asctime)s - %(levelname)s: %(message)s', level=logging.DEBUG, handlers=[logging.FileHandler("/var/log/sickbeard_mp4_automator/index.log", encoding="utf-8"),logging.StreamHandler()])
        log = logging.getLogger()
        return log
    def par_conv (files):
        log = get_logger()
        inputfile = os.path.join(r, files)
        par_settings = settings
        par_converter = converter
        single_file = 0
        # Drik added 5 start
        try:
            if inputfile.endswith(".mp4") or inputfile.endswith(".mkv") or inputfile.endswith(".avi"):
                hash_napi_str = hash_napiprojekt(inputfile, single_file)
        except:
            log.warning(u"Couldn't compute napiprojekt hash for %s", inputfile)
        try:
            if inputfile.endswith(".mp4") or inputfile.endswith(".mkv") or inputfile.endswith(".avi"):
                hash_open_str = hash_opensubtitles(inputfile, single_file)
        except:
            log.warning(u"Couldn't compute opensubtitles hash for %s", inputfile)
        # Drik added 5 stop
        if MkvtoMp4(par_settings).validSource(inputfile) and inputfile not in ignore:
            log.info("Processing file %s." % inputfile)
            try:
                par_settings.output_dir = os.path.dirname(os.path.abspath(inputfile))
                par_settings.output_dir = par_settings.output_dir.replace("/mnt/media/Pobrane","/mnt/media/Konwersja")
                if not os.path.exists(par_settings.output_dir):
                    os.makedirs(par_settings.output_dir)
                par_converter = MkvtoMp4(par_settings)
                output = par_converter.process(inputfile, reportProgress=True)
                # QTFS
                #if settings.relocate_moov:
                #    converter.QTFS(output['output'])
                if output is not False:
                    ignore.append(output['output'])
                else:
                    log.error("Converting file failed %s." % inputfile)
            except:
                log.exception("Error converting file %s." % inputfile)
        else:
            log.debug("Ignoring file %s." % inputfile)
        return None
    # Drik added 3 stop

    if single_file:
        # single file
        inputfile = content_path
        # Drik added 4 start
		# Generate hash files
        try:
            hash_napi_str = hash_napiprojekt(inputfile, single_file)
        except:
            log.warning(u"Couldn't compute napiprojekt hash for %s", inputfile)		
        try:
            hash_open_str = hash_opensubtitles(inputfile, single_file)
        except:
            log.warning(u"Couldn't compute opensubtitles hash for %s", inputfile)	
        # Drik added 4 stop
        if MkvtoMp4(settings).validSource(inputfile):
            log.info("Processing file %s." % inputfile)
            try:
                converter = MkvtoMp4(settings)
                output = converter.process(inputfile, reportProgress=True)
            except:
                log.exception("Error converting file %s." % inputfile)
        else:
            log.debug("Ignoring file %s." % inputfile)
    else:
        log.debug("Processing multiple files.")
        ignore = []
        for r, d, f in os.walk(root_path):
            Parallel(n_jobs=1)(delayed (par_conv)(files) for files in f)

    # Drik mod
    convert_folder = download_folder.replace("/mnt/media/Pobrane","/mnt/media/Konwersja")
    settings.output_dir = convert_folder
    converter = MkvtoMp4(settings)
    path = convert_folder
    # Drik mod
else:
    suffix = "copy"
    # name = name[:260-len(suffix)]
    if single_file:
        log.info("Single File Torrent")
        newpath = os.path.join(path, ("%s-%s" % (name, suffix)))
    else:
        log.info("Multi File Torrent")
        newpath = os.path.abspath(os.path.join(root_path, '..', ("%s-%s" % (name, suffix))))

    if not os.path.exists(newpath):
        os.mkdir(newpath)
        log.debug("Creating temporary directory %s" % newpath)

    if single_file:
        inputfile = content_path
        shutil.copy(inputfile, newpath)
        log.debug("Copying %s to %s" % (inputfile, newpath))
    else:
        for r, d, f in os.walk(root_path):
            for files in f:
                inputfile = os.path.join(r, files)
                shutil.copy(inputfile, newpath)
                log.debug("Copying %s to %s" % (inputfile, newpath))
    path = newpath
    delete_dir = newpath

if label == categories[0]:
    log.info("Passing %s directory to Couch Potato." % path)
    autoProcessMovie.process(path, settings)
elif label == categories[1]:
    log.info("Passing %s directory to Sickbeard." % path)
    autoProcessTV.processEpisode(path, settings)
elif label == categories[2]:
    log.info("Passing %s directory to Sonarr." % path)
    sonarr.processEpisode(path, settings, torrent_hash)
elif label == categories[3]:
    log.info("Passing %s directory to Radarr." % path)
    radarr.processMovie(path, settings, torrent_hash)
elif label == categories[4]:
    log.info("Passing %s directory to Sickrage." % path)
    autoProcessTVSR.processEpisode(path, settings)
elif label == categories[5]:
    log.info("Bypassing any further processing as per category.")

# Drik mod
# Run a qbittorrent action after conversion.
try:
    if settings.qBittorrent['actionAfter']:
        # currently only support resuming or deleting torrent
        if settings.qBittorrent['actionAfter'] == 'resume':
            log.debug("Sending action %s to qBittorrent" % settings.qBittorrent['actionAfter'])
            qb.resume(torrent_hash)
        elif settings.qBittorrent['actionAfter'] == 'delete':
            # this will delete the torrent from qBittorrent but it WILL NOT delete the data
            log.debug("Sending action %s to qBittorrent" % settings.qBittorrent['actionAfter'])
            qb.delete(torrent_hash)
        elif settings.qBittorrent['actionAfter'] == 'deletedata':
            # this will delete the torrent from qBittorrent and delete data
            log.debug("Sending action %s to qBittorrent" % settings.qBittorrent['actionAfter'])
            qb.delete_permanently(torrent_hash)
except:
    log.exception("Failed to send qBittorrent after action.")
# Drik mod

if delete_dir:
    if os.path.exists(delete_dir):
        try:
            os.rmdir(delete_dir)
            log.debug("Successfully removed tempoary directory %s." % delete_dir)
        except:
            log.exception("Unable to delete temporary directory")

sys.exit()
