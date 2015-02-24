#!/usr/bin/python
from configparser import RawConfigParser

class AttrConfig(RawConfigParser):
	def __init__(self, path):
		RawConfigParser.__init__(self)
		self.read(path)
		# Add sections based on the names
		for sname in self.sections():
			if ((sname not in self.__dict__) 
					and sname.replace('_', '').isalnum() 
					and not sname.replace('_', '').isdigit() 
					and '__' not in sname): 
				self.__dict__[sname] = Section(sname, self)
			# Not already defined, # Not full of garbage, # Not a number, # Not subvertive
			
class Section:
	def __init__(self, sname, conf):
		# Add options based on the names
		for oname in conf.options(sname):
			if ((oname not in self.__dict__) 
					and oname.replace('_', '').isalnum() 
					and not oname.replace('_', '').isdigit() 
					and '__' not in oname):
				self.__dict__[oname] = conf.get(sname, oname)
				# Not already defined, # Not full of garbage, # Not a number, # Not subvertive