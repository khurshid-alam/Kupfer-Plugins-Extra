# vim: set noexpandtab ts=8 sw=8:

__kupfer_name__ = _("Sudo")
__kupfer_actions__ = (
		"OpenAsRoot",
	)
__description__ = _("Open selection with root privileges")
__version__ = ""
__author__ = "Jakh Daven <tuxcanfly@gmail.com>"

from kupfer.objects import Action, Leaf, FileLeaf, AppLeaf
from kupfer import pretty, plugin_support, utils
from kupfer.obj.fileactions import Open

__kupfer_settings__ = plugin_support.PluginSettings(
	{
		"key" : "sudo_command",
		"label": _("Sudo Command"),
		"type": str,
		"value": "gksudo",
		"alternatives": ("kdesudo", )
	},
)

class OpenAsRoot (Open):
	rank_adjust = -20
	action_accelerator = "r"
	def __init__(self):
		Action.__init__(self, _("Open as root"))

	def activate(self, leaf, ctx=None):
		if type(leaf) == AppLeaf:
		    cmd = "%s %s" %(__kupfer_settings__["sudo_command"],
				leaf.object.get_commandline())
		    ret = utils.launch_commandline(cmd)
		    if ret: return ret
		    pretty.print_error(__name__, "Unable to run command(s)", cmd)
		elif type(leaf) == FileLeaf:
			self.activate_multiple((leaf,), ctx)

	def activate_multiple(self, objects, ctx):
		appmap = {}
		leafmap = {}
		for iobj_app in objects:
			if type(iobj_app) == AppLeaf:
			    self.activate(iobj_app)
			elif type(iobj_app) == FileLeaf:
				app = self.default_application_for_leaf(iobj_app)
				id_ = app.get_id()
				appmap[id_] = app
				leafmap.setdefault(id_, []).append(iobj_app)

		for id_, leaves in leafmap.items():
			app = appmap[id_]
			# commandline usually involves %U and we don't want that
			commandline = app.get_commandline()
			if "%" in commandline:
				commandline, subst = commandline.split (" %")
				
			cmd = "%s %s " %(__kupfer_settings__["sudo_command"],
					commandline)
			for l in leaves:
				cmd += "%s " %l.object
			ret = utils.launch_commandline(cmd)
			if ret: return ret
			pretty.print_error(__name__, "Unable to run command(s)", cmd)

	def item_types(self):
		yield Leaf
	def get_description(self):
		return _("Open with root privileges")

