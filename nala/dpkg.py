#                 __
#    ____ _____  |  | _____
#   /    \\__  \ |  | \__  \
#  |   |  \/ __ \|  |__/ __ \_
#  |___|  (____  /____(____  /
#       \/     \/          \/
#
# Copyright (C) 2021, 2022 Blake Lee
#
# This file is part of nala
#
# nala is program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# nala is program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with nala.  If not, see <https://www.gnu.org/licenses/>.
"""Nala dpkg module."""
from __future__ import annotations

import errno
import fcntl
import os
import pty
import re
import signal
import struct
import sys
import termios
from time import sleep
from types import FrameType
from typing import Callable, TextIO

import apt_pkg
from apt.progress import base, text
from pexpect.fdpexpect import fdspawn
from pexpect.utils import poll_ignore_interrupts

from nala.constants import DPKG_LOG, DPKG_MSG, ERROR_PREFIX, SPAM
from nala.options import arguments
from nala.rich import Live, Spinner, Table, Text
from nala.utils import color, term

spinner = Spinner('dots', text='Initializing', style="bold blue")
scroll_list: list[Spinner | str] = []
notice: set[str] = set()
live = Live(redirect_stdout=False)

class UpdateProgress(text.AcquireProgress, base.OpProgress): # type: ignore[misc]
	"""Class for getting cache update status and printing to terminal."""

	def __init__(self) -> None:
		"""Class for getting cache update status and printing to terminal."""
		text.AcquireProgress.__init__(self)
		base.OpProgress.__init__(self)
		self._file = sys.stdout
		self._signal = None
		self._id = 1
		self._width = 80
		self.old_op = "" # OpProgress setting
		if arguments.debug:
			arguments.verbose=True

		spinner.text = Text('Initializing Cache')
		scroll_list.clear()
		scroll_list.append(spinner)

	# OpProgress Method
	def update(self, percent: float | None = None) -> None:
		"""Call periodically to update the user interface."""
		base.OpProgress.update(self, percent)
		if arguments.verbose:
			if self.major_change and self.old_op:
				self._write(self.old_op)
			self._write(f"{self.op}... {self.percent}%\r", False, True)
			self.old_op = self.op

	# OpProgress Method
	def done(self, _dummy_variable:None = None) -> None:
		"""Call once an operation has been completed."""
		base.OpProgress.done(self)
		if arguments.verbose:
			if self.old_op:
				self._write(f"\r{self.old_op}... Done", True, True)
			self.old_op = ""

	def _write(self, msg: str, newline: bool = True, maximize: bool = False) -> None:
		"""Write the message on the terminal, fill remaining space."""
		if arguments.verbose:
			self._file.write("\r")
			self._file.write(msg)

			# Fill remaining stuff with whitespace
			if self._width > len(msg):
				self._file.write((self._width - len(msg)) * ' ')
			elif maximize:  # Needed for OpProgress.
				self._width = max(self._width, len(msg))
			if newline:
				self._file.write("\n")
			else:
				self._file.flush()
		else:
			for item in ['Updated:', 'Ignored:', 'Error:', 'No Change:']:
				if item in msg:
					scroll_bar(msg)
					break
			else:
				# For the pulse messages we need to do some formatting
				# End of the line will look like '51.8 mB/s 2s'
				if msg.endswith('s'):
					pulse = msg.split()
					last = len(pulse) - 1
					fill = sum(len(line) for line in pulse) + last
					# Minus three too account for our spinner dots
					fill = (self._width - fill) - 3
					pulse.insert(last-2, ' '*fill)
					msg = ' '.join(pulse)

				spinner.text = Text(msg)
				scroll_bar(msg=None)

	def ims_hit(self, item: apt_pkg.AcquireItemDesc) -> None:
		"""Call when an item is update (e.g. not modified on the server)."""
		base.AcquireProgress.ims_hit(self, item)
		self.write_update('No Change:', 'GREEN', item)

	def fail(self, item: apt_pkg.AcquireItemDesc) -> None:
		"""Call when an item is failed."""
		base.AcquireProgress.fail(self, item)
		if item.owner.status == item.owner.STAT_DONE:
			self._write(f"{color('Ignored:  ', 'YELLOW')} {item.description}")
		else:
			self._write(ERROR_PREFIX+item.description)
			self._write(f"  {item.owner.error_text}")

	def fetch(self, item: apt_pkg.AcquireItemDesc) -> None:
		"""Call when some of the item's data is fetched."""
		base.AcquireProgress.fetch(self, item)
		# It's complete already (e.g. Hit)
		if item.owner.complete:
			return
		self.write_update('Updated:  ', 'BLUE', item)

	def write_update(self, msg: str, _color: str, item: apt_pkg.AcquireItemDesc) -> None:
		"""Write the update from either hit or fetch."""
		line = f'{color(msg, _color)} {item.description}'
		if item.owner.filesize:
			size = apt_pkg.size_to_str(item.owner.filesize)
			line += f' [{size}B]'
		self._write(line)

	def _winch(self, *_args: object) -> None:
		"""Signal handler for window resize signals."""
		if hasattr(self._file, "fileno") and os.isatty(self._file.fileno()):
			buf = fcntl.ioctl(self._file, termios.TIOCGWINSZ, 8 * b' ')
			dummy, col, dummy, dummy = struct.unpack('hhhh', buf)
			self._width = col - 1  # 1 for the cursor

	def start(self) -> None:
		"""Start an Acquire progress.

		In this case, the function sets up a signal handler for SIGWINCH, i.e.
		window resize signals. And it also sets id to 1.
		"""
		base.AcquireProgress.start(self)
		self._signal = signal.signal(signal.SIGWINCH, self._winch) # type: ignore[assignment]
		# Get the window size.
		self._winch()
		self._id = 1
		live.start()

	def stop(self) -> None:
		"""Invoke when the Acquire process stops running."""
		base.AcquireProgress.stop(self)
		# Trick for getting a translation from apt
		fetched = apt_pkg.size_to_str(self.fetched_bytes)
		elapsed = apt_pkg.time_to_str(self.elapsed_time)
		speed = apt_pkg.size_to_str(self.current_cps).rstrip("\n")
		msg = color(f"Fetched {fetched}B in {elapsed} ({speed}B/s)")
		self._write(msg)

		# Delete the signal again.
		signal.signal(signal.SIGWINCH, self._signal)
		live.stop()

