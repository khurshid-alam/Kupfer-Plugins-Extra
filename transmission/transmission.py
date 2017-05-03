# -*- encoding: UTF-8 -*-
__kupfer_name__ = _("Transmission")
__kupfer_sources__ = ("TorrentSource", )
__kupfer_actions__ = ("ViewTorrent", )
__description__ = _("Search and perform actions on active Torrents in Transmission")
__version__ = "2017.2"
__author__ = ""

import sys
import json
import os 
import logging
import dbus
import gi
import subprocess
import ast
import dateutil
import time
import transmissionrpc
import libtorrent as lt
from os.path import basename
import xdg.BaseDirectory as base
from datetime import date, datetime, timezone
from dateutil.tz import tzlocal
gi.require_version('Gtk', '3.0')


from kupfer import plugin_support
from kupfer import pretty, utils
from kupfer import textutils
from kupfer.objects import Leaf, Action, Source
from kupfer.objects import TextLeaf, AppLeaf 
from kupfer.objects import NotAvailableError, OperationError
from kupfer.obj.apps import AppLeafContentMixin
from kupfer.obj.grouping import ToplevelGroupingSource
from kupfer.obj.helplib import FilesystemWatchMixin
from kupfer.plugin_support import PluginSettings





Torrent_ID = "transmission-gtk"

### Read Settings ##########################################
# Set the third, optional argument of get to 1 if you wish to use raw mode.

TM_CONFIG_PATH = (os.path.join(base.xdg_config_home, 
                               "transmission/settings.json"))
with open(TM_CONFIG_PATH) as data_file:    
    tm_settings = json.load(data_file)
    tm_host = tm_settings['rpc-whitelist']
    if tm_host == None:
        tm_host = "127.0.0.1"   
    tm_port = tm_settings['rpc-port']
    tm_user = tm_settings['rpc-username']
    if tm_user == '':
        tm_user = None



__kupfer_settings__ = PluginSettings( 
        {
                "key" : "tm_pass",
                "label": _("Transmission RPC passwowd"),
                "type": str,
                "value": "",
        }
)



tm_pass = __kupfer_settings__["tm_pass"]

if not tm_pass:
    tm_pass = "transmission"




LEVELS = {'debug': logging.DEBUG,
          'info': logging.INFO,
          'warning': logging.WARNING,
          'error': logging.ERROR,
          'critical': logging.CRITICAL
          }




def humanbytes(B):
   'Return the given bytes as a human friendly KB, MB, GB, or TB string'
   B = float(B)
   KB = float(1024)
   MB = float(KB ** 2) # 1,048,576
   GB = float(KB ** 3) # 1,073,741,824
   TB = float(KB ** 4) # 1,099,511,627,776

   if B < KB:
      return '{0} {1}'.format(B,'Bytes' if 0 == B > 1 else 'Byte')
   elif KB <= B < MB:
      return '{0:.2f} KB'.format(B/KB)
   elif MB <= B < GB:
      return '{0:.2f} MB'.format(B/MB)
   elif GB <= B < TB:
      return '{0:.2f} GB'.format(B/GB)
   elif TB <= B:
      return '{0:.2f} TB'.format(B/TB)


def spawn_async(argv):
    try:
        utils.spawn_async_raise(argv)
    except utils.SpawnError as exc:
        raise OperationError(exc)


def _is_connection_error(error):
    http_error_class = transmissionrpc.HTTPHandlerError
    return isinstance(error.original, http_error_class) and error.original.code == 111


def _get_error_msg():
    t_error = ("Failed to connect to tranmsission " 
               "on %s:%d, check your settings." %(tm_host, tm_port))

    return t_error


def _connect_rpc():
    try:
        transmission = transmissionrpc.Client(
            address=tm_host,
            port=tm_port,
            user=tm_user,
            password=tm_pass,
        )
        return transmission
    
    except transmissionrpc.TransmissionError:
        logging.error("Failed to connect to tranmsission"
                      "on %s, check your settings." % tm_host)
        return False
    



def _get_all_torrents():
  TORRENTS_DIR = (os.path.join(base.xdg_config_home, "transmission/torrents"))
  if os.path.exists(TORRENTS_DIR):
      for torrent in os.listdir(TORRENTS_DIR):
          try:
              t_obj = lt.torrent_info(os.path.join(TORRENTS_DIR, torrent))
          except:
              pass
          t_hash = str(t_obj.info_hash())
          t_name = t_obj.name()

          otorrent = Torrent(t_hash, t_name)
          yield otorrent



class ViewTorrent (Action):
    def __init__(self):
        Action.__init__(self, _("View"))

    def activate(self, leaf):
        #interface = _create_dbus_connection(True)
        spawn_async(("transmission-gtk", "-m"))

    def get_icon_name(self):
        return 'transmission'

    def get_description(self):
        return _("View Torrent in Transmission")



class StartTorrent (Action):
    def __init__(self):
        Action.__init__(self, _("Start Torrent"))

    def activate(self, leaf):
        torrent_hash = str(leaf.hid)
        tc = _connect_rpc()
        if tc:
            tc.start_torrent(torrent_hash)
        else:
            raise OperationError(_get_error_msg())


    def get_icon_name(self):
        return 'media-playback-start'

    def get_description(self):
        return _("Start running Torrent in Transmission")



class PauseTorrent (Action):
    def __init__(self):
        Action.__init__(self, _("Stop Torrent"))

    def activate(self, leaf):
        torrent_hash = str(leaf.hid)
        tc = _connect_rpc()
        if tc:
            tc.stop_torrent(torrent_hash)
        else:
            raise OperationError(_get_error_msg())


    def get_icon_name(self):
        return 'media-playback-pause'

    def get_description(self):
        return _("Pause running Torrent in Transmission")


      


class Torrent(Leaf):
    def __init__(self, t_hash, t_name):
        Leaf.__init__(self, t_hash, t_name)
        self.hid = t_hash
        self.title = t_name

    def get_description(self):
        descr = "Name : %s" % self.title
        return descr

    def get_icon_name(self):
        return 'transmission'

    def get_actions(self):
        yield ViewTorrent()
        yield StartTorrent()
        yield PauseTorrent()



class TorrentSource (AppLeafContentMixin,
                ToplevelGroupingSource, FilesystemWatchMixin):

    appleaf_content_id = Torrent_ID

    def __init__(self, name=None):
        ToplevelGroupingSource.__init__(self, name, _("Torrents"))
        self._torrent = []
        self._version = 3

    def initialize(self):
        ToplevelGroupingSource.initialize(self)
        TORRENTS_DIR = (os.path.join(base.xdg_config_home, "transmission/torrents"))
        self.monitor_token = self.monitor_directories(TORRENTS_DIR)


    def get_items(self):
        self._torrent = list(_get_all_torrents())
        return self._torrent

    def get_icon_name(self):
        return 'transmission'

    def provides(self):
        yield Torrent
