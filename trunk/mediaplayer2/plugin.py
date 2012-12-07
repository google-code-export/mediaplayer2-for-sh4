from os import path as os_path, remove as os_remove, listdir as os_listdir
from time import strftime
from enigma import iPlayableService, eTimer, eServiceCenter, iServiceInformation, ePicLoad, eAVSwitch
from ServiceReference import ServiceReference
from Screens.Screen import Screen
from Screens.HelpMenu import HelpableScreen
from Screens.MessageBox import MessageBox
from Screens.InputBox import InputBox
from Screens.ChoiceBox import ChoiceBox
from Screens.InfoBarGenerics import InfoBarSeek, InfoBarAudioSelection, InfoBarCueSheetSupport, InfoBarNotifications, \
	InfoBarShowHide, InfoBarServiceErrorPopupSupport, \
	InfoBarPVRState, InfoBarSimpleEventView, InfoBarServiceNotifications, \
	InfoBarMoviePlayerSummarySupport, InfoBarSubtitleSupport, InfoBarTeletextPlugin
from Screens.LocationBox import LocationBox
from Components.ActionMap import NumberActionMap, HelpableActionMap
from Components.Label import Label
from Components.Pixmap import Pixmap, MultiPixmap
from Components.FileList import FileList
from Components.MediaPlayer import PlayList
from Components.ServicePosition import ServicePositionGauge
from Components.ServiceEventTracker import ServiceEventTracker, InfoBarBase
from Components.Playlist import PlaylistIOInternal, PlaylistIOM3U, PlaylistIOPLS
from Components.AVSwitch import AVSwitch
from Components.Harddisk import harddiskmanager
from Components.config import config
from Tools.Directories import fileExists, pathExists, resolveFilename, SCOPE_CONFIG, SCOPE_PLAYLIST, SCOPE_SKIN_IMAGE
from settings import MediaPlayerSettings
from Plugins.Extensions.MediaPlayer2 import _
from Plugins.SystemPlugins.Hotplug.plugin import hotplugNotifier
try:
	from Plugins.Extensions.CSFD.plugin import CSFD
	print "CSFD plugin import OK"
except ImportError:
	print "CSFD None"
	CSFD = None
from subtitles.subtitles import SubsSupport
import os
import random

aspectratiomode = "1"

class MyPlayList(PlayList):
	def __init__(self):
		PlayList.__init__(self)

	def PlayListShuffle(self):
		random.shuffle(self.list)
		self.l.setList(self.list)
		self.currPlaying = -1
		self.oldCurrPlaying = -1

class MediaPixmap(Pixmap):
	def __init__(self):
		Pixmap.__init__(self)
		self.coverArtFileName = ""
		self.picload = ePicLoad()
		self.picload.PictureData.get().append(self.paintCoverArtPixmapCB)
		self.coverFileNames = ["folder.png", "folder.jpg"]

	def applySkin(self, desktop, screen):
		from Tools.LoadPixmap import LoadPixmap
		noCoverFile = None
		if self.skinAttributes is not None:
			for (attrib, value) in self.skinAttributes:
				if attrib == "pixmap":
					noCoverFile = value
					break
		if noCoverFile is None:
			noCoverFile = resolveFilename(SCOPE_SKIN_IMAGE, "skin_default/no_coverArt.png")
		self.noCoverPixmap = LoadPixmap(noCoverFile)
		return Pixmap.applySkin(self, desktop, screen)

	def onShow(self):
		Pixmap.onShow(self)
		sc = AVSwitch().getFramebufferScale()
		#0=Width 1=Height 2=Aspect 3=use_cache 4=resize_type 5=Background(#AARRGGBB)
		self.picload.setPara((self.instance.size().width(), self.instance.size().height(), sc[0], sc[1], False, 1, "#00000000"))

	def paintCoverArtPixmapCB(self, picInfo=None):
		ptr = self.picload.getData()
		if ptr != None:
			self.instance.setPixmap(ptr.__deref__())

	def updateCoverArt(self, path):
		while not path.endswith("/"):
			path = path[:-1]
		new_coverArtFileName = None
		for filename in self.coverFileNames:
			if fileExists(path + filename):
				new_coverArtFileName = path + filename
		if self.coverArtFileName != new_coverArtFileName:
			self.coverArtFileName = new_coverArtFileName
			if new_coverArtFileName:
				self.picload.startDecode(self.coverArtFileName)
			else:
				self.showDefaultCover()

	def showDefaultCover(self):
		self.instance.setPixmap(self.noCoverPixmap)

	def embeddedCoverArt(self):
		print "[embeddedCoverArt] found"
		self.coverArtFileName = "/tmp/.id3coverart"
		self.picload.startDecode(self.coverArtFileName)

