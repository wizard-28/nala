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

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from pydoc import pager

from nala import __version__
from nala.utils import LICENSE


# Custom Parser for printing help on error.
class nalaParser(argparse.ArgumentParser):
	def error(self, message):
		sys.stderr.write(f'error: {message}\n')
		self.print_help()
		sys.exit(1)

# Custom Action for --license switch
class GPLv3(argparse.Action):
	def __init__(self,
			option_strings,
			dest=argparse.SUPPRESS,
			default=argparse.SUPPRESS,
			help='reads the GPLv3'):
		super().__init__(
			option_strings=option_strings,
			dest=dest,
			default=default,
			nargs=0,
			help=help)

	def __call__(self, parser, args, values, option_string=None):
		if LICENSE.exists():
			with open(LICENSE) as file:
				pager(file.read())
		else:
			print('It seems the system has no license file')
			print('Nala is licensed under the GPLv3')
			print('https://www.gnu.org/licenses/gpl-3.0.txt')
		parser.exit()

def remove_options(parser,
	assume_yes=True, download_only=True,
	update=True, no_update=True,
	raw_dpkg=True, noninteractive=True):

	for item in parser._optionals._group_actions[:]:
		if assume_yes and '--assume-yes' in item.option_strings:
			parser._optionals._group_actions.remove(item)
		if download_only and '--download-only' in item.option_strings:
			parser._optionals._group_actions.remove(item)
		if no_update and '--no-update' in item.option_strings:
			parser._optionals._group_actions.remove(item)
		if update and '--update' in item.option_strings:
			parser._optionals._group_actions.remove(item)
		if raw_dpkg and '--raw-dpkg' in item.option_strings:
			parser._optionals._group_actions.remove(item)
		if noninteractive:
			for switch in ('--noninteractive', '--noninteractive-full', '--confold', '--confnew', '--confdef', '--confask', '--confmiss'):
				if switch in item.option_strings:
					parser._optionals._group_actions.remove(item)

