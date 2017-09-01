#!/usr/bin/env python3
# -*- coding: utf-8 -*-

'''
__kupfer_name__ = _("Chromium Bugs")
__kupfer_sources__ = ("BugsSource", )
__kupfer_actions__ = ()
__description__ = _("Index of a Chromium bookmarks folder")
__version__ = "2017.1"
__author__ = "Khurshid Alam"
'''

import os
import re
import sys
import json
import subprocess

import lxml.etree as xml
from urllib.parse import quote, urlparse

sys.path.append("/usr/share/kupfer")
from kupfer import plugin_support
from kupfer.plugin_support import PluginSettings
from kupfer.objects import Source, Action, Leaf
from kupfer.objects import UrlLeaf, TextLeaf, TextSource
from kupfer.obj.apps import AppLeafContentMixin
from kupfer.obj.helplib import FilesystemWatchMixin
from kupfer.obj.objects import OpenUrl
from kupfer import utils


BUGS_HOME = os.path.join(os.environ['HOME'], ".config", "chromium", "Default")

__kupfer_settings__ = PluginSettings( 
        {
                "key" : "bm_folder_name",
                "label": _("Bookmark Folder"),
                "type": str,
                "value": "",
        }
)



bm_folder = __kupfer_settings__["bm_folder_name"]

if not bm_folder:
    bm_folder = "Bugs"






# Recurse through a bookmark structure accumulating matches
# Does not recursively explore a matched folder: just adds its direct children
def search_bookmark(bm, names):
	acc = {}
	if bm['name'] in names:
		if bm['type'] == 'url':
                        acc[bm['url']] = bm['name']   
		elif bm['type'] == 'folder':
			for child in bm['children']:
				if child['type'] == 'url':
					acc[child['url']] = child['name']

	elif bm['type'] == 'folder':
		for child in bm['children']:
			acc.update(search_bookmark(child, names))

	return acc


# Get all bookmarks matching the given name(s)
def get_bookmarks(profile_dir, names):
	with open(os.path.join(profile_dir, 'Bookmarks')) as f:
		j = json.load(f)
		results = {}
		# There are two root-level bookmark folders: one for the bookmark bar and one for all others.
		results.update(search_bookmark(j['roots']['bookmark_bar'], names))
		#results.extend(search_bookmark(j['roots']['other'], names))
		return results



class BugsSource (AppLeafContentMixin, Source, FilesystemWatchMixin):
    appleaf_content_id = ("chromium-browser", "chrome")
    def __init__(self):
        super().__init__(_("Chromium Bookmarks"))
        self._version = 3

    def initialize(self):
        self.monitor_token = self.monitor_directories(BUGS_HOME)

    def monitor_include_file(self, gfile):
        return gfile and gfile.get_basename() == 'lock'

    def _get_bugs(self):
        """Query the firefox places bookmark database"""
        fpath = os.path.join(BUGS_HOME, Bookmarks)
        if not (fpath and os.path.isfile(fpath)):
            return []
        try:
            c = get_bookmarks(BUGS_HOME, bm_folder)
            return [UrlLeaf(url, title) for url, title in c]
        except:
            # Something is wrong with the database
            return []

    def get_items(self):
        return self._get_bugs()

    def get_description(self):
        return _("Index of Chromium Bookmarks Folder")

    def get_gicon(self):
        return self.get_leaf_repr() and self.get_leaf_repr().get_gicon()

    def get_icon_name(self):
        return "web-browser"

    def provides(self):
        yield UrlLeaf


c = get_bookmarks(BUGS_HOME, bm_folder)
for u, t in c.items():
    print (u)

