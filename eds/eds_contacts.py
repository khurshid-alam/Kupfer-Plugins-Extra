# -*- encoding: UTF-8 -*-
__kupfer_name__ = _("Gnome Contacts")
__kupfer_sources__ = ("GnomeContactsSource", )
__kupfer_actions__ = ("NewMailAction", )
__description__ = _("Search and open contact with Gnome-Contacts")
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
from xml.dom import minidom
gi.require_version('Gtk', '3.0')

from kupfer import plugin_support
from kupfer import pretty, utils
from kupfer import textutils
from kupfer.objects import Leaf, Action, Source
from kupfer.objects import TextLeaf, NotAvailableError, AppLeaf
from kupfer.objects import UrlLeaf, RunnableLeaf, FileLeaf
from kupfer.obj.apps import AppLeafContentMixin
from kupfer.obj.grouping import ToplevelGroupingSource
from kupfer.obj.contacts import ContactLeaf, EmailContact, is_valid_email
from kupfer.obj.contacts import EMAIL_KEY, NAME_KEY
from kupfer.weaklib import dbus_signal_connect_weakly

plugin_support.check_dbus_connection()



Contact_ID = "org.gnome.Contacts"

#get Addressbook UIDs
EDS_ADB_PATH = (os.path.join(base.xdg_data_home, "evolution/addressbook"))
EDS_ADB_WEB_PATH = (os.path.join(base.xdg_cache_home, "evolution/addressbook"))
local_addressbook_uids = []
web_addressbook_uids = []
for dir in os.listdir(EDS_ADB_PATH):
    if dir != "trash":
        local_addressbook_uids += [dir]

local_addressbook_uids = [word.replace('system','system-address-book') for word in local_addressbook_uids]


for dir in os.listdir(EDS_ADB_WEB_PATH):
    if os.path.exists(EDS_ADB_WEB_PATH + "/" + dir + "/cache.xml"):
        WEB_ADB_EXISTS = True
        if dir != "trash":
            web_addressbook_uids += [dir]
            addressbook_uids = local_addressbook_uids + web_addressbook_uids

    else:
        WEB_ADB_EXISTS = False
        addressbook_uids = local_addressbook_uids
#print (addressbook_uids)

#get EDS_FACTORY_BUS
EDS_FACTORY_OBJ = "/org/gnome/evolution/dataserver/AddressBookFactory"
EDS_FACTORY_IFACE = "org.gnome.evolution.dataserver.AddressBookFactory"

EDS_SUBPROCESS_IFACE = "org.gnome.evolution.dataserver.AddressBook"
INDIVIDUAL_ID_KEY = "CID"
CONTACT_NAME = "CONTACT_NAME"
CONTACT_EMAILS = "CONTACT_EMAILS"


def _search_bus_name(SERVICE_NAME_FILTER, activate=False):

    interface = None
    obj = None
    sbus = dbus.SessionBus()

    try:
        #check for running pidgin (code from note.py)
        proxy_obj = sbus.get_object('org.freedesktop.DBus', '/org/freedesktop/DBus')
        dbus_iface = dbus.Interface(proxy_obj, 'org.freedesktop.DBus')
        bus_names = dbus_iface.ListActivatableNames()
        eds_adb = list(filter(lambda x:SERVICE_NAME_FILTER in x, bus_names))
        if eds_adb:
            EDS_FACTORY_BUS = eds_adb[0]
    except dbus.exceptions.DBusException as err:
        pretty.print_debug(__name__, err)
    return EDS_FACTORY_BUS
                
EDS_FACTORY_BUS = _search_bus_name("org.gnome.evolution.dataserver.AddressBook")



