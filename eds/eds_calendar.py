# -*- encoding: UTF-8 -*-
__kupfer_name__ = _("Gnome Calendar")
__kupfer_sources__ = ("EventSource", )
__kupfer_actions__ = ("CreateGcalEvent", )
__description__ = _("Search and open calendar events with Gnome-Calendar")
__version__ = "2017.2"
__author__ = ""


import os
import gi
import re
import sys
import dbus
import time
import sqlite3
import vobject
import datetime
import subprocess
import hashlib, ast
from contextlib import closing

import xdg.BaseDirectory as base
from libtools.json_tools import load_from_json, save_to_json

gi.require_version('Unity', '7.0')
gi.require_version('Gtk', '3.0')
gi.require_version('EDataServer', '1.2')

from gi.repository import Gio, GLib
from gi.repository import EDataServer
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
from kupfer.weaklib import dbus_signal_connect_weakly

plugin_support.check_dbus_connection()


Calendar_ID = "org.gnome.Calendar"

SERVICE_NAME = "org.gnome.Calendar" 
OBJECT_NAME = "/org/gnome/Calendar/SearchProvider" 
IFACE_NAME = "org.gnome.Shell.SearchProvider2"


EDS_CAL_PATH = (os.path.join(base.xdg_data_home, "evolution/calendar"))
EDS_CAL_WEB_PATH = (os.path.join(base.xdg_cache_home, "evolution/calendar"))
EDS_ALARMS_PATH = (os.path.join(base.xdg_data_home, "evolution/calendar/alarms"))
GCALD_CACHE = (os.path.join(base.xdg_data_home, "kupfer/plugins/gcald"))

launcher = Unity.LauncherEntry.get_for_desktop_id ("org.gnome.Calendar.desktop")
S_OLD = None

RELOAD_AGIAN = False
MAX_ITEMS = 200
dt = datetime.datetime.today()
now = datetime.datetime.now()
m = dt.strftime('%m')
d = dt.strftime('%d')
EV_BEGIN = (str(dt.year)+str(m)+str(d))

m = datetime.datetime(dt.year + int(dt.month / 12), ((dt.month % 12) + 1), 1)
m = m.strftime('%m')
EV_END = (str(dt.year)+str(m)+'01')


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
        
def utc2local (utc):
    epoch = time.mktime(utc.timetuple())
    offset = datetime.datetime.fromtimestamp (epoch) - datetime.datetime.utcfromtimestamp (epoch)
    return utc + offset
        
        
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


def _load_calendars():
# Open a registry and get a list of all the calendars in EDS
	registry = EDataServer.SourceRegistry.new_sync(None)
	sources = EDataServer.SourceRegistry.list_enabled(registry, 
		                         EDataServer.SOURCE_EXTENSION_CALENDAR)

	cal_dict = {}
	for source in sources:
		cal_name = source.get_display_name()
		if cal_name == "Birthdays & Anniversaries":
			continue
		cal_stub = source.get_parent()
		cal_uid = source.get_uid()
		cal_dict[cal_uid] = {"cal_name": cal_name, "stub": cal_stub}
		
	return cal_dict



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



def fix_ical(ical_path):

	with open(ical_path, 'r') as ical:
		all = ical.read()

	# Discard all carriage returns. Makes pattern matching easier.
	# Output then doesn't contain them either.
	all = all.replace('\r', '')

	# Final result.
	calendars = []

	# Process each VCALENDAR.
	for calendar_match in re.finditer(r'''^BEGIN:VCALENDAR$.*?^END:VCALENDAR$''',
		                              all,
		                              re.MULTILINE + re.DOTALL):
		calendar = calendar_match.group(0)
		# Find all individual items inside the calendar.
		items = [m.group(0) for m in re.finditer(r'''^BEGIN:(?P<kind>VEVENT|VJOURNAL|VTODO)\n.*?^END:(?P=kind)\n''',
		                                         calendar,
		                                         re.MULTILINE + re.DOTALL)]
		# Strip these items from the calendar. We need the remaining
		# VERSION, PRODID, and in particular VTIMEZONE.
		for item in items:
		    calendar = calendar.replace(item, '', 1)
		# Now inject one item after the other at the end to produce new VCALENDARs.
		calendars.extend([calendar.replace('\nEND:VCALENDAR',
		                                   '\n' + item + 'END:VCALENDAR').replace('\n', '\r\n')
		                  for item in items])

	# Now print result, with empty line as separator.
	fixed_ical = ('\r\n\r\n'.join(calendars))
	return fixed_ical
	

