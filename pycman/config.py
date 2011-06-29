#!/usr/bin/env python3
# 
# pycman - A Python implementation of Pacman
# Copyright (C) 2011 Rémy Oudompheng <remy@archlinux.org>
# 
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation; either version 2 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program; if not, write to the Free Software
#   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#

"""
pycman configuration handling

This module handles pacman.conf files as well as pycman options that
are common to all action modes.
"""

import io
import os
import glob
import sys
import argparse

import pyalpm

class InvalidSyntax(Exception):
	pass

# Options that may occur several times in a section. Their values should be
# accumulated in a list.
LIST_OPTIONS = (
	'CacheDir',
	'HoldPkg',
	'SyncFirst',
	'IgnoreGroup',
	'IgnorePkg',
	'NoExtract',
	'NoUpgrade',
	'Server'
)

SINGLE_OPTIONS = (
	'RootDir',
	'DBPath',
	'LogFile',
	'Architecture',
	'XferCommand',
	'CleanMethod',
	'VerifySig'
)

BOOLEAN_OPTIONS = (
	'UseSyslog',
	'ShowSize',
	'UseDelta',
	'TotalDownload',
	'CheckSpace'
)

def pacman_conf_enumerator(path):
	filestack = []
	current_section = None
	filestack.append(open(path))
	while len(filestack) > 0:
		f = filestack[-1]
		line = f.readline()
		if len(line) == 0:
			# end of file
			filestack.pop()
			continue

		line = line.strip()
		if len(line) == 0: continue
		if line[0] == '#':
			continue
		if line[0] == '[' and line[-1] == ']':
			current_section = line[1:-1]
			continue
		if current_section is None:
			raise InvalidSyntax(f.name, 'statement outside of a section', line)
		# read key, value
		key, equal, value = [x.strip() for x in line.partition('=')]

		# include files
		if equal == '=' and key == 'Include':
			filestack.extend(open(f) for f in glob.glob(value))
			continue
		if current_section != 'options':
			# repos only have the Server option
			if key == 'Server' and equal == '=':
				yield (current_section, 'Server', value)
			elif key == 'VerifySig' and equal == '=':
				yield (current_section, 'VerifySig', value)
			else:
				raise InvalidSyntax(f.name, 'invalid key for repository configuration', line)
			continue
		if equal == '=':
			if key in LIST_OPTIONS:
				for val in value.split():
					yield (current_section, key, val)
			elif key in SINGLE_OPTIONS:
				yield (current_section, key, value)
			else:
				print(InvalidSyntax(f.name, 'unrecognized option', key))
		else:
			if key in BOOLEAN_OPTIONS:
				yield (current_section, key, True)
			else:
				print(InvalidSyntax(f.name, 'unrecognized option', key))

class PacmanConfig(object):
	def __init__(self, conf = None, options = None):
		self.options = {}
		self.repos = {}
		self.options["RootDir"] = "/"
		self.options["DBPath"] = "/var/lib/pacman"
		self.options["LogFile"] = "/var/lib/pacman"
		self.options["Architecture"] = os.uname()[-1]
		if conf is not None:
			self.load_from_file(conf)
		if options is not None:
			self.load_from_options(options)

	def load_from_file(self, filename):
		for section, key, value in pacman_conf_enumerator(filename):
			if section == 'options':
				if key == 'Architecture' and value == 'auto':
					continue
				if key in LIST_OPTIONS:
					self.options.setdefault(key, []).append(value)
				else:
					self.options[key] = value
			else:
				servers = self.repos.setdefault(section, [])
				if key == 'Server':
					servers.append(value)

	def load_from_options(self, options):
		if options.root is not None:
			self.options["RootDir"] = options.root
		if options.dbpath is not None:
			self.options["DBPath"] = options.dbpath
		if options.arch is not None:
			self.options["Architecture"] = options.arch
		if options.logfile is not None:
			self.options["LogFile"] = options.logfile

	def apply(self, h):
		h.arch = self.options["Architecture"]
		h.logfile = self.options["LogFile"]

		# set sync databases
		for repo, servers in self.repos.items():
			db = h.register_syncdb(repo, 0)
			db_servers = []
			for rawurl in servers:
				url = rawurl.replace("$repo", repo)
				url = url.replace("$arch", self.options["Architecture"])
				db_servers.append(url)
			db.servers = db_servers

	def initialize_alpm(self):
		h = pyalpm.Handle(self.options["RootDir"], self.options["DBPath"])
		self.apply(h)
		return h

	def __str__(self):
		return("PacmanConfig(options=%s, repos=%s)" % (str(self.options), str(self.repos)))

def make_parser(*args, **kwargs):
	parser = argparse.ArgumentParser(*args, **kwargs)
	common = parser.add_argument_group('Common options')
	common.add_argument('-b', '--dbpath', metavar = '<path>',
			action = 'store', dest = 'dbpath', type = str,
			help = 'set an alternate database location')
	common.add_argument('-r', '--root', metavar = '<path>',
			action = 'store', dest = 'root', type = str,
			help = 'set an alternate installation root')
	common.add_argument('-v', '--verbose',
			action = 'store_true', dest = 'verbose', default = False,
			help = 'be verbose')
	common.add_argument('--arch', metavar = '<arch>',
			action = 'store', dest = 'arch', type = str,
			help = 'set an alternate architecture')
	common.add_argument('--config', metavar = '<file>',
			action = 'store', dest = 'config', type = str,
			help = 'set an alternate configuration file')
	common.add_argument('--logfile', metavar = '<file>',
			action = 'store', dest = 'logfile', type = str,
			help = 'set an alternate log file')
	return parser

def init_with_config(configpath):
	"Reads configuration from given path and apply it to libalpm"
	config = PacmanConfig(conf = configpath)
	return config.initialize_alpm()

def init_with_config_and_options(options):
	"Reads configuration from file and commandline options, and apply it to libalpm"
	# read config file
	if options.config is not None:
		config_file = options.config
	else:
		config_file = "/etc/pacman.conf"

	conf = PacmanConfig(conf = config_file, options = options)
	return conf.initialize_alpm()

# vim: set ts=4 sw=4 tw=0 noet:
