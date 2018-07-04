# -*- encoding: UTF-8 -*-
__kupfer_name__ = _("Gnome Calendar")
__kupfer_sources__ = ("EventSource", )
__kupfer_actions__ = ("CreateGcalEvent", )
__description__ = _("Search and open calendar events with Gnome-Calendar")
__version__ = "2017.2"
__author__ = ""


import sys
import os
import dbus
import gi
import subprocess
import hashlib, ast
import vobject
import datetime
import xdg.BaseDirectory as base
from libtools.json_tools import load_from_json, save_to_json

gi.require_version('Unity', '7.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Unity, Dbusmenu

from kupfer import plugin_support
from kupfer import pretty, utils
from kupfer import textutils
from kupfer.objects import Leaf, Action, Source
from kupfer.objects import TextLeaf, NotAvailableError, AppLeaf
from kupfer.objects import UrlLeaf, RunnableLeaf, FileLeaf
from kupfer.obj.apps import AppLeafContentMixin
from kupfer.obj.grouping import ToplevelGroupingSource
from kupfer.obj.helplib import FilesystemWatchMixin

plugin_support.check_dbus_connection()


Calendar_ID = "org.gnome.Calendar"

SERVICE_NAME = "org.gnome.Calendar" 
OBJECT_NAME = "/org/gnome/Calendar/SearchProvider" 
IFACE_NAME = "org.gnome.Shell.SearchProvider2"


EDS_CAL_PATH = (os.path.join(base.xdg_data_home, "evolution/calendar"))
EDS_CAL_WEB_PATH = (os.path.join(base.xdg_cache_home, "evolution/calendar"))
EDS_ALARMS_PATH = (os.path.join(base.xdg_data_home, "evolution/calendar/alarms"))
GCALD_CACHE = (os.path.join(base.xdg_data_home, "kupfer/plugins/gcald"))


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
        pretty.print_debug(__name__, err)
    return interface


def file_get_contents(filename):
  if os.path.exists(filename):
    fp = open(filename, "r")
    content = fp.read()
    fp.close()
    return content


def spawn_async(argv):
    try:
        utils.spawn_async_raise(argv)
    except utils.SpawnError as exc:
        raise OperationError(exc)
        
        
def _get_calendar_dirs(EDS_CAL_PATH, EDS_CAL_WEB_PATH):
    calendar_dirs = []
    for d in os.listdir(EDS_CAL_PATH):
        if d != "trash" and d!= "alarms":
            dd = os.path.join(EDS_CAL_PATH, d)
            calendar_dirs.append(dd)
            
    for d in os.listdir(EDS_CAL_WEB_PATH):
        if d != "trash":
            dd = os.path.join(EDS_CAL_WEB_PATH, d)
            calendar_dirs.append(dd)
            
            
    return calendar_dirs
            


def _get_calendar_uids(EDS_CAL_PATH, EDS_CAL_WEB_PATH):
    local_calendar_uids = []
    web_calendar_uids = []
    for dir in os.listdir(EDS_CAL_PATH):
        if dir != "trash":
            local_calendar_uids += [dir]
    local_calendar_uids = [word.replace('system','system-calendar') for word in local_calendar_uids]


    for dir in os.listdir(EDS_CAL_WEB_PATH):
        if os.path.exists(EDS_CAL_WEB_PATH + "/" + dir + "/calendar.ics"):
            WEB_CAL_EXISTS = True
            if os.path.exists(EDS_CAL_WEB_PATH + "/" + dir + "/keys.xml"):
                if dir != "trash":
                    web_calendar_uids += [dir]
                    
            calendar_uids_all = local_calendar_uids + web_calendar_uids

        else:
            WEB_CAL_EXISTS = False
            calendar_uids_all = local_calendar_uids + web_calendar_uids

    return calendar_uids_all


def _load_calendars(calendar_uids):
    cmd = 'syncevolution --print-databases | awk "/evolution-calendar:/{f=1;next} /Evolution Task/{f=0} f" | sed -e "s/^[ \t]*//" | grep -v "Birthdays & Anniversaries (birthdays)" | sed -e "s/<default>//g"'
    cal_data = subprocess.check_output(cmd, shell=True)
    cal_data = cal_data.decode("utf-8")
    cal_data = cal_data.split("\n")
    m = list(filter(None, cal_data))
    cal_obj = {}

    for i in m:
        cald = i.split(" ")
        cal_name = cald[0]
        cal_uid = cald[1].strip("(").strip(")")
        for l in calendar_uids:
            if l == cal_uid:
                cal_obj[cal_uid] = cal_name

    return cal_obj



def _load_gcals():
    if os.path.exists(GCALD_CACHE):
        cal_data = file_get_contents(GCALD_CACHE)
        cal_data = ast.literal_eval(cal_data)
        gcald = {}
        for c in cal_data:
            gcald[c] = ('_' + c)
    else:
        cmd = 'gcalcli list | grep owner | awk -F" " \'{print $3}\''
        cal_data = ((subprocess.check_output(cmd, shell=True)).decode("utf-8")).split("\n")
        cal_data = list(filter(None, cal_data))
        with open(GCALD_CACHE,'w') as f:
            f.write(str(cal_data))
            f.close
        gcald = {}
        for c in cal_data:
            gcald[c] = ('_' + c)

    return gcald


    
def check_item_activated_callback(menuitem, a, b):#main menu item
    spawn_async(("gnome-calendar", "-u", b))

    
    
def add_item_to_qlist(ql, item, name, uid, due, launcher):
	y = str((datetime.datetime.now().year))

	due = due.split("2018")[0]
	due = due + '2018'
	d = datetime.datetime.strptime(due, "%A %d %B %Y")
    
	d = d.date()
	t = datetime.datetime.today()
	t = t.date()
	
	if t == d:
		item = Dbusmenu.Menuitem.new ()
		item.property_set (Dbusmenu.MENUITEM_PROP_LABEL, name)
		item.property_set_bool (Dbusmenu.MENUITEM_PROP_VISIBLE, True)
		item.connect ("item-activated", check_item_activated_callback, uid)
		ql.child_append (item)
		launcher.set_property("quicklist", ql)        
	else:
		pass        

def update_alarm_disc(alarm_disc, event_uid, title, due):
    due = due.split(" IST.")[0]
    d = datetime.datetime.strptime(due, "%A %d %B %Y %I:%M:%S %p")
    d_stamp = d.strftime("%s")
    t = (int(d_stamp) * 1000 * 1000)
    _d = d.strftime("%-I:%M %p")
    now = datetime.datetime.now()
    d_timer = (d - datetime.timedelta(minutes = 15))

    if event_uid not in alarm_disc:
        alarm_disc[event_uid] = {"alarm": True, "due": due, "title": title}
    else:
        if alarm_disc[event_uid]["due"] != due:
            alarm_disc[event_uid]["alarm"] = True
            alarm_disc[event_uid]["due"] = due
            alarm_disc[event_uid]["title"] = title
                  
    save_to_json(alarm_disc,
            os.path.join(EDS_ALARMS_PATH, "alarms.json"))
            
    return alarm_disc   


def _load_events(interface):
    #global ql
    # Quicklist integration
    alarm_disc = load_from_json(os.path.join(EDS_ALARMS_PATH, "alarms.json"))
    launcher = Unity.LauncherEntry.get_for_desktop_id ("org.gnome.Calendar.desktop")
    try:
        if ql:
            for c in ql.get_children():
                ql.child_delete(c)
            #ql = Dbusmenu.Menuitem.new ()
    except:
        pretty.print_debug(__name__, "ql is not defined yet")    
        ql = Dbusmenu.Menuitem.new ()    
    
    ''' Get all visible events from all active eds calendars '''
    event_uids = interface.GetInitialResultSet([""])
    for event_uid in event_uids:
        item = "item" + str((event_uids.index(event_uid)))
        event_dict = interface.GetResultMetas([event_uid])
        for event_obj in event_dict:
            title = event_obj['name']
            due = event_obj['description']
            add_item_to_qlist(ql, item, title, event_uid, due, launcher)
            
            if "AM" in due or "PM" in due:
                alarm_disc = update_alarm_disc(alarm_disc, event_uid, title, due)            
            
            oevent = Event(event_uid, title, due)
            yield oevent
    
    '''
    alarm_disc1 = load_from_json(os.path.join(EDS_ALARMS_PATH, "alarms.json"))
    for aid, ad in alarm_disc1.items():
        if aid not in event_uids:
            alarm_disc1.pop(event_uid)            
            save_to_json(alarm_disc1,
                os.path.join(EDS_ALARMS_PATH, "alarms.json"))
    '''    
    

                    
    if ql is not None:
        for c in ql.get_children():
            pretty.print_debug(__name__, c.property_get(Dbusmenu.MENUITEM_PROP_LABEL))        
        #launcher.set_property("quicklist", ql)



class OpenCalendarEvent (Action):
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



class CreateGcalEvent (Action):
    def __init__(self):
        Action.__init__(self, _("Create Event In Google Calendar"))

    def activate(self, leaf, obj):
        summary = leaf.object
        gcal_uid = obj.cid
        cmd = '\'gcalcli --calendar ' + gcal_uid + " " + '"' + summary + '"\''
        subprocess.check_call(["gcalcli", "quick", "--calendar", gcal_uid, summary])

    def item_types(self):
        yield TextLeaf

    def requires_object(self):
        return True

    def object_types(self):
        yield Gcalendar

    def object_source(self, for_item=None):
        return GcalendarSource()

    def get_description(self):
        return _("Add event to existing calendar")

    def get_icon_name(self):
        return "stock_new-appointment"



class Gcalendar(Leaf):
    def __init__(self, gcal_uid, gcal_name):
        Leaf.__init__(self, gcal_uid, gcal_name)
        self.cid = gcal_uid
        self.title = gcal_name

    def get_description(self):
        descr = "Name : %s" % self.title
        return descr

    def get_icon_name(self):
        return 'calendar'




class Event (Leaf):
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
        yield OpenCalendarEvent()


class AccountStatus(Leaf):
    pass


class CalendarIdSource(Source):

    def __init__(self):
        Source.__init__(self, _("Calendar Source"))

    def get_items(self):
        calendar_uids = _get_calendar_uids(EDS_CAL_PATH, EDS_CAL_WEB_PATH)
        cld = _load_calendars(calendar_uids)
        for cal_uid, cal_name in cld.items():
            yield Calendar(cal_uid, cal_name)

    def provides(self):
        yield Calendar





class GcalendarSource(Source):

    def __init__(self):
        Source.__init__(self, _("Calendar Source"))

    def get_items(self):
        gcald = _load_gcals()
        for gcal_uid, gcal_name in gcald.items():
            yield Gcalendar(gcal_uid, gcal_name)

    def provides(self):
        yield Gcalendar






class EventSource (AppLeafContentMixin, ToplevelGroupingSource, FilesystemWatchMixin):
    appleaf_content_id = Calendar_ID

    def __init__(self, name=None):
        ToplevelGroupingSource.__init__(self, name, _("Calendar Events"))
        self._event = []
        self._version = 3

    def initialize(self):
        ToplevelGroupingSource.initialize(self)
        
        eds_cache = _get_calendar_dirs(EDS_CAL_PATH, EDS_CAL_WEB_PATH)
        if eds_cache:
            self.monitor_token = self.monitor_directories(*eds_cache)
        
    def monitor_include_file(self, gfile):
        return gfile and (gfile.get_basename().endswith('.ics') \
                or (gfile.get_basename().endswith('.db') \
                or gfile.get_basename() == 'calendar.ics') \
                or gfile.get_basename() == 'cache.db')


    def get_items(self):
        interface = _create_dbus_connection(SERVICE_NAME, OBJECT_NAME, IFACE_NAME, activate=True)
        if interface is not None:
            self._event = list(_load_events(interface))
        return self._event

    def get_icon_name(self):
        return 'calendar'

    def provides(self):
        yield Event


