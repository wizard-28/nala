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
"""Functions for handling Nala History."""
from __future__ import annotations

import sys
import json
from json.decoder import JSONDecodeError
from datetime import datetime
from shutil import get_terminal_size
from typing import TYPE_CHECKING, Any

import jsbeautifier

from nala.logger import dprint
from nala.utils import ERROR_PREFIX, COLUMNS, print_packages
from nala.constants import NALA_HISTORY
from nala.rich import Table, Column, console

if TYPE_CHECKING:
	from nala.nala import Nala

def load_history_file() -> dict[str, dict[str, str | list]]:
	"""Loads Nala history"""
	try:
		return json.loads(NALA_HISTORY.read_text(encoding='utf-8'))
	except JSONDecodeError:
		sys.exit(ERROR_PREFIX+f"History file seems corrupt. You should try removing {NALA_HISTORY}")

def write_history_file(data: dict) -> None:
	"""Write history to file."""
	options = jsbeautifier.default_options()
	options.indent_size = 1
	options.indent_char = '\t'
	with open(NALA_HISTORY, 'w', encoding='utf-8') as file:
		file.write(jsbeautifier.beautify(json.dumps(data), options))

def history() -> None:
	"""Method for the history command."""
	if not NALA_HISTORY.exists():
		print("No history exists..")
		return
	history_file = load_history_file()
	names = []

	for key, entry in history_file.items():
		command = entry.get('Command')
		if command[0] in ('update', 'upgrade'):
			for package in entry.get('Upgraded'):
				command.append(package[0])
		names.append(
				(key,' '.join(command), entry.get('Date'), str(entry.get('Altered')))
		)

	max_width = get_terminal_size().columns - 50
	history_table = Table(
				'ID:',
				Column('Command:', no_wrap=True, max_width=max_width),
				'Date and Time:',
				'Altered:',
				padding=(0,2), box=None
			)

	for item in names:
		history_table.add_row(*item)
	console.print(history_table)

def history_info(hist_id: str) -> None:
	"""Method for the history info command."""
	dprint(f"History info {hist_id}")
	hist_entry = get_history(hist_id)
	dprint(f"History Entry: {hist_entry}")

	delete_names: list[list[str]] = hist_entry.get('Removed', [['None']])
	install_names: list[list[str]] = hist_entry.get('Installed', [['None']])
	upgrade_names: list[list[str]] = hist_entry.get('Upgraded', [['None']])

	print_packages(
		['Package:', 'Version:', 'Size:'],
		delete_names, 'Removed:', 'bold red')
	print_packages(
		['Package:', 'Version:', 'Size:'],
		install_names, 'Installed:', 'bold green')
	print_packages(
		['Package:', 'Old Version:', 'New Version:', 'Size:'],
		upgrade_names, 'Upgraded:', 'bold blue'
	)

	print('='*COLUMNS)
	if delete_names:
		print(f'Removed {len(delete_names)} Packages')
	if install_names:
		print(f'Installed {len(install_names)} Packages')
	if upgrade_names:
		print(f'Upgraded {len(upgrade_names)} Packages')

def history_clear(hist_id: str) -> None:
	"""Method for the show command."""
	dprint(f"History clear {hist_id}")
	if not NALA_HISTORY.exists():
		print("No history exists to clear..")
		return

	if hist_id == 'all':
		NALA_HISTORY.unlink()
		print("History has been cleared")
		return

	history_file: dict = json.loads(NALA_HISTORY.read_text(encoding='utf-8'))
	history_edit = {}
	num = 0
	# Using sum increments to relabled the IDs so when you remove just one
	# There isn't a gap in ID numbers and it looks concurrent.
	for key, value in history_file.items():
		if key != hist_id:
			num += 1
			history_edit[num] = value

	write_history_file(history_edit)

def history_undo(apt: Nala, hist_id: str, redo: bool = False):
	"""Method for the history undo/redo commands."""
	if redo:
		dprint(f"History: redo {hist_id}")
	else:
		dprint(f"History: undo {hist_id}")
	transaction = get_history(hist_id)
	dprint(f"Transaction: {transaction}")

	command = transaction.get('Command')[0]
	# We just reverse whatever was done in the transaction
	if command == 'remove':
		pkgs = (pkg[0] for pkg in transaction.get('Removed'))
		if redo:
			apt.remove(pkgs)
		else:
			apt.install(pkgs)

	elif command == 'install':
		pkgs = (pkg[0] for pkg in transaction.get('Installed'))
		if redo:
			apt.install(pkgs)
		else:
			apt.remove(pkgs)
	else:
		print('\nUndo for operations other than install or remove are not currently supported')

def write_history(delete_names: list[list[str | int]],
	install_names: list[list[str | int]], upgrade_names: list[list[str | int]]) -> None:
	"""Prepare history for writing."""
	# We don't need only downloads in the history
	if '--download-only' in sys.argv[1:]:
		return
	timezone = datetime.utcnow().astimezone().tzinfo
	time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')+' '+str(timezone)
	history_dict = load_history_file() if NALA_HISTORY.exists() else {}
	hist_id = len(history_dict) + 1 if history_dict else 1
	altered = len(delete_names) + len(install_names) + len(upgrade_names)

	transaction = {
		'Date' : time,
		'Command' : sys.argv[1:],
		'Altered' : altered,
		'Removed' : delete_names,
		'Installed' : install_names,
		'Upgraded' : upgrade_names,
	}

	history_dict[hist_id] = transaction
	write_history_file(history_dict)

def get_history(hist_id: str) -> dict[str, Any]:
	"""Method for getting the history from file."""
	dprint(f"Getting history {hist_id}")
	if not NALA_HISTORY.exists():
		sys.exit("No history exists..")
	history_file: dict = json.loads(NALA_HISTORY.read_text(encoding='utf-8'))
	transaction = history_file.get(hist_id)
	if transaction:
		return transaction
	sys.exit(ERROR_PREFIX+f"Transaction {hist_id} doesn't exist.")