class MediaPlayer(Screen, InfoBarBase, InfoBarSeek, InfoBarAudioSelection, InfoBarNotifications, HelpableScreen):
	ALLOW_SUSPEND = True

	def __init__(self, session, args=None):
		Screen.__init__(self, session)
		InfoBarAudioSelection.__init__(self)
		InfoBarNotifications.__init__(self)
		InfoBarBase.__init__(self)
		HelpableScreen.__init__(self)
		self.summary = None
		self.oldService = self.session.nav.getCurrentlyPlayingServiceReference()
		self.session.nav.stopService()

		self.playlistparsers = {}
		self.addPlaylistParser(PlaylistIOM3U, "m3u")
		self.addPlaylistParser(PlaylistIOPLS, "pls")
		self.addPlaylistParser(PlaylistIOInternal, "e2pls")
		self.title = 'MediaPlayer2'
		# 'None' is magic to start at the list of mountpoints
		defaultDir = config.plugins.mediaplayer2.defaultDir.getValue()
		self.filelist = FileList(defaultDir, matchingPattern="(?i)^.*\.(mp2|mp3|ogg|ts|wav|wave|m3u|pls|e2pls|mpg|vob|m2ts|avi|divx|mkv|mp4|m4a|dat|flac|rec)", useServiceRef=True, additionalExtensions="4098:m3u 4098:e2pls 4098:pls")
		self["filelist"] = self.filelist

		self.playlist = MyPlayList()
		self.is_closing = False
		self.MoviePlayerOpen = False
		self.delname = ""
		self["playlist"] = self.playlist

		self["PositionGauge"] = ServicePositionGauge(self.session.nav)

		self["currenttext"] = Label("")

		self["artisttext"] = Label(_("Artist") + ':')
		self["artist"] = Label("")
		self["titletext"] = Label(_("Title") + ':')
		self["title"] = Label("")
		self["albumtext"] = Label(_("Album") + ':')
		self["album"] = Label("")
		self["yeartext"] = Label(_("Year") + ':')
		self["year"] = Label("")
		self["genretext"] = Label(_("Genre") + ':')
		self["genre"] = Label("")
		self["coverArt"] = MediaPixmap()
		self["repeat"] = MultiPixmap()

		self.seek_target = None
		hotplugNotifier.append(self.hotplugCB)

		class MoviePlayerActionMap(NumberActionMap):
			def __init__(self, player, contexts=[ ], actions={ }, prio=0):
				NumberActionMap.__init__(self, contexts, actions, prio)
				self.player = player

			def action(self, contexts, action):
				self.player.show()
				return NumberActionMap.action(self, contexts, action)


		self["OkCancelActions"] = HelpableActionMap(self, "OkCancelActions",
			{
				"ok": (self.ok, _("add file to playlist")),
				"cancel": (self.exit, _("exit mediaplayer")),
			}, -2)

		self["MediaPlayerActions"] = HelpableActionMap(self, "MediaPlayerActions",
			{	
				"csfd": (self.csfd, _("show csfd info")),
				"play": (self.xplayEntry, _("play entry")),
				"pause": (self.pauseEntry, _("pause")),
				"stop": (self.stopEntry, _("stop entry")),
				"previous": (self.previousEntry, _("play from previous playlist entry")),
				"next": (self.nextEntry, _("play from next playlist entry")),
				"menu": (self.showMenu, _("menu")),
				"skipListbegin": (self.skip_listbegin, _("jump to listbegin")),
				"skipListend": (self.skip_listend, _("jump to listend")),
				"prevBouquet": (self.switchToPlayList, _("switch to playlist")),
				"nextBouquet": (self.switchToFileList, _("switch to filelist")),
				"delete": (self.deletePlaylistEntry, _("delete playlist entry")),
				"shift_stop": (self.clear_playlist, _("clear playlist")),
				"shift_record": (self.playlist.PlayListShuffle, _("shuffle playlist")),
			}, -2)

		self["InfobarEPGActions"] = HelpableActionMap(self, "InfobarEPGActions",
			{
				"showEventInfo": (self.showEventInformation, _("show event details")),
			})

		self["actions"] = MoviePlayerActionMap(self, ["DirectionActions"],
		{
			"right": self.rightDown,
			"rightRepeated": self.doNothing,
			"rightUp": self.rightUp,
			"left": self.leftDown,
			"leftRepeated": self.doNothing,
			"leftUp": self.leftUp,

			"up": self.up,
			"upRepeated": self.up,
			"upUp": self.doNothing,
			"down": self.down,
			"downRepeated": self.down,
			"downUp": self.doNothing,
		}, -2)

		InfoBarSeek.__init__(self, actionmap="MediaPlayerSeekActions")
		self.onShown.append(self.setWindowTitle)
		self.onClose.append(self.delMPTimer)
		self.onClose.append(self.__onClose)
		

		self.righttimer = False
		self.rightKeyTimer = eTimer()
		self.rightKeyTimer.callback.append(self.rightTimerFire)

		self.lefttimer = False
		self.leftKeyTimer = eTimer()
		self.leftKeyTimer.callback.append(self.leftTimerFire)

		self.currList = "filelist"
		self.isAudioCD = False
		self.AudioCD_albuminfo = {}
		self.savePlaylistOnExit = False
		self.cdAudioTrackFiles = []
		self.applySettings()
		self.bookmarks = config.movielist.videodirs

		self.playlistIOInternal = PlaylistIOInternal()
		list = self.playlistIOInternal.open(resolveFilename(SCOPE_CONFIG, "playlist.e2pls"))
		if list:
			for x in list:
				self.playlist.addFile(x.ref)
			self.playlist.updateList()

		self.__event_tracker = ServiceEventTracker(screen=self, eventmap=
			{
				iPlayableService.evUpdatedInfo: self.__evUpdatedInfo,
				iPlayableService.evUser + 10: self.__evAudioDecodeError,
				iPlayableService.evUser + 11: self.__evVideoDecodeError,
				iPlayableService.evUser + 12: self.__evPluginError,
				iPlayableService.evUser + 13: self["coverArt"].embeddedCoverArt
			})

	def doNothing(self):
		pass
	
	def setWindowTitle(self):
		self.setTitle(self.title)

	def createSummary(self):
		return MediaPlayerLCDScreen

	def exit(self):
		if self.savePlaylistOnExit and not config.plugins.mediaplayer2.savePlaylistOnExit.getValue():
			self.savePlaylistOnExit = False
		if config.plugins.mediaplayer2.askOnExit.getValue():
			if not self.savePlaylistOnExit:
				self.session.openWithCallback(self.exitCB, MessageBox, _("Do you really want to exit?"), timeout=5)
			else:
				list = []
				list.append((_("No"), "no"))
				list.append((_("Yes"), "yes"))
				self.session.openWithCallback(self.exitCBsave, ChoiceBox, title=_("save playlist before exit?"), list=list)
		else:
			self.exitCB(True)

	def exitCB(self, answer):
		if answer == True:
			self.playlistIOInternal.clear()
			if self.savePlaylistOnExit:
				print "save playlist"
				for x in self.playlist.list:
					self.playlistIOInternal.addService(ServiceReference(x[0]))
				self.playlistIOInternal.save(resolveFilename(SCOPE_CONFIG, "playlist.e2pls"))
			if config.plugins.mediaplayer2.saveDirOnExit.getValue():
				config.plugins.mediaplayer2.defaultDir.setValue(self.filelist.getCurrentDirectory())
				config.plugins.mediaplayer2.defaultDir.save()
			hotplugNotifier.remove(self.hotplugCB)
			del self["coverArt"].picload
			self.close()

	def exitCBsave(self, answer):
		if answer is not None:
			if answer[1] == "no":
				self.savePlaylistOnExit = False
			self.exitCB(True)

	def checkSkipShowHideLock(self):
		self.updatedSeekState()

	def doEofInternal(self, playing):
		print "--- eofint mediaplayer---"
		if playing:
			if not self.MoviePlayerOpen:
				self.nextEntry()
		else:
			self.show()

	def __onClose(self):
		self.session.nav.playService(self.oldService)

	def __evUpdatedInfo(self):
		currPlay = self.session.nav.getCurrentService()
		currenttitle = currPlay.info().getInfo(iServiceInformation.sCurrentTitle)
		totaltitles = currPlay.info().getInfo(iServiceInformation.sTotalTitles)
		sTagTitle = currPlay.info().getInfoString(iServiceInformation.sTagTitle)
		print "[__evUpdatedInfo] title %d of %d (%s)" % (currenttitle, totaltitles, sTagTitle)
		self.readTitleInformation()

	def __evAudioDecodeError(self):
		currPlay = self.session.nav.getCurrentService()
		sAudioType = currPlay.info().getInfoString(iServiceInformation.sUser + 10)
		print "[__evAudioDecodeError] audio-codec %s can't be decoded by hardware" % (sAudioType)
		self.session.open(MessageBox, _("This Dreambox can't decode %s streams!") % sAudioType, type=MessageBox.TYPE_INFO, timeout=20)

	def __evVideoDecodeError(self):
		currPlay = self.session.nav.getCurrentService()
		sVideoType = currPlay.info().getInfoString(iServiceInformation.sVideoType)
		print "[__evVideoDecodeError] video-codec %s can't be decoded by hardware" % (sVideoType)
		self.session.open(MessageBox, _("This Dreambox can't decode %s streams!") % sVideoType, type=MessageBox.TYPE_INFO, timeout=20)

	def __evPluginError(self):
		currPlay = self.session.nav.getCurrentService()
		message = currPlay.info().getInfoString(iServiceInformation.sUser + 12)
		print "[__evPluginError]" , message
		self.session.open(MessageBox, message, type=MessageBox.TYPE_INFO, timeout=20)

	def delMPTimer(self):
		del self.rightKeyTimer
		del self.leftKeyTimer

	def readTitleInformation(self):
		currPlay = self.session.nav.getCurrentService()
		if currPlay is not None:
			sTagTitle = currPlay.info().getInfoString(iServiceInformation.sTagTitle)
			sTagAlbum = currPlay.info().getInfoString(iServiceInformation.sTagAlbum)
			sTagGenre = currPlay.info().getInfoString(iServiceInformation.sTagGenre)
			sTagArtist = currPlay.info().getInfoString(iServiceInformation.sTagArtist)
			sYear = currPlay.info().getInfoString(iServiceInformation.sTimeCreate)

			if sTagTitle == "":
				if not self.isAudioCD:
					sTagTitle = currPlay.info().getName().split('/')[-1]
				else:
					sTagTitle = self.playlist.getServiceRefList()[self.playlist.getCurrentIndex()].getName()

			if self.AudioCD_albuminfo:
				if sTagAlbum == "" and "title" in self.AudioCD_albuminfo:
					sTagAlbum = self.AudioCD_albuminfo["title"]
				if sTagGenre == "" and "genre" in self.AudioCD_albuminfo:
					sTagGenre = self.AudioCD_albuminfo["genre"]
				if sTagArtist == "" and "artist" in self.AudioCD_albuminfo:
					sTagArtist = self.AudioCD_albuminfo["artist"]
				if "year" in self.AudioCD_albuminfo:
					sYear = self.AudioCD_albuminfo["year"]

			self.updateMusicInformation(sTagArtist, sTagTitle, sTagAlbum, sYear, sTagGenre, clear=True)
		else:
			self.updateMusicInformation()

	def updateMusicInformation(self, artist="", title="", album="", year="", genre="", clear=False):
		self.updateSingleMusicInformation("artist", artist, clear)
		self.updateSingleMusicInformation("title", title, clear)
		self.updateSingleMusicInformation("album", album, clear)
		self.updateSingleMusicInformation("year", year, clear)
		self.updateSingleMusicInformation("genre", genre, clear)

	def updateSingleMusicInformation(self, name, info, clear):
		if info != "" or clear:
			if self[name].getText() != info:
				self[name].setText(info)

	def leftDown(self):
		self.lefttimer = False
		self.leftKeyTimer.start(10)

	def rightDown(self):
		self.righttimer = False
		self.rightKeyTimer.start(10)

	def leftUp(self):
		if self.lefttimer:
			self.leftKeyTimer.stop()
			self.lefttimer = False
			self[self.currList].pageUp()
			self.updateCurrentInfo()

	def rightUp(self):
		if self.righttimer:
			self.rightKeyTimer.stop()
			self.righttimer = False
			self[self.currList].pageDown()
			self.updateCurrentInfo()

	def leftTimerFire(self):
		self.leftKeyTimer.stop()
		self.lefttimer = False
		self.switchToFileList()

	def rightTimerFire(self):
		self.rightKeyTimer.stop()
		self.righttimer = False
		self.switchToPlayList()

	def switchToFileList(self):
		self.currList = "filelist"
		self.filelist.selectionEnabled(1)
		self.playlist.selectionEnabled(0)
		self.updateCurrentInfo()

	def switchToPlayList(self):
		if len(self.playlist) != 0:
			self.currList = "playlist"
			self.filelist.selectionEnabled(0)
			self.playlist.selectionEnabled(1)
			self.updateCurrentInfo()

	def up(self):
		self[self.currList].up()
		self.updateCurrentInfo()

	def down(self):
		self[self.currList].down()
		self.updateCurrentInfo()

	def showAfterSeek(self):
		self.show()

	def showAfterCuesheetOperation(self):
		self.show()

	def hideAfterResume(self):
		self.hide()

	def getIdentifier(self, ref):
		if self.isAudioCD:
			return ref.getName()
		else:
			text = ref.getPath()
			return text.split('/')[-1]

	# FIXME: maybe this code can be optimized 
	def updateCurrentInfo(self):
		text = ""
		if self.currList == "filelist":
			idx = self.filelist.getSelectionIndex()
			r = self.filelist.list[idx]
			text = r[1][7]
			if r[0][1] == True:
				if len(text) < 2:
					text += " "
				if text[:2] != "..":
					text = "/" + text
			self.summaries.setText(text, 1)

			idx += 1
			if idx < len(self.filelist.list):
				r = self.filelist.list[idx]
				text = r[1][7]
				if r[0][1] == True:
					text = "/" + text
				self.summaries.setText(text, 3)
			else:
				self.summaries.setText(" ", 3)

			idx += 1
			if idx < len(self.filelist.list):
				r = self.filelist.list[idx]
				text = r[1][7]
				if r[0][1] == True:
					text = "/" + text
				self.summaries.setText(text, 4)
			else:
				self.summaries.setText(" ", 4)

			text = ""
			if not self.filelist.canDescent():
				r = self.filelist.getServiceRef()
				if r is None:
					return
				text = r.getPath()
				self["currenttext"].setText(os_path.basename(text))

		if self.currList == "playlist":
			t = self.playlist.getSelection()
			if t is None:
				return
			#display current selected entry on LCD
			text = self.getIdentifier(t)
			self.summaries.setText(text, 1)
			self["currenttext"].setText(text)
			idx = self.playlist.getSelectionIndex()
			idx += 1
			if idx < len(self.playlist):
				currref = self.playlist.getServiceRefList()[idx]
				text = self.getIdentifier(currref)
				self.summaries.setText(text, 3)
			else:
				self.summaries.setText(" ", 3)

			idx += 1
			if idx < len(self.playlist):
				currref = self.playlist.getServiceRefList()[idx]
				text = self.getIdentifier(currref)
				self.summaries.setText(text, 4)
			else:
				self.summaries.setText(" ", 4)

	def ok(self):
		if self.currList == "filelist":
			if self.filelist.canDescent():
				self.filelist.descent()
				self.updateCurrentInfo()
			else:
				self.copyFile()

		if self.currList == "playlist":
			selection = self["playlist"].getSelection()
			self.changeEntry(self.playlist.getSelectionIndex())

	def showMenu(self):
		menu = []
		if len(self.cdAudioTrackFiles):
			menu.insert(0, (_("Play Audio-CD..."), "audiocd"))
		if self.currList == "filelist":
			#menu.append((_("add selection after current playing"), "addAfterCurrent"))
			if self.filelist.canDescent():
				menu.append((_("add directory to playlist"), "copydir"))
			else:
				menu.append((_("add files to playlist"), "copyfiles"))
			menu.append((_("switch to playlist"), "playlist"))
		else:
			menu.append((_("switch to filelist"), "filelist"))
			menu.append((_("clear playlist"), "clear"))
			menu.append((_("Delete entry"), "deleteentry"))
			if config.usage.setup_level.index >= 1: # intermediate+
				menu.append((_("shuffle playlist"), "shuffle"))
		if pathExists("/usr/lib/enigma2/python/Plugins/Extensions/PicturePlayer/"):
			menu.append((_("PicturePlayer"), "PicturePlayer"));
		if config.usage.setup_level.index >= 1: # intermediate+
			menu.append((_("delete file"), "deletefile"))
		menu.append((_("hide player"), "hide"));
		menu.append((_("load playlist"), "loadplaylist"));
		if config.usage.setup_level.index >= 1: # intermediate+
			menu.append((_("save playlist"), "saveplaylist"));
			menu.append((_("delete saved playlist"), "deleteplaylist"));
			menu.append((_("Edit settings"), "settings"))
			menu.append((_("add/remove bookmarks (locationbox)"), "locationbox"))
		if self.currList == "filelist":
			menu.append((_("---------------------- bookmarks -------------------"), "line"))
			for x in self.bookmarks.value:
				menu.append((x, x))
		self.session.openWithCallback(self.menuCallback, ChoiceBox, title="", list=menu)

	def menuCallback(self, choice):
		if choice is None:
			return

		if choice[1] == "copydir":
			self.savePlaylistOnExit = True
			self.copyDirectory(self.filelist.getSelection()[0])
		elif choice[1] == "copyfiles":
			self.stopEntry()
			self.playlist.clear()
			self.savePlaylistOnExit = True
			self.isAudioCD = False
			self.copyDirectory(os_path.dirname(self.filelist.getSelection()[0].getPath()) + "/", recursive=False)
			self.playServiceRefEntry(self.filelist.getServiceRef())
		elif choice[1] == "addAfterCurrent":
			self.copyFileAfterCurrentPlaying()
		elif choice[1] == "playlist":
			self.switchToPlayList()
		elif choice[1] == "filelist":
			self.switchToFileList()
		elif choice[1] == "deleteentry":
			if self.playlist.getSelectionIndex() == self.playlist.getCurrentIndex():
				self.stopEntry()
			self.deleteEntry()
		elif choice[1] == "clear":
			self.clear_playlist()
		elif choice[1] == "hide":
			self.hide()
		elif choice[1] == "saveplaylist":
			self.save_playlist()
		elif choice[1] == "loadplaylist":
			self.load_playlist()
		elif choice[1] == "deleteplaylist":
			self.delete_saved_playlist()
		elif choice[1] == "shuffle":
			self.playlist.PlayListShuffle()
		elif choice[1] == "PicturePlayer":
			from Plugins.Extensions.PicturePlayer.plugin import picshow
			self.session.open(picshow)
		elif choice[1] == "deletefile":
			self.deleteFile()
		elif choice[1] == "settings":
			self.session.openWithCallback(self.applySettings, MediaPlayerSettings, self)
		elif choice[1] == "audiocd":
			self.playAudioCD()
		elif choice[1] == "locationbox":
			self.doPathSelect()
		elif choice[1] == "line":
			print "--- bookmark ---"
		else:
			print "bookmark: ", choice[1]
			self.filelist.changeDir(choice[1])

	def doPathSelect(self):
		self.session.openWithCallback(self.gotPath, LocationBox, _("Please select the path..."), currDir=self.filelist.getCurrentDirectory(), bookmarks=config.movielist.videodirs)

	def gotPath(self, res):
		if res is not None:
			self.filelist.changeDir(res)
			
	def playAudioCD(self):
		from enigma import eServiceReference
		from Plugins.Extensions.CDInfo.plugin import Query

		if len(self.cdAudioTrackFiles):
			self.playlist.clear()
			self.savePlaylistOnExit = False
			self.isAudioCD = True
			for file in self.cdAudioTrackFiles:
				ref = eServiceReference(4097, 0, file)
				self.playlist.addFile(ref)
			cdinfo = Query(self)
			cdinfo.scan()
			self.changeEntry(0)
			self.switchToPlayList()

	def applySettings(self):		
		if config.plugins.mediaplayer2.repeat.getValue() == True:
			self["repeat"].setPixmapNum(1)
		else:
			self["repeat"].setPixmapNum(0)

	def showEventInformation(self):
		from Screens.EventView import EventViewSimple
		from ServiceReference import ServiceReference
		evt = self[self.currList].getCurrentEvent()
		if evt:
			self.session.open(EventViewSimple, evt, ServiceReference(self.getCurrent()))

	# also works on filelist (?)
	def getCurrent(self):
		return self["playlist"].getCurrent()

	def deletePlaylistEntry(self):
		if self.currList == "playlist":
			if self.playlist.getSelectionIndex() == self.playlist.getCurrentIndex():
				self.stopEntry()
			self.deleteEntry()

	def skip_listbegin(self):
		if self.currList == "filelist":
			self.filelist.moveToIndex(0)
		else:
			self.playlist.moveToIndex(0)
		self.updateCurrentInfo()

	def skip_listend(self):
		if self.currList == "filelist":
			idx = len(self.filelist.list)
			self.filelist.moveToIndex(idx - 1)
		else:
			self.playlist.moveToIndex(len(self.playlist) - 1)
		self.updateCurrentInfo()

	def save_playlist(self):
		self.session.openWithCallback(self.save_playlist2, InputBox, title=_("Please enter filename (empty = use current date)"), windowTitle=_("Save Playlist"))

	def save_playlist2(self, name):
		if name is not None:
			name = name.strip()
			if name == "":
				name = strftime("%y%m%d_%H%M%S")
			name += ".e2pls"
			self.playlistIOInternal.clear()
			for x in self.playlist.list:
				self.playlistIOInternal.addService(ServiceReference(x[0]))
			self.playlistIOInternal.save(resolveFilename(SCOPE_PLAYLIST) + name)

	def load_playlist(self):
		listpath = []
		playlistdir = resolveFilename(SCOPE_PLAYLIST)
		try:
			for i in os_listdir(playlistdir):
				listpath.append((i, playlistdir + i))
		except IOError, e:
			print "Error while scanning subdirs ", e
		self.session.openWithCallback(self.PlaylistSelected, ChoiceBox, title=_("Please select a playlist..."), list=listpath)

	def PlaylistSelected(self, path):
		if path is not None:
			self.clear_playlist()
			extension = path[0].rsplit('.', 1)[-1]
			if self.playlistparsers.has_key(extension):
				playlist = self.playlistparsers[extension]()
				list = playlist.open(path[1])
				for x in list:
					self.playlist.addFile(x.ref)
			self.playlist.updateList()

	def delete_saved_playlist(self):
		listpath = []
		playlistdir = resolveFilename(SCOPE_PLAYLIST)
		try:
			for i in os_listdir(playlistdir):
				listpath.append((i, playlistdir + i))
		except IOError, e:
			print "Error while scanning subdirs ", e
		self.session.openWithCallback(self.DeletePlaylistSelected, ChoiceBox, title=_("Please select a playlist to delete..."), list=listpath)

	def DeletePlaylistSelected(self, path):
		if path is not None:
			self.delname = path[1]
			self.session.openWithCallback(self.deleteConfirmed, MessageBox, _("Do you really want to delete %s?") % (path[1]))

	def deleteConfirmed(self, confirmed):
		if confirmed:
			try:
				os_remove(self.delname)
			except OSError, e:
				self.session.open(MessageBox, _("Delete failed!, %s") % e, MessageBox.TYPE_ERROR)

	def clear_playlist(self):
		self.isAudioCD = False
		self.savePlaylistOnExit = True
		self.stopEntry()
		self.playlist.clear()
		self.switchToFileList()

	def copyDirectory(self, directory, recursive=True):
		print "copyDirectory", directory
		if directory == '/':
			print "refusing to operate on /"
			return
		filelist = FileList(directory, useServiceRef=True, showMountpoints=False, isTop=True)
		#filelist = FileList(directory, matchingPattern = "(?i)^.*\.(mp2|mp3|ts|wav|wave|m3u|pls|e2pls|mpg|vob|avi|mkv|mp4|m4a|dat|m2ts|wma)", useServiceRef = True, showMountpoints = False, isTop = True)
		
		for x in filelist.getFileList():
			if x[0][1] == True: #isDir
				if recursive:
					if x[0][0] != directory:
						self.copyDirectory(x[0][0])
			else:
				self.playlist.addFile(x[0][0])
		self.playlist.updateList()

	def deleteFile(self):
		if self.currList == "filelist":
			self.service = self.filelist.getServiceRef()
		else:
			self.service = self.playlist.getSelection()
		if self.service is None:
			return
		if self.service.type != 4098 and self.session.nav.getCurrentlyPlayingServiceReference() is not None:
			if self.service == self.session.nav.getCurrentlyPlayingServiceReference():
				self.stopEntry()

		serviceHandler = eServiceCenter.getInstance()
		offline = serviceHandler.offlineOperations(self.service)
		info = serviceHandler.info(self.service)
		name = info and info.getName(self.service)
		result = False
		if offline is not None:
			# simulate first
			if not offline.deleteFromDisk(1):
				result = True
		if result == True:
			self.session.openWithCallback(self.deleteConfirmed_offline, MessageBox, _("Do you really want to delete %s?") % (name))
		else:
			self.session.openWithCallback(self.close, MessageBox, _("You cannot delete this!"), MessageBox.TYPE_ERROR)      

	def deleteConfirmed_offline(self, confirmed):
		if confirmed:
			serviceHandler = eServiceCenter.getInstance()
			offline = serviceHandler.offlineOperations(self.service)
			result = False
			if offline is not None:
				# really delete!
				if not offline.deleteFromDisk(0):
					result = True
			if result == False:
				self.session.open(MessageBox, _("Delete failed!"), MessageBox.TYPE_ERROR)
			else:
				self.removeListEntry()

	def removeListEntry(self):
		self.savePlaylistOnExit = True
		currdir = self.filelist.getCurrentDirectory()
		self.filelist.changeDir(currdir)
		deleteend = False
		while not deleteend:
			index = 0
			deleteend = True
			if len(self.playlist) > 0:
				for x in self.playlist.list:
					if self.service == x[0]:
						self.playlist.deleteFile(index)
						deleteend = False
						break
					index += 1
		self.playlist.updateList()
		if self.currList == "playlist":
			if len(self.playlist) == 0:
				self.switchToFileList()

	def copyFileAfterCurrentPlaying(self):
		self.savePlaylistOnExit = True
		
		item = self.filelist.getServiceRef()
		playpos = self.playlist.getCurrentIndex()
		self.playlist.insertFile(playpos + 1, item)
		self.playlist.updateList()

	def copyFile(self):
		self.savePlaylistOnExit = True
		if self.filelist.getServiceRef().type == 4098: # playlist
			ServiceRef = self.filelist.getServiceRef()
			extension = ServiceRef.getPath()[ServiceRef.getPath().rfind('.') + 1:]
			if self.playlistparsers.has_key(extension):
				playlist = self.playlistparsers[extension]()
				list = playlist.open(ServiceRef.getPath())
				for x in list:
					self.playlist.addFile(x.ref)
			self.playlist.updateList()
		else:
			self.playlist.addFile(self.filelist.getServiceRef())
			self.playlist.updateList()
			if len(self.playlist) == 1:
				self.changeEntry(0)

	def addPlaylistParser(self, parser, extension):
		self.playlistparsers[extension] = parser

	def nextEntry(self):
		next = self.playlist.getCurrentIndex() + 1
		if next < len(self.playlist):
			self.changeEntry(next)
		elif (len(self.playlist) > 0) and (config.plugins.mediaplayer2.repeat.getValue() == True):
			self.stopEntry()
			self.changeEntry(0)
		else:
			self.stopEntry()

	def previousEntry(self):
		next = self.playlist.getCurrentIndex() - 1
		if next >= 0:
			self.changeEntry(next)

	def deleteEntry(self):
		self.savePlaylistOnExit = True
		self.playlist.deleteFile(self.playlist.getSelectionIndex())
		self.playlist.updateList()
		if len(self.playlist) == 0:
			self.switchToFileList()

	def changeEntry(self, index):
		self.playlist.setCurrentPlaying(index)
		self.playEntry()

	def playServiceRefEntry(self, serviceref):
		serviceRefList = self.playlist.getServiceRefList()
		for count in range(len(serviceRefList)):
			if serviceRefList[count] == serviceref:
				self.changeEntry(count)
				break
			
	def xplayEntry(self):
		if self.currList == "playlist":
			self.playEntry()
		else:
			self.stopEntry()
			self.playlist.clear()
			self.isAudioCD = False
			self.savePlaylistOnExit = True
			sel = self.filelist.getSelection()
			if sel:
				if sel[1]: # can descent
					# add directory to playlist
					self.copyDirectory(sel[0])
				else:
					if self.filelist.getServiceRef().type == 4098: # playlist
						self.copyFile()
					else:
						# add files to playlist
						self.copyDirectory(os_path.dirname(sel[0].getPath()) + "/", recursive=False)
			if len(self.playlist) > 0:
				self.changeEntry(0)
	
	def playEntry(self):
		if len(self.playlist.getServiceRefList()):
			audio_extensions = (".mp2", ".mp3", ".wav", ".ogg", "flac", ".m4a")
			needsInfoUpdate = False
			currref = self.playlist.getServiceRefList()[self.playlist.getCurrentIndex()]
			if self.session.nav.getCurrentlyPlayingServiceReference() is None or currref != self.session.nav.getCurrentlyPlayingServiceReference():
				text = self.getIdentifier(currref)
				ext = text[-4:].lower()
				if ext in audio_extensions or self.isAudioCD:
					self.session.nav.playService(currref)
				else:
					self.MoviePlayerOpen = True
					self.session.openWithCallback(self.leaveMoviePlayer, MoviePlayer, currref)
				info = eServiceCenter.getInstance().info(currref)
				description = info and info.getInfoString(currref, iServiceInformation.sDescription) or ""
				self["title"].setText(description)
				# display just playing musik on LCD
				idx = self.playlist.getCurrentIndex()
				currref = self.playlist.getServiceRefList()[idx]
				#text = self.getIdentifier(currref)
				text = ">" + text
				#ext = text[-4:].lower()

				# FIXME: the information if the service contains video (and we should hide our window) should com from the service instead 
				if ext in audio_extensions or self.isAudioCD:
					needsInfoUpdate = True
				self.summaries.setText(text, 1)

				# get the next two entries
				idx += 1
				if idx < len(self.playlist):
					currref = self.playlist.getServiceRefList()[idx]
					text = self.getIdentifier(currref)
					self.summaries.setText(text, 3)
				else:
					self.summaries.setText(" ", 3)

				idx += 1
				if idx < len(self.playlist):
					currref = self.playlist.getServiceRefList()[idx]
					text = self.getIdentifier(currref)
					self.summaries.setText(text, 4)
				else:
					self.summaries.setText(" ", 4)
			else:
				idx = self.playlist.getCurrentIndex()
				currref = self.playlist.getServiceRefList()[idx]
				text = currref.getPath()
				ext = text[-4:].lower()
				if ext in audio_extensions or self.isAudioCD:
					needsInfoUpdate = True

			self.unPauseService()
			if needsInfoUpdate == True:
				path = self.playlist.getServiceRefList()[self.playlist.getCurrentIndex()].getPath()
				self["coverArt"].updateCoverArt(path)
			else:
				self["coverArt"].showDefaultCover()
			self.readTitleInformation()

	def leaveMoviePlayer(self, answer):
		print "leaveMoviePlayer: ", answer
		self.MoviePlayerOpen = False
		if answer == 1:
			self.session.nav.playService(None)
			self.nextEntry()
		elif answer == -1:
			self.session.nav.playService(None)
			self.previousEntry()
		else:
			self.stopEntry()

	def updatedSeekState(self):
		if self.seekstate == self.SEEK_STATE_PAUSE:
			self.playlist.pauseFile()
		elif self.seekstate == self.SEEK_STATE_PLAY:
			self.playlist.playFile()
		elif self.isStateForward(self.seekstate):
			self.playlist.forwardFile()
		elif self.isStateBackward(self.seekstate):
			self.playlist.rewindFile()

	def pauseEntry(self):
		self.pauseService()
		self.show()

	def stopEntry(self):
		self.playlist.stopFile()
		self.session.nav.playService(None)
		self.updateMusicInformation(clear=True)
		self.show()
			
	def csfd(self):
		movieName = None
		if self.currList == "filelist" and CSFD:
			sel = self.filelist.getSelection()
			if sel is not None:
				if sel[1]:
					path = sel[0]
					print path
					movieName = path.split('/')[-2]
				else:
					path = sel[0].getPath()
					print path
					movieName = os.path.splitext(os.path.split(path)[1])[0]
			
				if movieName is not None:
					movieName = movieName.replace('.', ' ').replace('_', ' ').replace('-', ' ')
					print 'opening csfd', movieName
					if CSFD is not None:
						self.session.open(CSFD, movieName, False)

	def unPauseService(self):
		self.setSeekState(self.SEEK_STATE_PLAY)

	def hotplugCB(self, dev, media_state):
		if dev == harddiskmanager.getCD():
			if media_state == "1":
				from Components.Scanner import scanDevice
				devpath = harddiskmanager.getAutofsMountpoint(harddiskmanager.getCD())
				self.cdAudioTrackFiles = []
				res = scanDevice(devpath)
				list = [ (r.description, r, res[r], self.session) for r in res ]
				if list:
					(desc, scanner, files, session) = list[0]
					for file in files:
						if file.mimetype == "audio/x-cda":
							self.cdAudioTrackFiles.append(file.path)
			else:
				self.cdAudioTrackFiles = []
				if self.isAudioCD:
					self.clear_playlist()


