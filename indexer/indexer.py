#!/usr/bin/env python3
import aiohttp
import asyncio

import sqlite3
import json

import chardet

from packaging import version
from pathlib import PurePath

from typing import Union

import re
import xtarfile as tarfile # tarfile doesn't support zstd
import gzip
import os

import datetime
import time

from tqdm import tqdm

import logging
from .util import CustomFormatter, mandoc_convert, extract_headings, extract_description, resolve_so_links


arch = 'x86_64'
tmpdir = 'temp/' # trailing slash
MANDIR = 'usr/share/man'

# LOGGER
logger = logging.getLogger("Indexer")
logger.setLevel(logging.DEBUG)
#logger.propagate = False
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
ch.setFormatter(CustomFormatter())
logger.addHandler(ch)

headers = {
    "User-Agent": "Man page crawler (info@parabolas.xyz; https://man.parabolas.xyz/)"
}

class UnknownManPath(Exception):
    pass

class Indexer(object):

    def __init__(self, repo: str, db: str):
        self.INDEXER_STARTTIME = int(time.time())
        self._repo = repo
        self._con = sqlite3.connect(db) #isolation_level=None for autocommit
        self._con.row_factory = sqlite3.Row
        self._db = self._con.cursor()
        logger.info(f"Connected to db: {db}")
        self._init_db()
        # create temp dir
        if not os.path.exists(tmpdir + "pkgs"):
            os.makedirs(tmpdir + "pkgs")

    def _decode(self, text):
        CHARSETS = ["utf-8", "ascii", "iso-8859-1", "iso-8859-9", "iso-8859-15", "cp1250", "cp1252"]

        for charset in CHARSETS:
            try:
                return text.decode(charset)
            except UnicodeDecodeError:
                pass
            except LookupError:
                # ignore invalid encoding_hint
                pass

        # fall back to chardet and errors="replace"
        encoding = chardet.detect(text)["encoding"]
        return text.decode(encoding, errors="replace")


    def _init_db(self):
        self._db.execute("""CREATE TABLE IF NOT EXISTS arch_packages (
            NAME TEXT UNIQUE PRIMARY KEY,
            REPO TEXT,
            VERSION TEXT,
            FILENAME TEXT,
            ARCH TEXT,
            UPSTREAM TEXT,
            LICENSE TEXT,
            URL TEXT,
            MANPATHS TEXT
        );
        """)
        self._db.execute("""CREATE TABLE IF NOT EXISTS arch_manpages (
            PACKAGE TEXT,
            REPO TEXT,
            FILENAME TEXT UNIQUE PRIMARY KEY,
            NAME TEXT,
            SECTION TEXT,
            LOCALE TEXT,
            HEADINGS TEXT,
            DESCRIPTION TEXT,
            CONTENT TEXT,
            HTML_CONTENT TEXT,
            TXT_CONTENT TEXT,
            SO_RESOLVED INTEGER DEFAULT 0
        );
        """)
        self._db.execute("""CREATE TABLE IF NOT EXISTS arch_meta (
            ID INTEGER NOT NULL PRIMARY KEY,
            TIMESTAMP INTEGER,
            HAVEMAN_PKGS INTEGER,
            TOTAL_PKGS INTEGER
        );
        """)
        self._db.execute("""CREATE TABLE IF NOT EXISTS arch_executions (
            START_TIME INTEGER,
            EXECUTION_TIME INTEGER,
            UPDATED_PKGS INTEGER,
            UPDATED_PAGES INTEGER
        );
        """)
        self._db.execute("""CREATE TABLE IF NOT EXISTS arch_redirects (
            SOURCE_NAME TEXT,
            SOURCE_SECTION TEXT,
            SOURCE_LANG TEXT,
            TARGET_NAME TEXT,
            TARGET_SECTION TEXT,
            TARGET_LANG TEXT
        );
        """)
        self._db.execute("""SELECT * from arch_meta limit 1""")
        if self._db.fetchone() is None:
            # empty table
            self._db.execute("""INSERT INTO arch_meta (ID, TIMESTAMP)
            VALUES(1, 0);
            """)
        self._con.commit()

    async def __aenter__(self):
        self._session = aiohttp.ClientSession(raise_for_status=True, headers=headers) # make sure all requests are 200
        self._mirror = await self._get_mirror()
        return self

    async def __aexit__(self, *err):
        await self._session.close()
        self._con.close() # close sqlite3 db

    def _get_manpage(self, filename: str) -> Union[None, str]:
        """
        Fetch content of manpage from database
        """
        self._db.execute("""SELECT * FROM arch_manpages
        WHERE FILENAME = ?;""", (filename,))
        result = self._db.fetchone()
        if result is None:
            return None
        else:
            return result

    def _get_manpage_html(self, filename: str) -> Union[None, str]:
        """
        Fetch compiled html of manpage from database
        """
        self._db.execute("""SELECT HTML_CONTENT FROM arch_manpages
        WHERE FILENAME = ?;""", (filename,))
        result = self._db.fetchone()
        if result is None:
            return None
        else:
            return result['CONTENT']

    def _insert_execution(self):
        exec_time = self.INDEXER_ENDTIME - self.INDEXER_STARTTIME
        self._db.execute("""INSERT INTO arch_executions
        VALUES (?, ?, ?, ?)""", (self.INDEXER_STARTTIME, exec_time, self._updatedpkgs + self._newpkgs, self._updated_pages))
        self._con.commit()


    def _insert_manpage(self, package, filename, headings, description, content, html_content, txt_content):
        """
        Make sure to commit() after running this
        """

        prevman = self._get_manpage(filename)
        if prevman is None or content != self._get_manpage(filename)['CONTENT']:

            try:
                name, section, locale = self._getmanpathinfo(filename)
            except UnknownManPath:
                logger.warning("Skipping path with unrecognized structure: {}".format(path))

            self._db.execute("""INSERT OR REPLACE INTO arch_manpages (PACKAGE, REPO, FILENAME, NAME, SECTION, LOCALE, HEADINGS, DESCRIPTION, CONTENT, HTML_CONTENT, TXT_CONTENT)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (package, self._repo, filename, name, section, locale, headings, description, content, html_content, txt_content,))
            #self._con.commit()
            logger.info(f"Updated {filename} for package {package}")

    def _insert_redirects(self, redirects: list):
        self._db.executemany("""INSERT INTO arch_redirects
            VALUES (?, ?, ?, ?, ?, ?);
        """, redirects)
        self._con.commit()


    def _update_meta(self, key: str, value: int):
        self._db.execute(f"""UPDATE arch_meta
            SET {key} = ?
            WHERE
                ID = 1;
            """, (value,))
        self._con.commit()

    # return resp of url
    async def _fetch_file(self, url: str):
        async with self._session.get(url) as resp:
            response = await resp.text()
        return response
        
    # download `url` to `file_name`
    async def _download_file(self, url: str, file_name: str):
        with open(file_name, mode='wb') as f:
            async with self._session.get(url) as resp:
                total_length = resp.headers.get('Content-Length')
                if total_length is None: f.write(await resp.read())
                else:
                    dl = 0
                    total_length = int(total_length)
                    pbar = tqdm(total=total_length)
                    async for chunk in resp.content.iter_chunked(8*1024*1024): # 8 MiB
                        dl += len(chunk)
                        pbar.update(len(chunk))
                        f.write(chunk)
                        #print(dl / total_length)
                    pbar.close()
                logger.info(f"Downloaded {file_name}")
                return resp


    async def _get_mirror(self) -> str:
        #logger.info("Downloading Mirrorlist")
        #mirrorlist = await self._fetch_file("https://archlinux.org/mirrorlist/?country=US&protocol=http&protocol=https&ip_version=4&use_mirror_status=on")
        #mirror = re.findall(r'#Server = (http?s\:\/\/.*)', mirrorlist)[0].replace('$repo', self._repo).replace('$arch', arch)
        #logger.info(f"Selected Mirror: {mirror}")
        #return mirror
        return "https://mirrors.edge.kernel.org/archlinux/core/os/x86_64"

    def _ismanpath(self, path: str) -> bool:
        if path.startswith(MANDIR) and not path.endswith("/"):
            return True
        return False

    def _getmanpathinfo(self, path: str) -> tuple[str, str, str]:

        # Regex Method
        #regex = r"""(?x)
        #    man
        #    (?: / ([^/]+) )?   # Optional locale
        #    /man[a-z0-9]+/      # Subdir
        #    ([^/]+?)           # Man page name (non-greedy)
        #    \. ([^/\.]+)       # Section
        #    (?: \. (?: gz|lzma|bz2|xz|zst ))* $  # Any number of compression extensions
        #"""
        #match = re.findall(regex, path)[0]
        #info = {
        #    "section": match[2],
        #    "locale": None if not match[0] else match[0],
        #    "name": match[1]
        #}

        # Better
        pp = PurePath(path)
        man_name = pp.stem
        man_section = pp.suffix[1:]  # strip the dot

        if not man_section:
            raise UnknownManPath("empty section number")

        # relative_to can succeed only if path is a subdir of MANDIR
        if not path.startswith(MANDIR):
            raise UnknownManPath
        pp = pp.relative_to(MANDIR)

        if pp.parts[0].startswith("man"):
            man_lang = "en"
        elif len(pp.parts) > 1 and pp.parts[1].startswith("man"):
            man_lang = pp.parts[0]
        else:
            raise UnknownManPath

        #info = {
        #    "section": man_section,
        #    "name": man_name,
        #    "locale", man_lang
        #}
        return man_name, man_section, man_lang

    def _read_files(self, file: str) -> list: # read "files"
        with open(file, "r") as f:
            lines = f.readlines()

        manpaths = []

        for line in lines:
            line = line.rstrip()
            if self._ismanpath(line):
                manpaths.append(line)

        return manpaths

    def _read_desc(self, file: str) -> dict:
        with open(file, "r") as f:
            desc = f.read()

        regex = r"\s*%([^%]+)%\s*\n\s*([^\n]+)\s*\n"
        meta = dict(re.findall(regex, desc))
        if 'FILENAME' not in meta or 'VERSION' not in meta or 'NAME' not in meta:
            logger.warn(f"Missing metadata from package: {file}")
        return meta

    def _get_pkg(self, pkgname, field=None) -> Union[str, int, dict]:
        self._db.execute(f"SELECT {field if field else '*'} FROM arch_packages WHERE NAME = ?", (pkgname,))
        entry = self._db.fetchone()
        if entry is None:
            return None
        if field is not None:
            return entry[field]
        else:
            return(dict(entry))

    async def _get_file_index(self):
        logger.info(f"Downloading {self._repo}.files.tar.gz")

        if os.path.exists(tmpdir + f"{self._repo}.files.tar.gz"):
            logger.info(f"{self._repo}.files.tar.gz already exists, downloading to {self._repo}.files.tar.gz.new")
            resp = await self._download_file("{}/{}.files.tar.gz".format(self._mirror, self._repo), tmpdir + f"{self._repo}.files.tar.gz.new")

            remote_timestamp = resp.headers['last-modified']
            remote_timestamp = datetime.datetime.strptime(remote_timestamp, '%a, %d %b %Y %X GMT')
            remote_timestamp = remote_timestamp.replace(tzinfo=datetime.timezone.utc).timestamp()

            self._db.execute("""SELECT TIMESTAMP FROM arch_meta WHERE ID = 1;""")
            local_timestamp = self._db.fetchone()['TIMESTAMP']

            if remote_timestamp > local_timestamp:
                logger.info(f"Replacing {self._repo}.files.tar.gz with {self._repo}.files.tar.gz.new")
                os.replace(tmpdir + f"{self._repo}.files.tar.gz.new", tmpdir + f"{self._repo}.files.tar.gz")
                self._update_meta('TIMESTAMP', remote_timestamp)
            else:
                logger.info(f"{self._repo}.files.tar.gz up to date, deleting {self._repo}.files.tar.gz.new")
                os.remove(tmpdir + f"{self._repo}.files.tar.gz.new")

        else:
            resp = await self._download_file("{}/{}.files.tar.gz".format(self._mirror, self._repo), tmpdir + f"{self._repo}.files.tar.gz")
            remote_timestamp = resp.headers['last-modified']
            remote_timestamp = datetime.datetime.strptime(remote_timestamp, '%a, %d %b %Y %X GMT')
            remote_timestamp = remote_timestamp.replace(tzinfo=datetime.timezone.utc).timestamp()
            self._update_meta('TIMESTAMP', remote_timestamp)

        files_compressed = tarfile.open(tmpdir + f"{self._repo}.files.tar.gz", "r")
        logger.info(f"Extracting {self._repo}.files.tar.gz")
        files_compressed.extractall(tmpdir + f"{self._repo}.files")
        files_compressed.close()
        #os.remove(tmpdir + "core.files.tar.gz")
        #logger.info("Deleted core.files.tar.gz")
        logger.info(f"Traversing ./temp/{self._repo}.files")

        # Traverse ./temp/{repo}.files
        self._newpkgs = 0
        self._newpkgs_list = []
        self._updatedpkgs = 0
        self._updatedpkgs_list = []
        havemanpkgs = 0
        totalpkgs = 0
        for (root, dirs, files) in os.walk(tmpdir + f"{self._repo}.files", topdown=True):
            if files != [] and 'files' in files and 'desc' in files: # root has no files
                manpaths = self._read_files(root + '/' + 'files')
                meta = self._read_desc(root + '/' + 'desc')
                if manpaths and meta != None:
                    pkg = {
                            "name": meta["NAME"],
                            "repo": self._repo,
                            "version": meta["VERSION"],
                            "filename": meta['FILENAME'],
                            "arch": meta['ARCH'],
                            "upstream": meta['URL'],
                            "license": meta['LICENSE'],
                            "url": f"{self._mirror}/{meta['FILENAME']}",
                            "manpaths": manpaths
                    }
                    
                    oldver = self._get_pkg(pkg['name'], 'VERSION')
                    if oldver is None:
                        # new entry
                        self._db.execute(f"""INSERT INTO arch_packages (NAME, REPO, VERSION, FILENAME, ARCH, UPSTREAM, LICENSE, URL, MANPATHS)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """, (pkg['name'], pkg['repo'], pkg['version'], pkg['filename'], pkg['arch'], pkg['upstream'], pkg['license'], pkg['url'], json.dumps(pkg['manpaths']),))
                        self._newpkgs += 1
                        self._newpkgs_list.append(pkg)
                        logger.info(f"New package: {pkg['name']} {pkg['version']}")
                    elif version.parse(pkg['version']) > version.parse(oldver):
                            # downloaded version is newer, update
                            self._db.execute(f"""UPDATE arch_packages
                            SET VERSION = ?,
                                FILENAME = ?,
                                ARCH = ?,
                                UPSTREAM = ?,
                                LICENSE = ?,
                                URL = ?,
                                MANPATHS = ?,
                            WHERE
                                NAME = ?;
                            """, (pkg['version'], pkg['filename'], pkg['arch'], pkg['upstream'], pkg['license'], pkg['url'], json.dumps(pkg['manpaths'],pkg['name'],)))
                            logger.info(f"Package '{pkg['name']}' updated: {oldver} -> {pkg['version']}")
                            self._updatedpkgs += 1
                            self._updatedpkgs_list.append(pkg)
                    havemanpkgs += 1
                totalpkgs += 1

        self._update_meta('HAVEMAN_PKGS', havemanpkgs)
        self._update_meta('TOTAL_PKGS', totalpkgs)
        logger.info(f"Package database parsed: {self._newpkgs} new, {self._updatedpkgs} updated, {havemanpkgs} have man, {totalpkgs} total")
        self._con.commit()


    async def _get_man_contents(self, pkg: dict) -> tuple[list, list, list]:
        """
        pkg: dict
        {
            "name": str,
            "repo": str, #core/community/extra
            "version": str,
            "filename": str,
            "url": str,
            "manpaths": str #use json.loads
        }
        """
        path = tmpdir + 'pkgs/' + pkg['filename']
        resp = await self._download_file(pkg['url'], path)
        with tarfile.open(path, "r") as t:
            #hardlinks = []
            symlinks = []
            files = []
            for file in pkg['manpaths']:
                info = t.getmember(file)
                # just treat hardlinks like normal files because it's too hard
#                if info.islnk():
#                    target = info.linkname
#                    if target.endswith(".gz"):
#                        target = target[:-3]
#                    hardlinks.append ( ("hardlink", file, target) )
                if info.issym():
                    if file.endswith(".gz"):
                        file = file[:-3]
                    target = info.linkname
                    if target.endswith(".gz"):
                        target = target[:-3]
                        symlinks.append( ("symlink", file, target) )
                else:
                    man = t.extractfile(file).read()
                    if file.endswith(".gz"):
                        file = file[:-3]
                        man = gzip.decompress(man)
                        man = self._decode(man)
                    files.append( ("file", file, man))
        #return (files, symlinks, hardlinks,)
        return (files, symlinks,)

    async def _update_man_pages(self):
        # update self._updatedpkgs_list and self._newpkgs_list
        to_update = self._updatedpkgs_list + self._newpkgs_list
        logger.info(f"Updating man pages from {len(to_update)} packages")

        updated_pages = 0

        redirects = []
        #hardlink_list= []

        for pkg in to_update:
            files, symlinks = await self._get_man_contents(pkg)
            for file in files:
                html_content = mandoc_convert(file[2], "html")
                txt_content = mandoc_convert(file[2], 'txt')
                headings = json.dumps(extract_headings(html_content))
                description = extract_description(txt_content)

                self._insert_manpage(pkg['name'], file[1], headings, description, file[2], html_content, txt_content)

                updated_pages += 1
            #for hardlink in hardlinks:

            #    # extract info from source
            #    try:
            #        source_name, source_section, source_lang = self._getmanpathinfo(hardlink[1])
            #    except UnknownManPath:
            #        logger.warning("Skipping hardlink with unrecognized source path: {}".format(hardlink[1]))
            #        continue

            #    # extract info from target
            #    try:
            #        target_name, target_section, target_lang = self._getmanpathinfo(hardlink[2])
            #    except UnknownManPath:
            #        logger.warning("Skipping hardlink with unrecognized target path: {}".format(hardlink[2]))
            #        continue
            #    
            #    # drop encoding from the lang (ru.KOI8-R)
            #    if "." in source_lang:
            #        source_lang, _ = source_lang.split(".", maxsplit=1)
            #    if "." in target_lang:
            #        target_lang, _ = target_lang.split(".", maxsplit=1)

            #    if target_lang == source_lang and target_section == source_section and target_name == source_name:
            #        logger.warning("Skipping hardlink from {} to {} (the base name is the same).".format(source, target))
            #        continue

            #    hardlink_list.append((source_name, source_section, source_lang, target_name, target_section, target_lang,))

            #    manpage = self._get_manpage(hardlink[2])
            #    content = manpage['CONTENT']
            #    html_content = manpage['HTML_CONTENT']
            #    txt_content = manpage['TXT_CONTENT']
            #    headings = json.dumps(extract_headings(html_content))
            #    description = extract_description(txt_content)

            #    self._insert_manpage(pkg['name'], hardlink[1], headings, description, content, html_content, txt_content)

            for symlink in symlinks:
                source, target = symlink[1], symlink[2]

                try:
                    source_name, source_section, source_lang = self._getmanpathinfo(source)
                except UnknownManPath:
                    logger.warning("Skipping symlink with unrecognized structure: {}".format(source))
                    continue

                if target.startswith("/"):
                    # make target relative to "/"
                    target = target[1:]
                else:
                    # make target full path
                    ppt = PurePath(source).parent / target
                    # normalize to remove any '..'
                    target = os.path.normpath(ppt)

                # extract info from target, check if it makes sense
                try:
                    target_name, target_section, target_lang = self._getmanpathinfo(target)
                except UnknownManPath:
                    logger.warning("Skipping symlink with unknown target: {}".format(target))
                    continue

                # drop encoding from the lang (ru.KOI8-R)
                if "." in source_lang:
                    source_lang, _ = source_lang.split(".", maxsplit=1)
                if "." in target_lang:
                    target_lang, _ = target_lang.split(".", maxsplit=1)

                # drop cross-language symlinks
                if target_lang != source_lang:
                    logger.warning("Skipping cross-language symlink from {} to {}".format(source, target))
                    continue

                # drop useless redirects
                if target_section == source_section and target_name == source_name:
                    logger.warning("Skipping symlink from {} to {} (the base name is the same).".format(source, target))
                    continue

                redirects.append((source_name, source_section, source_lang, target_name, target_section, target_lang,))
                updated_pages += 1

        self._insert_redirects(redirects)

        self._con.commit()

        # Useless
        self._db.execute('SELECT COUNT(*) from arch_manpages')
        manpage_count = self._db.fetchone()[0]
        self._db.execute('SELECT COUNT(*) from arch_redirects')
        redirect_count = self._db.fetchone()[0]
        self._db.execute('SELECT COUNT(*) from arch_packages')
        pkg_count = self._db.fetchone()[0]
        self._updated_pages = updated_pages
        logger.info(f"DB contains {manpage_count} manpages and {redirect_count} symlinks from {pkg_count} packages")

    def _postprocess(self):
        resolve_so_links(self._db)

    async def main(self):
        await self._get_file_index()
        await self._update_man_pages()
        self._postprocess()
        self.INDEXER_ENDTIME = int(time.time())
        self._insert_execution()
        self._con.commit()

async def main():
    async with Indexer("core", "packages.db") as indexer:
        await indexer.main()

if __name__ == "__main__":
    asyncio.run(main())