class InstallProgress(base.InstallProgress): # type: ignore[misc]
	"""Class for getting dpkg status and printing to terminal."""

	def __init__(self) -> None:
		"""Class for getting dpkg status and printing to terminal."""
		base.InstallProgress.__init__(self)
		self.raw = False
		self.last_line = b''
		self.dpkg_log: TextIO
		self.child: AptExpect
		self.child_fd: int
		self.child_pid: int
		# If we detect we're piped it's probably best to go raw.
		if not term.is_term():
			arguments.raw_dpkg = True
		# Setting environment to xterm seems to work fine for linux terminal
		# I don't think we will be supporting much more this this, at least for now
		if not term.is_xterm() and not arguments.raw_dpkg:
			os.environ["TERM"] = 'xterm'

		spinner.text = Text('Initializing dpkg')
		scroll_list.clear()
		scroll_list.append(spinner)

	@staticmethod
	def start_update() -> None:
		"""Start update."""
		if not arguments.verbose and not arguments.raw_dpkg:
			live.start()
			spinner.text = Text(color('Initializing dpkg...', 'BLUE'))

	@staticmethod
	def finish_update() -> None:
		"""Call when update has finished."""
		if not arguments.verbose and not arguments.raw_dpkg:
			live.stop()
		if notice:
			print('\n'+color('Notices:'))
			for notice_msg in notice:
				print(notice_msg)
		print(color("Finished Successfully", 'GREEN'))

	def __exit__(self, _type: object, value: object, traceback: object) -> None:
		"""Exit."""

	def run(self, obj: apt_pkg.PackageManager | bytes | str) -> int:
		"""
		Install using the `PackageManager` object `obj`.

		returns the result of calling `obj.do_install()`
		"""
		pid, self.child_fd = self.fork()
		if pid == 0:
			try:
				# We ignore this with mypy because the attr is there
				os._exit(obj.do_install()) # type: ignore[union-attr]
			# We need to catch every exception here.
			# If we don't the code continues in the child,
			# And bugs will be very confusing
			# pylint: disable=broad-except
			except Exception as err:
				sys.stderr.write(f"{err}\n")
				os._exit(1)

		self.child_pid = pid
		if arguments.raw_dpkg:
			return os.WEXITSTATUS(self.wait_child())

		fcntl.fcntl(self.child_fd, fcntl.F_SETFL, os.O_NONBLOCK)
		# We use fdspawn from pexpect to interact with out dpkg pty
		# But we also subclass it to give it the interact method and setwindow
		self.child = AptExpect(self.child_fd, timeout=None)

		signal.signal(signal.SIGWINCH, self.sigwinch_passthrough)
		with open(DPKG_LOG, 'w', encoding="utf-8") as self.dpkg_log:
			self.child.interact(self.format_dpkg_output)
		return os.WEXITSTATUS(self.wait_child())

	def fork(self) -> tuple[int, int]:
		"""Fork pty or regular."""
		return (os.fork(), 0) if arguments.raw_dpkg else pty.fork()

	def wait_child(self) -> int:
		"""Wait for child progress to exit."""
		(pid, res) = (0, 0)
		while True:
			try:
				sleep(0.01)
				(pid, res) = os.waitpid(self.child_pid, os.WNOHANG)
				if pid == self.child_pid:
					break
			except OSError as err:
				if err.errno == errno.ECHILD:
					break
				if err.errno != errno.EINTR:
					raise
		return res

	def sigwinch_passthrough(self, _sig_dummy: int, _data_dummy: FrameType | None) -> None:
		"""Pass through sigwinch signals to dpkg."""
		buffer = struct.pack("HHHH", 0, 0, 0, 0)
		term_size = struct.unpack('hhhh', fcntl.ioctl(term.STDIN,
			termios.TIOCGWINSZ , buffer))
		if not self.child.closed:
			setwinsize(self.child_fd, term_size[0],term_size[1])

	def conf_check(self, rawline: bytes) -> None:
		"""Check if we get a conf prompt."""
		# I wish they would just use debconf for this.
		# But here we are and this is what we're doing for config files
		for line in DPKG_MSG['CONF_MESSAGE']:
			# We only iterate the whole list just in case. We don't want to miss this.
			# Even if we just hit the last line it's better than not hitting it.
			if line in rawline:
				# Sometimes dpkg be like yo I'm going to say the same thing as the conf prompt
				# But a little different so it will trip you up.
				if rawline.endswith((b'.', b'\r\n')):
					break
				self.raw = True
				raw_init()
				# Add return because our progress bar might eat one
				#if not rawline.startswith(b'\r'):
				rawline = b'\r'+rawline
				break

	def conf_end(self, rawline: bytes) -> bool:
		"""Check to see if the conf prompt is over."""
		return rawline == b'\r\n' and (DPKG_MSG['CONF_MESSAGE'][9] in self.last_line
										or self.last_line in DPKG_MSG['CONF_ANSWER'])

	def format_dpkg_output(self, rawline: bytes) -> None:
		"""Facilitate what needs to happen to dpkg output."""
		# During early development this is mandatory
		# if self.debug:
		self.dpkg_log.write(repr(rawline)+'\n')
		self.dpkg_log.flush()

		# These are real spammy the way we set this up
		# So if we're in verbose just send it
		for item in DPKG_MSG['DPKG_STATUS']:
			if item in rawline:
				if arguments.verbose:
					term.write(rawline)
				else:
					spinner.text = Text(color(rawline.decode().strip()))
					scroll_bar(msg=None)
				return

		# Set to raw if we have a conf prompt
		self.conf_check(rawline)

		# This second one is for the start of the shell
		if term.SAVE_TERM in rawline or term.ENABLE_BRACKETED_PASTE in rawline:
			self.raw = True
			raw_init()

		if self.raw:
			self.rawline_handler(rawline)
			return

		self.line_handler(rawline)

	def line_handler(self, rawline: bytes) -> None:
		"""Handle text operations for not a rawline."""
		line = rawline.decode().strip()
		if line == '':
			return

		if check_line_spam(line, rawline):
			return

		spinner.text = Text(color('Running dpkg...'))
		# Main format section for making things pretty
		msg = msg_formatter(line)
		# If verbose we just send it. No bars
		if arguments.verbose:
			# We have to append Carriage return and new line or things get weird
			term.write((msg+'\r\n').encode())
		else:
			scroll_bar(msg)

		self.set_last_line(rawline)

	def rawline_handler(self, rawline: bytes) -> None:
		"""Handle text operations for rawline."""
		term.write(rawline)
		# Once we write we can check if we need to pop out of raw mode
		if term.RESTORE_TERM in rawline or self.conf_end(rawline):
			self.raw = False
			term.restore_mode()
			live.start()
		self.set_last_line(rawline)

	def set_last_line(self, rawline: bytes) -> None:
		"""Set the current line to last line if there is no backspace."""
		# When at the conf prompt if you press Y, then backspace, then hit enter
		# Things get really buggy so instead we check for a backspace
		if term.BACKSPACE not in rawline:
			self.last_line = rawline