def _get_local_events(local_calendar_uids):
	event_dict = {}
	for cal_uid in local_calendar_uids:
		if cal_uid == "system-calendar":
			cal_uid = "system"
		ical_path = os.path.join(EDS_CAL_PATH, cal_uid + "/calendar.ics" )
		with open(ical_path, 'r') as ical:
			icalstream = ical.read()
			icalstream = fix_ical(ical_path) 
			#print (icalstream)
			cal_obj = vobject.readComponents(icalstream)
			for event in cal_obj:
				event_uid = event.vevent.uid.value
				if cal_uid == "system":
					cal_uid = "system-calendar"
				event_uid = cal_uid + ":" + event_uid
				title = event.vevent.summary.value
				due = event.vevent.dtstart.value
				if int(due.strftime("%Y%m%d")) < int(EV_BEGIN) or \
						int(due.strftime("%Y%m%d")) > int(EV_END):
					continue
				if isinstance(due, datetime.datetime):
					due = due.strftime("%A %d %B %Y %I:%M %p")
				else:
					due = due.strftime("%A %d %B %Y")
					
				if 'location' in event.vevent.contents:
					loc = event.vevent.location.value
				else:
					loc = None
				event_dict[event_uid] = {"name": title, "due": due, "loc": loc}
				
	return event_dict
	
	
def _get_web_events(web_calendar_uids):
	event_dict = {}	
	for cal_uid in web_calendar_uids:
		cache_db = os.path.join(EDS_CAL_WEB_PATH, cal_uid + "/cache.db" )
		with closing(sqlite3.connect(cache_db, timeout=1)) as conn:
			c = conn.cursor()
			c.execute("""SELECT ECacheObjects.occur_start
                 		FROM ECacheObjects
                 		WHERE occur_start IS NOT NULL
                 		LIMIT 1""")
                 
			record = c.fetchone()
			if record:
				has_occur_start = True
			else:
				has_occur_start = False
				
			if has_occur_start:	
				with closing(sqlite3.connect(cache_db, timeout=1)) as conn:
					c = conn.cursor()
					c.execute("""SELECT ECacheUID, summary, 
								 occur_start, location
								 FROM ECacheObjects
								 WHERE occur_start BETWEEN ? AND ?
								 ORDER BY occur_start DESC
								 LIMIT ?""",
								 (EV_BEGIN, EV_END, MAX_ITEMS, ))
					 
					for event_uid, title, due, loc in c:
						event_uid = cal_uid + ":" + event_uid
						title = title.title()
						if due[8:] == "000000":
							due = datetime.datetime.strptime(due[8:], "%Y%m%d")
							due = utc2local(due)
							due = due.strftime("%A %d %B %Y")
						else:
							due = datetime.datetime.strptime(due, "%Y%m%d%H%M%S")
							due = utc2local(due)
							due = due.strftime("%A %d %B %Y %I:%M %p")
						if loc:
							loc = loc.title()
						event_dict[event_uid] = {"name": title, "due": due, "loc": loc}
						
			else:
				with closing(sqlite3.connect(cache_db, timeout=1)) as conn:
					c = conn.cursor()
					c.execute("""SELECT ECacheUID, summary, 
								 ECacheObj, location
								 FROM ECacheObjects
								 LIMIT 15""")
					for event_uid, title, icalstream, loc in c:
						event_uid = cal_uid + ":" + event_uid
						title = title.title()
						event = vobject.readOne(icalstream)
						#print (event.contents)
						due = event.dtstart.value
						if int(due.strftime("%Y%m%d")) < int(EV_BEGIN) or \
								int(due.strftime("%Y%m%d")) > int(EV_END):
							continue
						
						if isinstance(due, datetime.datetime):
							due = due.strftime("%A %d %B %Y %I:%M %p")
						else:
							due = due.strftime("%A %d %B %Y")
							
						if loc:
							loc = loc.title()
						event_dict[event_uid] = {"name": title, "due": due, "loc": loc}
					 	
	return event_dict


    
def check_item_activated_callback(menuitem, a, b):#main menu item
    spawn_async(("gnome-calendar", "-u", b))

    
    
def add_item_to_qlist(ql, item, name, uid, due, launcher):
	y = str((now.year))
	if "AM" in due or "PM" in due:
		d = datetime.datetime.strptime(due[:-9], "%A %d %B %Y")
		d1 = datetime.datetime.strptime(due, "%A %d %B %Y %I:%M %p")
		name = name + " @ " + due[-8:] 
		if now < d1:
			add_event = True
		else:
			add_event = False
	else:
		d = datetime.datetime.strptime(due, "%A %d %B %Y")
		add_event = True
    
	d = d.date()
	t = datetime.datetime.today()
	t = t.date()
	
	if t == d and add_event:
		print ("adding {} to quicklist".format(name))
		item = Dbusmenu.Menuitem.new ()
		item.property_set (Dbusmenu.MENUITEM_PROP_LABEL, name)
		item.property_set_bool (Dbusmenu.MENUITEM_PROP_VISIBLE, True)
		item.connect ("item-activated", check_item_activated_callback, uid)
		ql.child_append (item)
		#launcher.set_property("quicklist", ql)
	else:
		pass        

