# -*- encoding: UTF-8 -*-
__kupfer_name__ = _("Gnome Calendar")
__kupfer_sources__ = ("CalendarSource", )
__kupfer_actions__ = ("", )
__description__ = _("Search and open calendar events with Gnome-Calendar")
__version__ = "2017.2"
__author__ = ""


import sys
import os
import dbus
import gi
import subprocess
import hashlib
import vobject
import xdg.BaseDirectory as base
gi.require_version('Gtk', '3.0')

from kupfer import plugin_support
from kupfer import pretty, utils
from kupfer import textutils
from kupfer.objects import Leaf, Action, Source
from kupfer.objects import TextLeaf, NotAvailableError, AppLeaf
from kupfer.objects import UrlLeaf, RunnableLeaf, FileLeaf
from kupfer.obj.apps import AppLeafContentMixin
from kupfer.obj.grouping import ToplevelGroupingSource

plugin_support.check_dbus_connection()


Calendar_ID = "org.gnome.Calendar"

SERVICE_NAME = "org.gnome.Calendar" 
OBJECT_NAME = "/org/gnome/Calendar/SearchProvider" 
IFACE_NAME = "org.gnome.Shell.SearchProvider2"


def _create_dbus_connection(SERVICE_NAME, OBJECT_NAME, IFACE_NAME, activate=False):
    ''' Create dbus connection to Gnome Calendar
    @activate: true=starts Gnome Calendar if not running
    '''
    interface = None
    obj = None
    sbus = dbus.SessionBus()

    try:
        #check for running pidgin (code from note.py)
        proxy_obj = sbus.get_object('org.freedesktop.DBus', '/org/freedesktop/DBus')
        dbus_iface = dbus.Interface(proxy_obj, 'org.freedesktop.DBus')
        if activate or dbus_iface.NameHasOwner(SERVICE_NAME):
            obj = sbus.get_object(SERVICE_NAME, OBJECT_NAME)
        if obj:
            interface = dbus.Interface(obj, IFACE_NAME)
    except dbus.exceptions.DBusException as err:
        pretty.print_debug(err)
    return interface




def _load_events(interface):
    ''' Get all visible events from all active eds calendars '''
    event_uids = interface.GetInitialResultSet([""])
    for event_uid in event_uids:
        event_dict = interface.GetResultMetas([event_uid])
        for event_obj in event_dict:
            title = event_obj['name']
            due = event_obj['description']
            
            oevent = Calendar(event_uid, title, due)
            yield oevent



def spawn_async(argv):
    try:
        utils.spawn_async_raise(argv)
    except utils.SpawnError as exc:
        raise OperationError(exc)



class OpenCalendar (Action):
    rank_adjust = 1
    action_accelerator = "o"

    def __init__(self):
        Action.__init__(self, _("Open"))

    def activate(self, leaf):
        #interface = _create_dbus_connection(True)
        spawn_async(("gnome-calendar", "-u", leaf.eid))

    def get_icon_name(self):
        return 'org.gnome.Calendar'

    def get_description(self):
        return _("Open calendar event in Gnome Calendar")


class Calendar (Leaf):
    def __init__(self, event_uid, title, due):
        Leaf.__init__(self, event_uid, title)
        self.eid = event_uid
        self.title = title
        self.due = due

    def get_description(self):
        descr = "Due : %s" % self.due
        return descr

    def get_icon_name(self):
        return 'calendar'

    def get_actions(self):
        yield OpenCalendar()


class CalendarSource (AppLeafContentMixin, ToplevelGroupingSource):
    appleaf_content_id = Calendar_ID

    def __init__(self, name=None):
        ToplevelGroupingSource.__init__(self, name, _("Calendar Events"))
        self._calendar = []
        self._version = 3

    def initialize(self):
        ToplevelGroupingSource.initialize(self)


    def get_items(self):
        interface = _create_dbus_connection(SERVICE_NAME, OBJECT_NAME, IFACE_NAME, activate=True)
        self._calendar = list(_load_events(interface))
        return self._calendar

    def get_icon_name(self):
        return 'calendar'

    def provides(self):
        yield Calendar