class MoviePlayer(InfoBarShowHide,SubsSupport, \
		InfoBarSeek, InfoBarAudioSelection, HelpableScreen, InfoBarNotifications,
		InfoBarServiceNotifications, InfoBarPVRState, InfoBarCueSheetSupport, InfoBarSimpleEventView,
		InfoBarMoviePlayerSummarySupport, Screen, InfoBarTeletextPlugin,
		InfoBarServiceErrorPopupSupport):

	ENABLE_RESUME_SUPPORT = True
	ALLOW_SUSPEND = True
		
	def __init__(self, session, service):
		Screen.__init__(self, session)
		
		self["actions"] = HelpableActionMap(self, "MoviePlayerActions",
			{
				"aspectChange": (self.aspectChange, _("changing aspect")),
				"leavePlayer": (self.leavePlayer, _("leave movie player...")),
				"audioSelection": (self.audioSelection, _("Audio Options..."))
			}, -5)
			
		self["MediaPlayerActions"] = HelpableActionMap(self, "MediaPlayerActions",
			{
				"previous": (self.previousMarkOrEntry, _("play from previous mark or playlist entry")),
				"next": (self.nextMarkOrEntry, _("play from next mark or playlist entry")),
				"aspectratio" : (self.aspectChange, _("AspectRatioChange")),
			}, -2)
		
		for x in HelpableScreen, InfoBarShowHide, \
				InfoBarSeek, \
				InfoBarAudioSelection, InfoBarNotifications, InfoBarSimpleEventView, \
				InfoBarServiceNotifications, InfoBarPVRState, InfoBarCueSheetSupport, \
				InfoBarMoviePlayerSummarySupport,SubsSupport, \
				InfoBarTeletextPlugin, InfoBarServiceErrorPopupSupport:
			x.__init__(self)
			
		self.session.nav.playService(service)
		self.returning = False
	
	def nextMarkOrEntry(self):
		if not self.jumpPreviousNextMark(lambda x: x):
			self.is_closing = True
			self.close(1)

	def previousMarkOrEntry(self):
		if not self.jumpPreviousNextMark(lambda x:-x - 5 * 90000, start=True):
			self.is_closing = True
			self.close(-1)
	
	def aspectChange(self):
		print "Aspect Ratio"
		global aspectratiomode
		print  aspectratiomode
		if aspectratiomode == "1": #letterbox
			eAVSwitch.getInstance().setAspectRatio(0)
			aspectratiomode = "2"
		elif aspectratiomode == "2": #nonlinear
			eAVSwitch.getInstance().setAspectRatio(4)
			aspectratiomode = "3"
		elif aspectratiomode == "2": #nonlinear
			eAVSwitch.getInstance().setAspectRatio(2)
			aspectratiomode = "3"
		elif aspectratiomode == "3": #panscan
			eAVSwitch.getInstance().setAspectRatio(3)
			aspectratiomode = "1"		
			
	def leavePlayer(self):
		self.is_closing = True

		if config.usage.on_movie_stop.value == "ask":
			list = []
			list.append((_("Yes"), "quit"))
			list.append((_("No"), "continue"))
			if config.usage.setup_level.index >= 2: # expert+
				list.append((_("No, but restart from begin"), "restart"))
			self.session.openWithCallback(self.leavePlayerConfirmed, ChoiceBox, title=_("Stop playing this movie?"), list=list)
		else:
			self.close(0)

	def leavePlayerConfirmed(self, answer):
		answer = answer and answer[1]
		if answer == "quit":
			self.close(0)
		elif answer == "restart":
			self.doSeek(0)

	def doEofInternal(self, playing):
		print "--- eofint movieplayer ---"
		self.is_closing = True
		self.close(1)

