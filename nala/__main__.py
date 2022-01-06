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
"""The main module for Nala."""
from __future__ import annotations

import sys
from getpass import getuser
from os import geteuid
from typing import NoReturn

from nala.fetch import fetch
from nala.logger import dprint, esyslog
from nala.nala import iter_remove, nala
from nala.options import arguments, parser
from nala.utils import (CAT_ASCII, LION_ASCII, LION_ASCII2, ERROR_PREFIX,
				ARCHIVE_DIR, LISTS_PARTIAL_DIR, PARTIAL_DIR, PKGCACHE, SRCPKGCACHE)


def _main() -> NoReturn:
	"""This is the main Nala function."""
	if not arguments.command and not arguments.update:
		parser.print_help()
		sys.exit(1)

	dprint(f"Argparser = {arguments}")
	superuser= ('update', 'upgrade', 'install', 'remove', 'fetch', 'clean')
	apt_init = ('update', 'upgrade', 'install', 'remove', 'show', 'history', 'purge', None)

	sudo = geteuid()
	if arguments.command in superuser:
		sudo_check(sudo, arguments.command)

	if arguments.command in apt_init:
		apt_command(sudo)
	else:
		not_apt_command()

def apt_command(sudo: int) -> NoReturn:
	"""Commands that require initializing the apt cache."""
	apt = init_apt()
	if arguments.command in ('update', 'upgrade'):
		apt.upgrade(dist_upgrade=arguments.no_full)

	elif arguments.command == 'install':
		arg_check(arguments.args, 'install')
		apt.install(arguments.args)

	elif arguments.command in ('remove', 'purge'):
		purge = arguments.command == 'purge'
		args = arguments.args
		apt.remove(args, purge=purge)

	elif arguments.command == 'show':
		arg_check(arguments.args, 'show')
		apt.show(arguments.args)

	elif arguments.command == 'history':
		history(apt, sudo)

	elif not arguments.update:
		sys.exit(ERROR_PREFIX+'unknown error in "apt_command" function')
	sys.exit(0)

def not_apt_command() -> NoReturn:
	"""Commands that do not require initializing the apt cache."""
	if arguments.command == 'clean':
		clean()
	elif arguments.command == 'fetch':
		fetch()
	elif arguments.command == 'moo':
		moo_pls()
	else:
		sys.exit(ERROR_PREFIX+'unknown error in "apt_command" function')
	sys.exit(0)

def arg_check(args, msg) -> NoReturn | None:
	"""Checks arguments and errors if no packages are specified."""
	if not args:
		sys.exit(ERROR_PREFIX+f'You must specify a package to {msg}')

def clean() -> None:
	"""Find and delete cache files."""
	iter_remove(ARCHIVE_DIR, arguments.verbose)
	iter_remove(PARTIAL_DIR, arguments.verbose)
	iter_remove(LISTS_PARTIAL_DIR, arguments.verbose)
	if arguments.verbose:
		print(f'Removing {PKGCACHE}')
		print(f'Removing {SRCPKGCACHE}')
	elif arguments.debug:
		dprint(f'Removing {PKGCACHE}')
		dprint(f'Removing {SRCPKGCACHE}')
	PKGCACHE.unlink(missing_ok=True)
	SRCPKGCACHE.unlink(missing_ok=True)
	print("Cache has been cleaned")

def history(apt: nala, sudo:int) -> None | NoReturn:
	"""Function for coordinating the history command."""
	hist_id = arguments.id
	mode = arguments.mode

	if mode and not hist_id:
		sys.exit(ERROR_PREFIX+'We need a transaction ID..')

	if mode in ('undo', 'redo', 'info'):
		try:
			hist_id = int(hist_id)
		except ValueError:
			sys.exit(ERROR_PREFIX+'Option must be a number..')
	else:
		apt.history()
	if mode == 'undo':
		apt.history_undo(hist_id)

	elif mode == 'redo':
		apt.history_undo(hist_id, redo=True)

	elif mode == 'info':
		apt.history_info(hist_id)

	elif mode == 'clear':
		sudo_check(sudo, 'clear history')
		apt.history_clear(hist_id)

def sudo_check(sudo: int, root_action: str) -> None | NoReturn:
	"""Checks for root and exits if not root."""
	if sudo != 0:
		esyslog(f'{getuser()} tried to run [{" ".join(sys.argv)}] without permission')
		sys.exit(ERROR_PREFIX+f'Nala needs root to {root_action}')

def init_apt() -> nala:
	"""Initializes nala and determines if we update the cache or not."""
	no_update_list = ('remove', 'show', 'history', 'install', 'purge')
	no_update = arguments.no_update
	if arguments.command in no_update_list:
		no_update = True
	if arguments.update:
		no_update = False

	return nala(
		download_only=arguments.download_only,
		assume_yes=arguments.assume_yes,
		no_update=no_update,
		debug=arguments.debug,
		verbose=arguments.verbose,
		raw_dpkg=arguments.raw_dpkg
	)

def moo_pls() -> None:
	"""Pls moo."""
	moos = arguments.moo
	moos = moos.count('moo')
	dprint(f"moo number is {moos}")
	if moos == 1:
		print(LION_ASCII)
	elif moos == 2:
		print(LION_ASCII2)
	else:
		print(CAT_ASCII)
	print('..."I can\'t moo for I\'m a cat"...')
	if arguments.no_update:
		print("...What did you expect no-update to do?...")
	if arguments.update:
		print("...What did you expect to update?...")

def main():
	"""Main Nala function to reference from the entry point."""
	try:
		_main()
	except KeyboardInterrupt:
		print('\nExiting at your request')
		sys.exit(130)