# Main Parser
def arg_parse():

	formatter = lambda prog: argparse.RawDescriptionHelpFormatter(prog, max_help_position=64)

	bin_name = Path(sys.argv[0]).name

	version = __version__

	# Define global options to be given to subparsers
	global_options = nalaParser(add_help=False)
	global_options.add_argument('-y', '--assume-yes', action='store_true', help="assume 'yes' to all prompts and run non-interactively.")
	global_options.add_argument('-d', '--download-only', action='store_true', help="package files are only retrieved, not unpacked or installed")
	global_options.add_argument('-v', '--verbose', action='store_true', help='Logs extra information for debugging')
	global_options.add_argument('--no-update', action='store_true', help="skips updating the package list")
	global_options.add_argument('--raw-dpkg', action='store_true', help="skips all formatting and you get raw dpkg output")
	global_options.add_argument('--update', action='store_true', help="updates the package list")
	global_options.add_argument('--debug', action='store_true', help='Logs extra information for debugging')
	global_options.add_argument('--version', action='version', version=f'{bin_name} {version}')
	global_options.add_argument('--license', action=GPLv3)

	# Define interactive options
	interactive_options = nalaParser(add_help=False)
	interactive_options.add_argument('--no-aptlist', action='store_true', help="sets 'APT_LISTCHANGES_FRONTEND=none'. apt-listchanges will not bug you")
	interactive_options.add_argument('--noninteractive', action='store_true', help="sets 'DEBIAN_FRONTEND=noninteractive'. this also disables apt-listchanges")
	interactive_options.add_argument('--noninteractive-full', action='store_true', help="an alias for --noninteractive --confdef --confold")
	interactive_options.add_argument('--confold', action='store_true', help="always keep the old version without prompting")
	interactive_options.add_argument('--confnew', action='store_true', help="always install the new version without prompting")
	interactive_options.add_argument('--confdef', action='store_true', help="always choose the default action without prompting")
	interactive_options.add_argument('--confmiss', action='store_true', help="always install the missing conffile without prompting. this is dangerous")
	interactive_options.add_argument('--confask', action='store_true', help="always offer to replace it with the version in the package")
	interactive_options._action_groups[1].title = 'dpkg options'
	interactive_options._action_groups[1].description = 'read the man page if you are unsure about these options'

	parser = nalaParser(	formatter_class=formatter,
							usage=f'{bin_name} [--options] <command>',
							parents=[global_options, interactive_options]
							)

	# We need a special iteration to remove the interactive_options from the global --help
	for group in parser._action_groups[:]:
		if group.title == 'dpkg options':
			group._group_actions.clear()
			group.title = None
			group.description = None

	# Define our subparser
	subparsers = parser.add_subparsers(metavar='', dest='command')

	# Parser for the install command
	install_parser = subparsers.add_parser('install',
		formatter_class=formatter,
		help='install packages',
		parents=[global_options, interactive_options],
		usage=f'{bin_name} install [--options] pkg1 [pkg2 ...]'
		)

	install_parser.add_argument('args', metavar='pkg(s)', nargs='*', help='package(s) to install')

	remove_options(
		install_parser, assume_yes=False,
		download_only=False, update=False,
		no_update=True, raw_dpkg=False, noninteractive=False
	)

	# Parser for the remove command
	remove_parser = subparsers.add_parser('remove',
		formatter_class=formatter,
		help='remove packages', parents=[global_options, interactive_options],
		usage=f'{bin_name} remove [--options] pkg1 [pkg2 ...]'
	)

	# Remove Global options that I don't want to see in remove --help
	remove_options(remove_parser, assume_yes=False, update=False, raw_dpkg=False)

	remove_parser.add_argument('args',
		metavar='pkg(s)',
		nargs='*',
		help='package(s) to remove')

	# Parser for the purge command
	purge_parser = subparsers.add_parser('purge',
		formatter_class=formatter,
		help='purge packages', parents=[global_options, interactive_options],
		usage=f'{bin_name} remove [--options] pkg1 [pkg2 ...]'
	)

	# Remove Global options that I don't want to see in purge --help
	remove_options(remove_parser, assume_yes=False, update=False, raw_dpkg=False)

	purge_parser.add_argument('args',
		metavar='pkg(s)',
		nargs='*',
		help='package(s) to purge')

	# We specify the options as a parent parser first just so we can easily move them above the global options inside the subparser help.
	# If there is a better way of doing this please let me know
	update_options = nalaParser(add_help=False)
	update_options.add_argument(
		'--no-full',
		action='store_false',
		help="R|runs a normal upgrade instead of full-upgrade\n\n"
	)

	# Parser for the update/upgrade command
	update_parser = subparsers.add_parser(
		'update',
		formatter_class=formatter,
		help='update package list and upgrade the system',
		parents=[update_options, global_options, interactive_options],
		usage=f'{bin_name} update [--options]'
	)

	remove_options(
		update_parser, assume_yes=False,
		download_only=False, update=True,
		no_update=False, raw_dpkg=False, noninteractive=False
	)

	upgrade_parser = subparsers.add_parser(
		'upgrade',
		formatter_class=formatter,
		help='alias for update',
		parents=[update_options, global_options, interactive_options],
		usage=f'{bin_name} upgrade [--options]'
	)

	remove_options(
		upgrade_parser, assume_yes=False,
		download_only=False, update=True,
		no_update=False, raw_dpkg=False, noninteractive=False
	)

	# We do the same thing that we did with update options
	fetch_options = nalaParser(add_help=False)
	fetch_options.add_argument('--fetches', metavar='number', type=int, default=3, help="number of mirrors to fetch")
	fetch_options.add_argument('--debian', metavar='sid', help="choose the Debian release")
	fetch_options.add_argument('--ubuntu', metavar='jammy', help="choose an Ubuntu release")
	fetch_options.add_argument('--country', metavar='US', help="choose only mirrors of a specific ISO country code")
	fetch_options.add_argument('--foss', action='store_true', help="omits contrib and non-free repos\n\n")

	# Parser for the fetch command
	fetch_parser = subparsers.add_parser('fetch',
		formatter_class=formatter,
		description=(
		'nala will fetch mirrors with the lowest latency.\n'
		'for Debian https://www.debian.org/mirror/list-full\n'
		'for Ubuntu https://launchpad.net/ubuntu/+archivemirrors'
		),
		help='fetches fast mirrors to speed up downloads',
		parents=[fetch_options, global_options],
		usage=f'{bin_name} fetch [--options]'
	)
	# Remove Global options that I don't want to see in fetch --help
	remove_options(fetch_parser)

	# Parser for the show command
	show_parser = subparsers.add_parser(
		'show',
		help='show package details',
		parents=[global_options, interactive_options],
		usage=f'{bin_name} show [--options] pkg1 [pkg2 ...]'
	)
	# Remove Global options that I don't want to see in show --help
	remove_options(show_parser, update=False)

	show_parser.add_argument('args', metavar='pkg(s)', nargs='*', help='package(s) to show')

	# Parser for the History command
	history_parser = subparsers.add_parser(
		'history',
		help='show transaction history',
		description='history without additional commands lists a history summary',
		parents=[global_options, interactive_options],
		usage=f'{bin_name} history [--options] <command> <id|all>'
	)

	# Remove Global options that I don't want to see in history --help
	remove_options(history_parser, update=False)

	history_parser.add_argument('mode', metavar='info <id>', nargs='?', help='action you would like to do on the history')
	history_parser.add_argument('id', metavar='undo <id>', nargs='?', help='undo a transaction')
	history_parser.add_argument('placeholder', metavar='redo <id>', nargs='?', help='redo a transaction')
	history_parser.add_argument('placeholder2', metavar='clear <id>|all', nargs='?', help='clear a transaction or the entire history')

	# Parser for the show command
	clean_parser = subparsers.add_parser(
		'clean',
		help='clears out the local repository of retrieved package files.',
		parents=[global_options],
		usage=f'{bin_name} show [--options]'
	)

	# Remove Global options that I don't want to see in clean --help
	remove_options(clean_parser)

	# This is just moo, but we can't cause are cat
	moo_parser = subparsers.add_parser(
		'moo',
		description='nala is unfortunately unable to moo',
		parents=[global_options],
		usage=f'{bin_name} moo [--options]'
	)
	moo_parser.add_argument('moo', nargs='*', help=argparse.SUPPRESS)

	for item in (
		install_parser, remove_parser,
		update_parser, upgrade_parser,
		moo_parser, fetch_parser, purge_parser,
		show_parser, clean_parser, history_parser):

		item._positionals.title = "arguments"
		item._optionals.title = "options"
	parser._subparsers.title = "commands"

	return parser

parser = arg_parse()
arguments = parser.parse_args()