class MediaPlayerLCDScreen(Screen):
	skin = """
	<screen position="0,0" size="132,64" title="LCD Text">
		<widget name="text1" position="4,0" size="132,35" font="Regular;16"/>
		<widget name="text3" position="4,36" size="132,14" font="Regular;10"/>
		<widget name="text4" position="4,49" size="132,14" font="Regular;10"/>
	</screen>"""

	def __init__(self, session, parent):
		Screen.__init__(self, session)
		self["text1"] = Label("Mediaplayer")
		self["text3"] = Label("")
		self["text4"] = Label("")

	def setText(self, text, line):
		if len(text) > 10:
			if text[-4:] == ".mp3":
				text = text[:-4]
		textleer = "    "
		text = text + textleer * 10
		if line == 1:
			self["text1"].setText(text)
		elif line == 3:
			self["text3"].setText(text)
		elif line == 4:
			self["text4"].setText(text)

def main(session, **kwargs):
	session.open(MediaPlayer)

def menu(menuid, **kwargs):
	if menuid == "mainmenu":
		return [(_("Media player"), main, "media_player", 45)]
	return []

def filescan_open(list, session, **kwargs):
	from enigma import eServiceReference

	mp = session.open(MediaPlayer)
	mp.playlist.clear()
	mp.savePlaylistOnExit = False

	for file in list:
		if file.mimetype == "video/MP2T":
			stype = 1
		else:
			stype = 4097
		ref = eServiceReference(stype, 0, file.path)
		mp.playlist.addFile(ref)

	mp.changeEntry(0)
	mp.switchToPlayList()

