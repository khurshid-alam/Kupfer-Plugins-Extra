# -*- coding: UTF-8 -*-
__kupfer_name__ = _("SFTP Hosts")
__description__ = _("Adds the SFTP hosts found in ~/config/nautilus/servers.")
__version__ = "2017-04-12"
__author__ = "Khurshid Alam"

__kupfer_sources__ = ("SFTPSource", )
__kupfer_actions__ = ("SFTPConnect", "SSHConnect", )

import os
import lxml.etree as xml
from urllib.parse import urlparse

from kupfer import icons, utils
from kupfer.objects import Action
from kupfer.obj.helplib import FilesystemWatchMixin
from kupfer.obj.grouping import ToplevelGroupingSource
from kupfer.obj.hosts import HOST_NAME_KEY, HostLeaf, HOST_SERVICE_NAME_KEY, \
        HOST_ADDRESS_KEY



class SFTPLeaf (HostLeaf):
    """The SFTP host. It only stores the "Host" as it was
    specified in the nautilus server config.
    """
    def __init__(self, addr, name):
        slots = {HOST_NAME_KEY: name, HOST_ADDRESS_KEY: addr,
                HOST_SERVICE_NAME_KEY: "sftp"}
        HostLeaf.__init__(self, slots, name)

    def get_description(self):
        return _("SFTP host")

    def get_gicon(self):
        return icons.ComposedIconSmall(self.get_icon_name(), "applications-internet")


class SSHConnect (Action):
    """Used to launch a terminal connecting to the specified
    SSH host.
    """
    def __init__(self):
        Action.__init__(self, name=_("Connect"))

    def activate(self, leaf):
        utils.spawn_in_terminal(["ssh", leaf[HOST_ADDRESS_KEY]])

    def get_description(self):
        return _("Connect to SSH host")

    def get_icon_name(self):
        return "network-server"

    def item_types(self):
        yield HostLeaf

    def valid_for_item(self, item):
        if item.check_key(HOST_SERVICE_NAME_KEY):
            return item[HOST_SERVICE_NAME_KEY] == 'sftp'
        return False


class SFTPConnect (Action):
    """Browse remote server with specified
    SFTP host.
    """
    def __init__(self):
        Action.__init__(self, name=_("Browse Remote Server"))

    def activate(self, leaf):
        utils.show_url(leaf[HOST_ADDRESS_KEY])

    def get_description(self):
        return _("Connect to SFTP host")

    def get_icon_name(self):
        return "network-server"

    def item_types(self):
        yield HostLeaf

    def valid_for_item(self, item):
        if item.check_key(HOST_SERVICE_NAME_KEY):
            return item[HOST_SERVICE_NAME_KEY] == 'sftp'
        return False



class SFTPSource (ToplevelGroupingSource, FilesystemWatchMixin):
    """Reads ~/.config/nautilus/servers and creates leaves for the hosts found.
    """
    _SFTP_home = os.path.expanduser("~/.config/nautilus")
    _SFTP_config_file = "servers"
    _config_path = os.path.join(_SFTP_home, _SFTP_config_file)

    def __init__(self, name=_("SFTP Hosts")):
        ToplevelGroupingSource.__init__(self, name, "hosts")
        self._version = 3

    def initialize(self):
        ToplevelGroupingSource.initialize(self)
        self.monitor_token = self.monitor_directories(self._SFTP_home)

    def monitor_include_file(self, gfile):
        return gfile and gfile.get_basename() == self._SFTP_config_file

    def get_items(self):
        try:
            root = xml.parse(note_path).getroot()
            for bookmark in root.findall('bookmark'):
                host_addr = bookmark.attrib['href']
                host_name = urlparse(host_addr).hostname
                yield SFTPLeaf(host_addr, host_name)
        except EnvironmentError as exc:
            self.output_error(exc)
        except UnicodeError as exc:
            self.output_error("File %s not in expected encoding (UTF-8)" %
                    self._config_path)
            self.output_error(exc)

    def get_description(self):
        return _("SFTP hosts as specified in ~/.config/nautilus/servers")

    def get_icon_name(self):
        return "applications-internet"

    def provides(self):
        yield SFTPLeaf