def update_alarm_disc(alarm_disc, event_uid, title, due):
	#due = due.split(" IST.")[0]
	d = datetime.datetime.strptime(due, "%A %d %B %Y %I:%M %p")
	d_stamp = d.strftime("%s")
	t = (int(d_stamp) * 1000 * 1000)
	_d = d.strftime("%-I:%M %p")
	d_timer = (d - datetime.timedelta(minutes = 15))

	if now < d:
		if event_uid not in alarm_disc:
			alarm_disc[event_uid] = {"alarm": True, "due": due, "title": title}
		else:
			if alarm_disc[event_uid]["due"] != due:
				alarm_disc[event_uid]["alarm"] = True
				alarm_disc[event_uid]["due"] = due
				alarm_disc[event_uid]["title"] = title

	#Only contain events from current month after current time
	alarm_disc1 = alarm_disc.copy() 
	for event_uid, alarmd in alarm_disc.items():
		alarm_due = alarm_disc[event_uid]["due"]
		alarm_notify = alarm_disc[event_uid]["alarm"]
		ad = datetime.datetime.strptime(due, "%A %d %B %Y %I:%M %p")
		if (now > ad and not alarm_notify) or \
				int(ad.strftime("%Y%m%d")) > int(EV_END):
			alarm_disc1.pop(event_uid)
		          
	save_to_json(alarm_disc1,
		    os.path.join(EDS_ALARMS_PATH, "alarms.json"))
		    
	return alarm_disc1   





def _load_events():
	#global ql
	# Quicklist integration
	alarm_disc = load_from_json(os.path.join(EDS_ALARMS_PATH, "alarms.json"))
	#launcher = Unity.LauncherEntry.get_for_desktop_id ("org.gnome.Calendar.desktop")
	ql_old =  launcher.get_property("quicklist")
	if ql_old:
		#for c in ql_old.get_children():
			#ql_old.child_delete(c)
		ql_old = None
		launcher.set_property("quicklist", None)
		ql = Dbusmenu.Menuitem.new ()
	else:
		pretty.print_debug(__name__, "ql is not defined yet")    
		ql = Dbusmenu.Menuitem.new ()    
    
	''' Get all visible events from all active eds calendars '''
	cal_dict = _load_calendars()
	local_calendar_uids = []
	web_calendar_uids = []
	for cal_uid in cal_dict:
		if cal_dict[cal_uid]["stub"] == "local-stub":
			local_calendar_uids += [cal_uid]		
		else:
			web_calendar_uids += [cal_uid]
			
	if local_calendar_uids:
		event_dict_local = 	_get_local_events(local_calendar_uids)
	if web_calendar_uids:
		event_dict_web = _get_web_events(web_calendar_uids)
		
	if not web_calendar_uids:
		#eds always gives at least one local calendar by default.
		event_dict = event_dict_local.copy()
	else:
		event_dict = event_dict_local.copy()
		event_dict.update(event_dict_web)
	#print (event_dict)
	for event_uid, event_obj in event_dict.items():
		d_keys = list(event_dict.keys())
		item = "item" + str((d_keys.index(event_uid)))
		title = event_obj['name']
		due = event_obj['due']
		loc = event_obj['loc']
        
		add_item_to_qlist(ql, item, title, event_uid, due, launcher)
		launcher.set_property("quicklist", ql)

		if "AM" in due or "PM" in due:
			alarm_disc = update_alarm_disc(alarm_disc, event_uid, title, due)            

		if loc:
			due = due + ", " + loc #we intend to location on leaf description
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
		cld = _load_calendars()
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
			#path = list(self.get_path())
			self.monitor_token = self.monitor_directories(*eds_cache)

		bus = dbus.SessionBus()
		dbus_signal_connect_weakly(bus, "objects_modified", self._on_events_updated,
									dbus_interface="org.gnome.evolution.dataserver.CalendarView")

	def monitor_include_file(self, gfile):
		return gfile and (gfile.get_basename().endswith('.ics') \
		        or (gfile.get_basename().endswith('.db') \
		        or gfile.get_basename() == 'calendar.ics') \
		        or gfile.get_basename() == 'cache.db')

	def _on_events_updated (self, name):
		#s = name[0]
		#s = (s[s.find("LAST-MODIFIED:")+len("LAST-MODIFIED:"):s.rfind("\nEND:VEVENT")])
		self.mark_for_update()
		#self.get_items()

	def get_items(self):
		#interface = _create_dbus_connection(SERVICE_NAME, OBJECT_NAME, IFACE_NAME, activate=True)
		self._event = list(_load_events())
		return self._event

	def get_icon_name(self):
		return 'calendar'

	def provides(self):
		yield Event