def audioCD_open(list, session, **kwargs):
	from enigma import eServiceReference

	mp = session.open(MediaPlayer)
	mp.cdAudioTrackFiles = []
	for file in list:
		mp.cdAudioTrackFiles.append(file.path)
	mp.playAudioCD()

def filescan(**kwargs):
	from Components.Scanner import Scanner, ScanPath
	mediatypes = [
		Scanner(mimetypes=["video/mpeg", "video/MP2T", "video/x-msvideo"],
			paths_to_scan=
				[
					ScanPath(path="", with_subdirs=False),
				],
			name="Movie",
			description=_("View Movies..."),
			openfnc=filescan_open,
		),
		Scanner(mimetypes=["video/x-vcd"],
			paths_to_scan=
				[
					ScanPath(path="mpegav", with_subdirs=False),
					ScanPath(path="MPEGAV", with_subdirs=False),
				],
			name="Video CD",
			description=_("View Video CD..."),
			openfnc=filescan_open,
		),
		Scanner(mimetypes=["audio/mpeg", "audio/x-wav", "application/ogg", "audio/x-flac"],
			paths_to_scan=
				[
					ScanPath(path="", with_subdirs=False),
				],
			name="Music",
			description=_("Play Music..."),
			openfnc=filescan_open,
		)]
	try:
		from Plugins.Extensions.CDInfo.plugin import Query
		mediatypes.append(
		Scanner(mimetypes=["audio/x-cda"],
			paths_to_scan=
				[
					ScanPath(path="", with_subdirs=False),
				],
			name="Audio-CD",
			description=_("Play Audio-CD..."),
			openfnc=audioCD_open,
		))
		return mediatypes
	except ImportError:
		return mediatypes
	
def startSetup(menuid, **kwargs):
	if menuid == "mainmenu":
		return [(_("Media player"), main, "media_player", 45)]
	return []


from Plugins.Plugin import PluginDescriptor
from Components.PluginComponent import plugins

def Plugins(**kwargs):
	name = 'MediaPlayer2'
	descr = _('Play back media files with subtitles')
	list = []
	list.append(PluginDescriptor(name=name, description=descr, where=PluginDescriptor.WHERE_PLUGINMENU, icon="plugin.png", fnc=main))
	if config.plugins.mediaplayer2.extensionsMenu.getValue():
		list.append(PluginDescriptor(name=name, description=descr, where=PluginDescriptor.WHERE_EXTENSIONSMENU, fnc=main))
		
	if config.plugins.mediaplayer2.mainMenu.getValue():
		for p in plugins.getPlugins(where=PluginDescriptor.WHERE_MENU):
			if p.name == "MediaPlayer":
				plugins.removePlugin(p)
				break
		list.append(PluginDescriptor(name=name, description=descr, where=PluginDescriptor.WHERE_MENU, needsRestart=False, fnc=startSetup))
	return list
		
		