def check_line_spam(line: str, rawline: bytes) -> bool:
	"""Check for, and handle, notices and spam."""
	for message in DPKG_MSG['NOTICES']:
		if message in rawline:
			notice.add(line)
			return False

	return any(item in line for item in SPAM)

def raw_init() -> None:
	"""Initialize raw terminal output."""
	live.update('')
	term.write(term.CURSER_UP+term.CLEAR_LINE)
	live.stop()
	term.set_raw()

def msg_formatter(line: str) -> str:
	"""Format dpkg output."""
	msg = ''
	for word in line.split():
		match = re.fullmatch(r'\(.*.\)', word)
		if word == 'Removing':
			msg += color('Removing:   ', 'RED')
		elif word == 'Unpacking':
			msg += color('Unpacking:  ', 'GREEN')
		elif word == 'Setting':
			msg += color('Setting ', 'GREEN')
		elif word == 'up':
			msg += color('up: ', 'GREEN')
		elif word == 'Processing':
			msg += color('Processing: ', 'GREEN')
		elif word == '...':
			continue
		elif match:
			word = re.sub('[()]', '', word)
			paren = color('(')
			paren2 = color(')')
			msg += (' ') + paren+color(word, 'BLUE')+paren2
		else:
			msg += ' ' + word
	return msg

