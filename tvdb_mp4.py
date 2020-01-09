import os
import sys
import requests
try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO
import tempfile
import time
import logging
import tmdbsimple as tmdb 
from mutagen.mp4 import MP4, MP4Cover
from extensions import valid_output_extensions, valid_poster_extensions, tmdb_api_key


def urlretrieve(url, fn):
    with open(fn, 'wb') as f:
        f.write(requests.get(url, allow_redirects=True, timeout=30).content)
    return (fn, f)


class Tvdb_mp4:
    def __init__(self, show, season, episode, original=None, language='en', logger=None, tmdbid=False):

        tmdb.API_KEY = tmdb_api_key

        if logger:
            self.log = logger
        else:
            self.log = logging.getLogger(__name__)

        if not tmdbid:
            self.log.info("ID supplied is not a TMDB ID, attempting to convert")
            find = tmdb.Find(show)
            response = find.info(external_source='tvdb_id')
            try:
                new = find.tv_results[0]['id']
                self.log.info("Replacing TVDB ID %s with TMDB ID %s" % (show, new))
                show = find.tv_results[0]['id']
            except:
                self.log.exception("Unable to convert TVDB to TMDB")

        for i in range(3):
            try:
                seriesquery = tmdb.TV(show)
                seasonquery = tmdb.TV_Seasons(show, season)
                episodequery = tmdb.TV_Episodes(show, season, episode)
                self.show = show
                self.showid = show
                self.season = season
                self.episode = episode
                self.rating = None
                self.HD = None
                self.original = original

                # Gather information from theTVDB
                self.showdata = seriesquery.info()
                self.seasondata = seasonquery.info()
                self.episodedata = episodequery.info()
                self.credit = episodequery.credits()

                self.show = self.showdata['name']
                self.genre = self.showdata['genres']
                self.network = self.showdata['networks']
                # self.contentrating = self.showdata['rating']

                self.title = self.episodedata['name']
                self.description = self.episodedata['overview']
                self.airdate = self.episodedata['air_date']

                # Generate XML tags for Actors/Writers/Directors
                self.xml = self.xmlTags()
                break
            except Exception as e:
                self.log.exception("Failed to connect to TVDB, trying again in 20 seconds.")
                time.sleep(20)

    def writeTags(self, mp4Path, artwork=True, thumbnail=False):
        self.log.info("Tagging file: %s." % mp4Path)
        ext = os.path.splitext(mp4Path)[1][1:]
        if ext not in valid_output_extensions:
            self.log.error("File is not the correct format.")
            sys.exit()

        video = MP4(mp4Path)
        try:
            video.delete()
        except IOError:
            self.log.debug("Unable to clear original tags, attempting to proceed.")

        video["tvsh"] = self.show  # TV show title
        video["\xa9nam"] = self.title  # Video title
        video["tven"] = self.title  # Episode title
        video["desc"] = self.shortDescription()  # Short description
        video["ldes"] = self.description  # Long description (same a short for tv)
        network = [x['name'] for x in self.network]
        video["tvnn"] = network  # Network
        if self.airdate != "0000-00-00":
            video["\xa9day"] = self.airdate  # Airdate
        video["tvsn"] = [self.season]  # Season number
        video["disk"] = [(int(self.season), 0)]  # Season number as disk
        video["\xa9alb"] = self.show + ", Season " + str(self.season)  # iTunes Album as Season
        video["tves"] = [self.episode]  # Episode number
        video["trkn"] = [(int(self.episode), len(self.seasondata))]  # Episode number iTunes
        video["stik"] = [10]  # TV show iTunes category
        if self.HD is not None:
            video["hdvd"] = self.HD
        if self.genre is not None:
            genre = None
            for g in self.genre:
                if genre is None:
                    genre = g['name']
                    break
            video["\xa9gen"] = genre
            # video["\xa9gen"] = self.genre.replace('|', ',')[1:-1]  # Genre(s)
        video["----:com.apple.iTunes:iTunMOVI"] = self.xml  # XML - see xmlTags method
        # video["----:com.apple.iTunes:iTunEXTC"] = self.setRating()  # iTunes content rating

        if artwork:
            path = self.getArtwork(mp4Path, thumbnail=thumbnail)
            if path is not None:
                cover = open(path, 'rb').read()
                if path.endswith('png'):
                    video["covr"] = [MP4Cover(cover, MP4Cover.FORMAT_PNG)]  # png poster
                else:
                    video["covr"] = [MP4Cover(cover, MP4Cover.FORMAT_JPEG)]  # jpeg poster
        if self.original:
            video["\xa9too"] = "MDH:" + os.path.basename(self.original)
        else:
            video["\xa9too"] = "MDH:" + os.path.basename(mp4Path)
        MP4(mp4Path).delete(mp4Path)
        for i in range(3):
            try:
                self.log.info("Trying to write tags.")
                video.save()
                self.log.info("Tags written successfully.")
                break
            except IOError as e:
                self.log.exception("There was a problem writing the tags. Retrying.")
                time.sleep(5)

    def setHD(self, width, height):
        if width >= 1900 or height >= 1060:
            self.HD = [2]
        elif width >= 1260 or height >= 700:
            self.HD = [1]
        else:
            self.HD = [0]

    def shortDescription(self, length=255, splitter='.', suffix='.'):
        if self.description is None:
            self.description = ''
        if len(self.description) <= length:
            return self.description
        else:
            return ' '.join(self.description[:length + 1].split('.')[0:-1]) + suffix

    def setRating(self):
        if self.contentrating is None:
            return 'us-tv|Not Rated|000'
        ratings = dict([
            ("TV-Y", 'us-tv|TV-Y|100'),
            ("TV-Y7", 'us-tv|TV-Y7|200'),
            ("TV-G", 'us-tv|TV-G|300'),
            ("TV-PG", 'us-tv|TV-PG|400'),
            ("TV-14", 'us-tv|TV-14|500'),
            ("TV-MA", 'us-tv|TV-MA|600'),
            ("Not Rated", 'mpaa|Not Rated|000'),
            ("G", 'mpaa|G|100'),
            ("PG", 'mpaa|PG|200'),
            ("PG-13", 'mpaa|PG-13|300'),
            ("R", 'mpaa|R|400'),
            ("NC-17", 'mpaa|NC-17|500')])

        return str(ratings[self.contentrating])

    def xmlTags(self):
        # constants
        header = "<?xml version=\"1.0\" encoding=\"UTF-8\"?><!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\"><plist version=\"1.0\"><dict>\n"
        castheader = "<key>cast</key><array>\n"
        writerheader = "<key>screenwriters</key><array>\n"
        directorheader = "<key>directors</key><array>\n"
        producerheader = "<key>producers</key><array>\n"
        subfooter = "</array>\n"
        footer = "</dict></plist>\n"

        output = StringIO()
        output.write(header)

        # Write actors
        output.write(castheader)
        for a in self.credit['cast'][:5]:
            if a is not None and a['name'] is not None:
                output.write("<dict><key>name</key><string>%s</string></dict>\n" % a['name'].encode('ascii', errors='ignore'))
        output.write(subfooter)
        # Write screenwriters
        output.write(writerheader)
        for w in [x for x in self.credit['crew'] if x['department'].lower() == "writing"][:5]:
            if w is not None:
                output.write("<dict><key>name</key><string>%s</string></dict>\n" % w['name'].encode('ascii', 'ignore'))
        output.write(subfooter)
        # Write directors
        output.write(directorheader)
        for d in [x for x in self.credit['crew'] if x['department'].lower() == "directing"][:5]:
            if d is not None:
                output.write("<dict><key>name</key><string>%s</string></dict>\n" % d['name'].encode('ascii', 'ignore'))
        output.write(subfooter)
        # Write producers
        output.write(producerheader)
        for p in [x for x in self.credit['crew'] if x['department'].lower() == "production"][:5]:
            if p is not None:
                output.write("<dict><key>name</key><string>%s</string></dict>\n" % p['name'].encode('ascii', 'ignore'))
        output.write(subfooter)

        # Close XML
        output.write(footer)
        return output.getvalue()

    def getArtwork(self, mp4Path, filename='cover', thumbnail=False):
        # Check for local cover.jpg or cover.png artwork in the same directory as the mp4
        extensions = valid_poster_extensions
        poster = None
        for e in extensions:
            head, tail = os.path.split(os.path.abspath(mp4Path))
            path = os.path.join(head, filename + os.extsep + e)
            if (os.path.exists(path)):
                poster = path
                self.log.info("Local artwork detected, using %s." % path)
                break
        # Pulls down all the poster metadata for the correct season and sorts them into the Poster object
        if poster is None:
            if thumbnail:
                poster_path = self.episodedata['still_path']
            else:
                poster_path = self.seasondata['poster_path']
            if not poster_path:
                self.log.warning("No poster found")
                return None
            savepath = os.path.join(tempfile.gettempdir(), "poster-%s%s%s.jpg" % (self.showid, self.season, self.episode))
            if os.path.exists(savepath):
                try:
                    os.remove(savepath)
                except:
                    import random
                    savepath = os.path.join(tempfile.gettempdir(), "poster-%s%s%s%s.jpg" % (self.showid, self.season, self.episode, random.randint(1, 9999)))
            try:
                poster = urlretrieve("https://image.tmdb.org/t/p/original" + poster_path, savepath)[0]
            except Exception as e:
                self.log.exception("Exception while retrieving poster %s.", str(e))
                poster = None
        return poster


class Poster:
    # Simple container for all the poster parameters needed
    def __init__(self, rating=0, ratingcount=0, bannerpath=""):
        self.rating = rating
        self.bannerpath = bannerpath
        self.ratingcount = ratingcount


def main():
    if len(sys.argv) > 4:
        mp4 = str(sys.argv[1]).replace("\\", "\\\\").replace("\\\\\\\\", "\\\\")
        tvdb_id = str(sys.argv[2])
        if tvdb_id.isdigit():
            tvdb_id = int(tvdb_id)
        tvdb_season = int(sys.argv[3])
        tvdb_episode = int(sys.argv[4])
        tvdb_mp4_instance = Tvdb_mp4(show=tvdb_id, season=tvdb_season, episode=tvdb_episode)
        if os.path.splitext(mp4)[1][1:] in valid_output_extensions:
            tvdb_mp4_instance.writeTags(mp4)
        else:
            print("Wrong file type")


if __name__ == '__main__':
    main()
