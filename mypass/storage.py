# Copyright (c) 2014 Sebastian Noack
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 3 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
# for more details.

import os
import json
import struct

import Crypto.Cipher.AES
import Crypto.Hash.HMAC
import Crypto.Hash.SHA256
import Crypto.Protocol.KDF

from mypass import CredentialsDoNotExist, CredentialsAlreadytExist, WrongPassphraseOrBrokenDatabase
from mypass import DATABASE

KEY_SIZE = 32
SALT_SIZE = 48
ITERATIONS = 10000

SINGLE_PASSWORD = ''

class Database:
	_header_struct = struct.Struct('{}s{}s'.format(SALT_SIZE, Crypto.Cipher.AES.block_size))

	def __init__(self):
		self._data = {}

	def _init_key(self, passphrase, salt):
		self._key = Crypto.Protocol.KDF.PBKDF2(
			passphrase.encode('utf-8'), salt, KEY_SIZE, ITERATIONS,
			lambda p, s: Crypto.Hash.HMAC.new(p, s, Crypto.Hash.SHA256).digest()
		)
		self._salt = salt

	def _get_cipher(self, iv):
		return Crypto.Cipher.AES.new(self._key, Crypto.Cipher.AES.MODE_CBC, iv)

	def _write(self):
		block_size = Crypto.Cipher.AES.block_size

		plaintext = json.dumps(dict(self._data.values()), ensure_ascii=False).encode('utf-8')
		plaintext += b' ' * (block_size - len(plaintext) % block_size)

		iv = os.urandom(block_size)
		ciphertext = self._get_cipher(iv).encrypt(plaintext)

		try:
			file = open(DATABASE, 'wb')
		except FileNotFoundError:
			os.makedirs(os.path.dirname(DATABASE))
			file = open(DATABASE, 'wb')

		with file:
			file.write(self._salt)
			file.write(iv)
			file.write(ciphertext)

	def get_credentials(self, domain):
		try:
			credentials = self._data[domain.lower()][1]
		except KeyError:
			raise CredentialsDoNotExist

		return sorted(credentials.items(), key=lambda token: token[0])

	def get_domains(self):
		return [domain for _, (domain, _) in sorted(self._data.items(), key=lambda pair: pair[0])]

	def store_credentials(self, domain, username, password, override=False):
		domain_lower = domain.lower()

		if domain_lower not in self._data:
			credentials = {}
		else:
			credentials = self._data[domain_lower][1]

			if not override and username in credentials:
				raise CredentialsAlreadytExist

			if SINGLE_PASSWORD in credentials:
				if not override:
					raise CredentialsAlreadytExist

				credentials = {}

		credentials[username] = password
		self._data[domain_lower] = (domain, credentials)
		self._write()

	def store_password(self, domain, password, override=False):
		domain_lower = domain.lower()

		if not override and domain_lower in self._data:
			raise CredentialsAlreadytExist

		self._data[domain_lower] = (domain, {SINGLE_PASSWORD: password})
		self._write()

	def delete_credentials(self, domain, username):
		domain_lower = domain.lower()

		try:
			credentials = self._data[domain_lower][1]
			del credentials[username]
		except KeyError:
			raise CredentialsDoNotExist

		if not credentials:
			del self._data[domain_lower]

		self._write()

	def delete_domain(self, domain):
		try:
			del self._data[domain.lower()]
		except KeyError:
			raise CredentialsDoNotExist

		self._write()

	def change_passphrase(self, passphrase):
		self._init_key(passphrase, os.urandom(SALT_SIZE))
		self._write()

	@classmethod
	def decrypt(cls, ciphertext, passphrase):
		try:
			salt, iv = cls._header_struct.unpack_from(ciphertext)
		except struct.error:
			raise WrongPassphraseOrBrokenDatabase

		db = cls()
		db._init_key(passphrase, salt)

		cipher = db._get_cipher(iv)
		ciphertext = ciphertext[cls._header_struct.size:]

		try:
			data = json.loads(cipher.decrypt(ciphertext).decode('utf-8'))
		except ValueError:
			raise WrongPassphraseOrBrokenDatabase

		if not isinstance(data, dict):
			raise WrongPassphraseOrBrokenDatabase

		for domain, credentials in data.items():
			db._data[domain.lower()] = (domain, credentials)

		return db

	@classmethod
	def create(cls, passphrase):
		db = cls()
		db.change_passphrase(passphrase)
		return db