def _create_dbus_connection(SERVICE_NAME, OBJECT_NAME, IFACE_NAME, activate=False):
    ''' Create dbus connection to EDS Addressbook
    @activate: true=starts EDS Addressbook if not running
    usually eds addressbook subprocesses starts at boot and keep 
    running in the background
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


class ComposeMail(RunnableLeaf):
    ''' Create new mail without recipient '''
    def __init__(self):
        RunnableLeaf.__init__(self, name=_("Compose New Email"))

    def run(self):
        utils.spawn_async_notify_as("evolution.desktop",
                                   ['xdg-open', 'mailto:'])

    def get_description(self):
        return _("Compose a new message in Evolution")

    def get_icon_name(self):
        return "mail-message-new"




#Hack to get online contact ids like google, carddav etc.
def _get_web_contacts_ids(addressbook_uid):
    xmldoc = minidom.parse(EDS_ADB_WEB_PATH + "/" + addressbook_uid + "/cache.xml")    
    itemlist = xmldoc.getElementsByTagName('object')
    contact_pass_ids = []
    for s in itemlist:
        if s.attributes['uid'].value.startswith("http://"):
            contact_pass_ids += [s.attributes['uid'].value]

    return contact_pass_ids





def _load_contacts(addressbook_uids):
    ''' Get service & ifcace name for each addressbooks and then load all contacts '''
    for addressbook_uid in addressbook_uids:
        iface = _create_dbus_connection(EDS_FACTORY_BUS, EDS_FACTORY_OBJ, EDS_FACTORY_IFACE, activate=True)
        EDS_SUBPROCESS_OBJ, EDS_SUBPROCESS_BUS  = iface.OpenAddressBook(addressbook_uid)
        interface = _create_dbus_connection(EDS_SUBPROCESS_BUS, EDS_SUBPROCESS_OBJ, EDS_SUBPROCESS_IFACE)
        interface.Open() #otherwise it may fail

        if os.path.exists(EDS_ADB_WEB_PATH + "/" + addressbook_uid + "/cache.xml"):
            contact_pass_ids =  _get_web_contacts_ids(addressbook_uid)   
        else:    
            contact_pass_ids = interface.GetContactListUids("")
        for contact_pass_id in contact_pass_ids:
            #Lets form contact_uid from pass_id
            if 'http://' in contact_pass_id:        
                contact_uid = "eds:" + addressbook_uid + ":" + contact_pass_id.replace(":", "\\:")
            else:
                contact_uid = "eds:" + addressbook_uid + ":" + contact_pass_id
            #We also know individual id is just sha1 hash of uid, so
            m = hashlib.sha1()
            m.update(contact_uid.encode('UTF-8'))
            contact_individual_id = str(m.hexdigest())

            #we get contact vcard and parse it using python3-vobject
            contact_vcard = interface.GetContact(contact_pass_id)
            vcard = vobject.readOne( contact_vcard )
            if 'email' in vcard.contents:
                emails = [email.value for email in vcard.contents['email']]
            else:
                emails = [""]
            if 'tel' in vcard.contents:
                telephones = [tel.value for tel in vcard.contents['tel']]
            else:
                telephones = [""]
            cobj = {"EMAIL": emails, "TEL": telephones}

            if "fn" in vcard.contents:
                full_name = vcard.fn.value
            elif "n" in vcard.contents:
                name_given = vcard.n.value.given
                name_family = vcard.n.value.family
                full_name = name_given + name_family
            else:
                continue

            if full_name == "":
                continue

            ocontact = GnomeContact(contact_individual_id, full_name, cobj)
            yield ocontact
            yield ComposeMail()




def spawn_async(argv):
    try:
        utils.spawn_async_raise(argv)
    except utils.SpawnError as exc:
        raise OperationError(exc)



class OpenContact (Action):
    rank_adjust = 1
    action_accelerator = "o"

    def __init__(self):
        Action.__init__(self, _("Open"))

    def activate(self, leaf):
        #interface = _create_dbus_connection(True)
        spawn_async(("gnome-contacts", "-i", leaf.cid))

    def get_icon_name(self):
        return 'x-office-address-book'

    def get_description(self):
        return _("Open contact in Gnome Contact")


class NewMailAction(Action):
    action_accelerator = "n"

    ''' Create new mail to selected leaf'''
    def __init__(self):
        Action.__init__(self, _('Compose Email'))

    #def activate(self, leaf):
        #self.activate_multiple((leaf, ))

    def activate(self, leaf):
        print(leaf.telephones)
        if len(leaf.emails) > 1:
            ems = leaf.emails
            eids = ",".join(e for e in ems)
            spawn_async(["xdg-open", "mailto:%s" % eids])
        else:
            spawn_async(["xdg-open", "mailto:%s" % leaf.emails[0]])

    def valid_for_item(self, item):
        return bool(is_valid_email(item.emails[0]) and item.emails[0])

    def get_icon_name(self):
        return "mail-message-new"

    def item_types(self):
        yield ContactLeaf
        # we can enter email
        #yield TextLeaf
        #yield UrlLeaf



class GnomeContact (Leaf):
    def __init__(self, contact_individual_id, full_name, cobj):
        Leaf.__init__(self, contact_individual_id, full_name)
        self.cid = contact_individual_id
        self.name = full_name
        self.cobj = cobj
        self.emails = cobj['EMAIL']
        self.telephones = cobj['TEL']

    def get_description(self):
        descr = []
        if self.telephones:
            descr.append("Telephones: %s" % self.telephones[0])
        else:
            descr.append("This contact doesn't have any telephone no")
        '''
        if self.emails:
            if len(self.emails) > 1:
                eid = ",".join(e for e in self.emails)
                descr.append("Emails: %s" % eid)
            else:
                descr.append("Emails: %s" % self.emails[0])
        '''
        return "  ".join(descr)

    def get_icon_name(self):
        return 'evolution'

    def get_actions(self):
        yield OpenContact()
        yield NewMailAction()



class GnomeContactsSource (AppLeafContentMixin, ToplevelGroupingSource, Source):
    appleaf_content_id = Contact_ID

    def __init__(self, name=None):
        ToplevelGroupingSource.__init__(self, name, _("GnomeContacts"))
        self._gnomecontacts = []
        self._version = 3

    def initialize(self):
        ToplevelGroupingSource.initialize(self)


    def get_items(self):
        self._gnomecontacts = list(_load_contacts(addressbook_uids))
        return self._gnomecontacts

    def get_icon_name(self):
        return 'evolution'

    def provides(self):
        yield GnomeContact
        yield RunnableLeaf
