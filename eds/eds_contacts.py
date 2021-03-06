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
gi.require_version('EBook', '1.2')

from gi.repository import EBook
from gi.repository import EDataServer, EBookContacts

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


#EDS SOURCES
registry = EDataServer.SourceRegistry.new_sync(None)
esources = EDataServer.SourceRegistry.list_enabled(registry, 
                        EDataServer.SOURCE_EXTENSION_ADDRESS_BOOK)


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




def _get_contact_pass_ids(esource):
    ebc = EBook.BookClient.connect_sync(esource, 5, None)
    q = EBookContacts.BookQuery.vcard_field_exists("N")
    qr = q.to_string()
    ret, contact_pass_ids = ebc.get_contacts_uids_sync(qr, None)
    if ret:
        return contact_pass_ids
    else:
        return None




def _load_contacts(esources):
    ''' Get service & ifcace name for each addressbooks and then load all contacts '''
    for esource in esources:
        adb_name = esource.get_display_name()
        addressbook_uid = esource.get_uid()
        if adb_name == "friends-twitter-contacts":
            continue
        
        contact_pass_ids = _get_contact_pass_ids(esource)
        
        if contact_pass_ids is None:
            continue

        iface = _create_dbus_connection(EDS_FACTORY_BUS, EDS_FACTORY_OBJ, EDS_FACTORY_IFACE, activate=True)
        EDS_SUBPROCESS_OBJ, EDS_SUBPROCESS_BUS  = iface.OpenAddressBook(addressbook_uid)
        interface = _create_dbus_connection(EDS_SUBPROCESS_BUS, EDS_SUBPROCESS_OBJ, EDS_SUBPROCESS_IFACE)
        interface.Open() #otherwise it may fail

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
            try:
                contact_vcard = interface.GetContact(contact_pass_id)
            except:
                print ("Couldn't load contact..skipping {}".format(contact_pass_id))
                
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

    def activate(self, leaf, email_leaf=None):
        print(leaf.telephones)
        if email_leaf:
            email = email_leaf.object
            spawn_async(["xdg-open", "mailto:%s" % email])

    def valid_for_item(self, leaf):
        print (leaf.emails[0])
        return bool(is_valid_email(leaf.emails[0]) and leaf.emails[0])

    def get_icon_name(self):
        return "mail-message-new"

    def item_types(self):
        yield ContactLeaf
        # we can enter email
        #yield TextLeaf
        #yield UrlLeaf

    def requires_object(self):
        return True

    def object_source(self, for_item=None):
        if for_item:
            return EmailSource(for_item)

    def object_types(self, for_item=None):
        yield TextLeaf



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



class EmailSource(Source):
    def __init__(self, leaf):
        Source.__init__(self, _("Emails"))
        self.ems = leaf.emails

    def item_types(self):
        yield TextLeaf

    def get_items(self):
        for e in self.ems:
            yield TextLeaf(e)




class GnomeContactsSource (AppLeafContentMixin, ToplevelGroupingSource, Source):
    appleaf_content_id = Contact_ID

    def __init__(self, name=None):
        ToplevelGroupingSource.__init__(self, name, _("GnomeContacts"))
        self._gnomecontacts = []
        self._version = 3

    def initialize(self):
        ToplevelGroupingSource.initialize(self)


    def get_items(self):
        self._gnomecontacts = list(_load_contacts(esources))
        return self._gnomecontacts

    def get_icon_name(self):
        return 'evolution'

    def provides(self):
        yield GnomeContact
        yield RunnableLeaf
