from __future__ import annotations

import asyncio
import re
import sys
from asyncio import Semaphore, gather
from pathlib import Path
from random import shuffle
from typing import Pattern

import aiofiles
import apt_pkg
from apt.package import Package, Version
from httpx import (AsyncClient, ConnectTimeout,
				HTTPStatusError, RequestError, get)

from nala.constants import ARCHIVE_DIR, ERROR_PREFIX, PARTIAL_DIR
from nala.rich import Live, Spinner, Table, pkg_download_progress
from nala.utils import (check_pkg, color, dprint,
				get_pkg_name, pkg_candidate, unit_str, vprint)

MIRROR_PATTERN = re.compile(r'mirror://([A-Za-z_0-9.-]+).*')

class PkgDownloader:
	"""Manage Package Downloads."""

	def __init__(self, pkgs: list[Package]) -> None:
		"""Manage Package Downloads."""
		self.pkgs = pkgs
		self.total_size: int = sum(pkg_candidate(pkg).size for pkg in self.pkgs)
		self.total_pkgs: int = len(self.pkgs)
		self.count: int = 0
		self.live: Live
		self.task = pkg_download_progress.add_task(
			"[bold][blue]Downloading [green]Packages",
			total=self.total_size
		)
		self.pkg_urls: list[list[Version | str]] = []
		self._set_pkg_urls()

		self.pkg_urls = sorted(self.pkg_urls, key=sort_pkg_size, reverse=True)
		http_proxy = apt_pkg.config.find('Acquire::http::Proxy')
		https_proxy = apt_pkg.config.find('Acquire::https::Proxy', http_proxy)
		ftp_proxy = apt_pkg.config.find('Acquire::ftp::Proxy')

		self.proxy: dict[str, str] = {
			'http' : http_proxy,
			'https' : https_proxy,
			'ftp' : ftp_proxy
		}

	async def start_download(self) -> bool:
		"""Start async downloads."""
		if not self.pkgs:
			return True
		concurrent = min(guess_concurrent(self.pkg_urls), 16)
		semaphore = Semaphore(concurrent)
		starting_downloads = Spinner('dots', color('Starting Downloads...', 'BLUE'))
		with Live() as self.live:
			async with AsyncClient(follow_redirects=True, timeout=20) as client:
				self.live.update(starting_downloads)
				loop = asyncio.get_running_loop()
				tasks = (
					loop.create_task(
						self._download(client, urls, semaphore)
					) for urls in self.pkg_urls
				)
				await gather(*tasks)

				return all(
					await gather(
						*(self.process_downloads(pkg) for pkg in self.pkgs)
					)
				)

	async def process_downloads(self, pkg: Package) -> bool:
		"""Process the downloaded packages."""
		filename = get_pkg_name(pkg_candidate(pkg))
		destination = ARCHIVE_DIR / filename
		source = PARTIAL_DIR / filename
		try:
			dprint(f'Moving {source} -> {destination}')
			source.rename(destination)
		except OSError as error:
				print(ERROR_PREFIX+f"Failed to move archive file {error}")
				return False
		return True

	async def _download(self, client: AsyncClient,
		urls: list[Version | str], semaphore: Semaphore) -> None:
		"""Download pkgs."""
		candidate = urls.pop(0)
		assert isinstance(candidate, Version)
		dest = PARTIAL_DIR / get_pkg_name(candidate)
		for num, url in enumerate(urls):
			try:
				async with semaphore:
					vprint(
						color('Starting Download: ', 'BLUE')
						+f"{url} {unit_str(candidate.size, 1)}")
					assert isinstance(url, str)
					async with client.stream('GET', url) as response:
						async with aiofiles.open(dest, mode="wb") as file:
							async for data in response.aiter_bytes():
								if data:
									await file.write(data)

				if not check_pkg(PARTIAL_DIR, candidate):
					continue

				vprint(
					color('Download Complete: ', 'GREEN')
					+url
				)
				await self._update_progress(dest.name, candidate.size)
				break

			except ConnectTimeout:
				print(color('Mirror Timedout:', 'YELLOW'), url)
				check_index(num, urls, candidate)
				continue
			except (HTTPStatusError, RequestError, OSError) as error:
				msg = str(error) or type(error).__name__
				print(ERROR_PREFIX+msg)
				check_index(num, urls, candidate)
				continue

	def _set_pkg_urls(self) -> None:
		"""Set pkg_urls list."""
		mirrors: list[str] = []
		for pkg in self.pkgs:
			candidate = pkg_candidate(pkg)
			urls: list[str] = []
			urls.extend(filter_uris(candidate, mirrors, MIRROR_PATTERN))
			# Randomize the urls to minimize load on a single mirror.
			shuffle(urls)
			urls.insert(0, candidate)
			self.pkg_urls.append(urls)

	def _gen_table(self, pkg_name: str) -> Table:
		"""Generate Rich Table."""
		table = Table.grid()
		table.add_row(f"{color('Total Packages:', 'GREEN')} {self.count}/{self.total_pkgs}")
		table.add_row(f"{color('Last Completed:', 'GREEN')} {pkg_name}")
		table.add_row(pkg_download_progress.get_renderable())
		return table

	async def _update_progress(self, pkg_name: str, size: int) -> None:
		"""Update download progress."""
		pkg_download_progress.advance(self.task, advance=size)
		self.count += 1
		self.live.update(
			self._gen_table(pkg_name)
		)

def check_index(num: int, urls: list[Version | str], candidate: Version) -> None:
	"""Check if there is more urls in the list."""
	try:
		next_url = urls[num+1]
	except IndexError:
		print('No more mirrors for...', Path(candidate.filename).name)
		return
	print(color('Trying:', 'YELLOW'), next_url)

def filter_uris(candidate: Version, mirrors: list[str], pattern: Pattern[str]) -> list[str]:
	"""Filter uris into usable urls."""
	urls: list[str] = []
	for uri in candidate.uris:
		# Regex to check if we're using mirror.txt
		regex = pattern.search(uri)
		if regex:
			domain = regex.group(1)
			if not mirrors:
				try:
					mirrors = get(f"http://{domain}/mirrors.txt").text.splitlines()
				except ConnectionError:
					sys.exit(ERROR_PREFIX+f'unable to connect to http://{domain}/mirrors.txt')
			urls.extend([link+candidate.filename for link in mirrors])
			continue
		urls.append(uri)
	return urls

class IntegrityError(Exception):
	"""Exception for integrity checking."""

def guess_concurrent(pkg_urls: list[list[Version | str]]) -> int:
	"""Determine how many concurrent downloads to do."""
	max_uris = 2
	for pkg in pkg_urls:
		max_uris = max(len(pkg[1:])*2, max_uris)
	return max_uris

def sort_pkg_size(pkg_url: list[Version | str]) -> int:
	"""Sort by package size.

	This is to be used as sorted(key=sort_pkg_size)
	"""
	candidate = pkg_url[0]
	assert isinstance(candidate, Version)
	assert isinstance(candidate.size, int)
	return candidate.size