def scroll_bar(msg: str | None = None) -> None:
	"""Print msg to our scroll bar live display."""
	if msg:
		scroll_list.append(msg)

	scroll_list.append(
		scroll_list.pop(
			scroll_list.index(spinner)
		)
	)

	# Set the scroll bar to take up a 3rd of the screen
	scroll_lines = term.lines // 3
	if len(scroll_list) > scroll_lines and len(scroll_list) > 10:
		del scroll_list[0]

	table = Table.grid()
	table.add_column(no_wrap=True)
	for item in scroll_list:
		table.add_row(item)

	live.update(table)

def setwinsize(file_descriptor: int, rows: int, cols: int) -> None:
	"""Set the terminal window size of the child tty.

	This will cause a SIGWINCH signal to be sent to the child. This does not
	change the physical window size. It changes the size reported to
	TTY-aware applications like vi or curses -- applications that respond to
	the SIGWINCH signal.
	"""
	tiocswinz = getattr(termios, 'TIOCSWINSZ', -2146929561)
	# Note, assume ws_xpixel and ws_ypixel are zero.
	size = struct.pack('HHHH', rows, cols, 0, 0)
	fcntl.ioctl(file_descriptor, tiocswinz, size)

class AptExpect(fdspawn): # type: ignore[misc]
	"""Subclass of fdspawn to add the interact method."""

	def interact(self, output_filter: Callable[[bytes], None]) -> None:
		"""Hacked up interact method.

		Because pexpect doesn't want to have one for fdspawn.

		This gives control of the child process to the interactive user (the
		human at the keyboard). Keystrokes are sent to the child process, and
		the stdout and stderr output of the child process is printed. This
		simply echos the child stdout and child stderr to the real stdout and
		it echos the real stdin to the child stdin.
		"""
		# Flush the buffer.
		self.write_to_stdout(self.buffer)
		self.stdout.flush()
		self._buffer = self.buffer_type()

		setwinsize(self.child_fd, term.lines, term.columns)

		try:
			self.interact_copy(output_filter)
		finally:
			term.restore_mode()

	def interact_copy(self, output_filter: Callable[[bytes], None]) -> None:
		"""Interact with the pty."""
		while self.isalive():
			try:
				ready = poll_ignore_interrupts([self.child_fd, term.STDIN])
				if self.child_fd in ready:
					try:
						data = os.read(self.child_fd, 1000)
					except OSError as err:
						if err.args[0] == errno.EIO:
							# Linux-style EOF
							break
						raise
					if data == b'':
						# BSD-style EOF
						break
					output_filter(data)
				if term.STDIN in ready:
					data = os.read(term.STDIN, 1000)
					while data != b'' and self.isalive():
						split = os.write(self.child_fd, data)
						data = data[split:]
			except KeyboardInterrupt:
				warn = color("Warning: ", 'YELLOW')
				warn += "quitting now could break your system!"
				if live.is_started:
					scroll_list.append(warn)
					scroll_list.append(color("Ctrl+C twice quickly will exit...", 'RED'))
					scroll_bar()
				else:
					term.write(b'\n'+warn.encode())
				sleep(0.5)
