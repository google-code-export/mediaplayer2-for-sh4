from Screens.Screen import Screen
from Screens.HelpMenu import HelpableScreen
from Screens.LocationBox import LocationBox
from Components.Label import Label
from Components.FileList import FileList
from Components.config import config, getConfigListEntry, ConfigSubsection, configfile, ConfigText, ConfigYesNo, ConfigDirectory
from Components.ConfigList import ConfigListScreen
from Components.ActionMap import ActionMap
from Plugins.Extensions.MediaPlayer2 import _

config.plugins.mediaplayer2 = ConfigSubsection()
config.plugins.mediaplayer2.repeat = ConfigYesNo(default=False)
config.plugins.mediaplayer2.savePlaylistOnExit = ConfigYesNo(default=True)
config.plugins.mediaplayer2.askOnExit = ConfigYesNo(default=True)
config.plugins.mediaplayer2.saveDirOnExit = ConfigYesNo(default=False)
config.plugins.mediaplayer2.defaultDir = ConfigDirectory()
config.plugins.mediaplayer2.extensionsMenu = ConfigYesNo(default=False)
config.plugins.mediaplayer2.mainMenu = ConfigYesNo(default=False)

class MediaPlayerSettings(Screen, ConfigListScreen):

	def __init__(self, session, parent):
		from Components.Sources.StaticText import StaticText
		Screen.__init__(self, session)
		self.skin = """
			<screen name="MediaPlayerSettings" position="center,150" size="610,200" title="Edit settings">
			<ePixmap pixmap="skin_default/buttons/red.png" position="110,0" size="140,40" alphatest="on" />
			<ePixmap pixmap="skin_default/buttons/green.png" position="360,0" size="140,40" alphatest="on" />
			<widget source="key_red" render="Label" position="110,0" zPosition="1" size="140,40" font="Regular;20" halign="center" valign="center" backgroundColor="#9f1313" transparent="1" />
			<widget source="key_green" render="Label" position="360,0" zPosition="1" size="140,40" font="Regular;20" halign="center" valign="center" backgroundColor="#1f771f" transparent="1" />
			<widget name="config" position="10,44" size="590,146" />
			</screen>"""
		self["key_red"] = StaticText(_("Cancel"))
		self["key_green"] = StaticText(_("Save"))
		self.skinName = 'MediaPlayerSettings2'

		ConfigListScreen.__init__(self, [])
		self.parent = parent
		self.initConfigList()
		config.plugins.mediaplayer2.saveDirOnExit.addNotifier(self.initConfigList)

		self["setupActions"] = ActionMap(["SetupActions", "ColorActions"],
		{
		    "green": self.save,
		    "red": self.cancel,
		    "cancel": self.cancel,
		    "ok": self.ok,
		}, -2)

	def initConfigList(self, element=None):
		print "[initConfigList]", element
		try:
			self.list = []
			self.list.append(getConfigListEntry(_("repeat playlist"), config.plugins.mediaplayer2.repeat))
			self.list.append(getConfigListEntry(_("save playlist on exit"), config.plugins.mediaplayer2.savePlaylistOnExit))
			self.list.append(getConfigListEntry(_("ask on exit"), config.plugins.mediaplayer2.askOnExit))
			self.list.append(getConfigListEntry(_("save last directory on exit"), config.plugins.mediaplayer2.saveDirOnExit))
			self.list.append(getConfigListEntry(_("show in extensions menu"), config.plugins.mediaplayer2.extensionsMenu))
			self.list.append(getConfigListEntry(_("replace default MediaPlayer in main menu"), config.plugins.mediaplayer2.mainMenu))
			if not config.plugins.mediaplayer2.saveDirOnExit.getValue():
				self.list.append(getConfigListEntry(_("start directory"), config.plugins.mediaplayer2.defaultDir))
			self["config"].setList(self.list)
		except KeyError:
			print "keyError"

	def changedConfigList(self):
		self.initConfigList()

	def ok(self):
		if self["config"].getCurrent()[1] == config.plugins.mediaplayer2.defaultDir:
			self.session.openWithCallback(self.LocationBoxClosed, LocationBox, _("Please select the path for the Startdirectory"), currDir=self.parent.filelist.getCurrentDirectory(), bookmarks=config.movielist.videodirs)

	def LocationBoxClosed(self, path):
		print "PathBrowserClosed:", path
		if path is not None:
			config.plugins.mediaplayer2.defaultDir.setValue(path)

	def save(self):
		for x in self["config"].list:
			x[1].save()
		self.close()

	def cancel(self):
		self.close()

