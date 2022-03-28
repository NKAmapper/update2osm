#!/usr/bin/env python3
# -*- coding: utf8

# update2osm
# Compares input file with corresponding dataset in OSM and produces updated file.
# Finds a "ref:" tag in input file and uses this tag to match with data in OSM.
# Deletes tags from OSM object which are not present in input file (only if tag is part of the input dataset).
# "Equal prefix rule": If e.g. "fuel:diesel" is part of input dataset, then all "fuel:" tags must be part of the input dataset to survive.

# Usage: python update_ref.py [input_filename.osm] [country]
# Input file name must end with .osm
# Output file name is appended with "_update.osm"
# Default country is "Norge" - optional country argument must match name=* in OSM country relation
# Detailed log file: "_update_log.txt" + date


import json
import sys
import urllib.request, urllib.parse
import copy
import time
from xml.etree import ElementTree as ET


version = "1.1.0"

header = {"User-Agent": "osm-no/update2osm"}

country = "Norge"  # Used in Overpass query; must match country relation name in OSM ("Norge", "Sverige")



def message (line):
	'''
	Output message
	'''

	sys.stdout.write (line)
	sys.stdout.flush()



def load_file(input_filename):
	'''
	Load input file with update data.
	'''

	global ref_key, input_keys, input_elements

	# First loop all input nodes to copy data and produce tag inventory

	message ("Loading file ...\n")

	tree = ET.parse(input_filename)
	root = tree.getroot()

	ref_key = ""
	input_keys = []
	input_elements = []
	ref_input_count = 0

	for node in root.iter('node'):
		entry = {}
		entry['lat'] = float(node.get('lat'))
		entry['lon'] = float(node.get('lon'))
		entry['tags'] = {}

		for tag in node.iter('tag'):
			key = tag.get('k')
			entry['tags'][key] = tag.get('v')

			if key[0:4] == "ref:":
				if ref_key and (ref_key != key):
					message ("More than one ref: key found - '%s' and '%s'" % (ref_key, key))
					sys.exit()
				ref_key = key
				ref_input_count += 1

			colon = key.find(":")
			if colon >= 0:
				key = key[0:colon + 1]  # Keep prefix only, will match all keys with equal prefix (e.g. "fuel:xxx")

			if (key != key.upper()) and (key != "ref:"):
				input_keys.append(key)

		input_elements.append(entry)

	message ("\tRef tag found: '%s'\n" % ref_key)
	message ("\t%i elements loaded from input file '%s'" % (len(input_elements), input_filename))
	if ref_input_count < len(input_elements):
		message (" (%i with %s key)\n" % (ref_input_count, ref_key))
	else:
		message ("\n")

	if not(ref_key):
		message ("*** No ref: key found\n")
		sys.exit()



def load_overpass():
	'''
	Load existing OSM data for given ref from Overpass.
	'''

	global osm_data

	# Get all existing object from Overpass

	message ("Loading from Overpass for %s ...\n" % country)
	query = '[out:json][timeout:60];(area[admin_level=2][name=%s];)->.a;(nwr["%s"](area.a););(._;<;);(._;>;);out meta;' % (country, ref_key)
	request = urllib.request.Request('https://overpass-api.de/api/interpreter?data=' + urllib.parse.quote(query), headers=header)
	file = urllib.request.urlopen(request)
	osm_data = json.load(file)
	file.close()

	ref_osm_count = 0
	for element in osm_data['elements']:
		if ("tags" in element) and (ref_key in element['tags']):
			ref_osm_count += 1

	message ("\t%i elements in OSM with %s" % (ref_osm_count, ref_key))
	if len(osm_data['elements']) > ref_osm_count:
		message (", + %i connected elements\n" % (len(osm_data['elements']) - ref_osm_count))
	else:
		message ("\n")



def merge(log_filename):
	'''
	Merge input file with existing OSM elements based on ref tag.
	Generate also log file with details of conflation.
	'''

	message ("Merging data ...\n")

	# Loop through all elements in input file and compare with osm data

	log_file = open(log_filename, "w")
	log_file.write("Log file for updating %s file on %s \n" % (input_filename, today_date))

	updated = 0
	added = 0
	not_found = 0

	node_id = -1000

	for input_element in input_elements:
		found = False

		if ref_key in input_element['tags']:

			# Loop osm data until matching element is found

			modified = False
			log_file.write ("\n%s=%s\n" % (ref_key, input_element['tags'][ref_key]))

			for osm_element in osm_data['elements']:
				if ("tags" in osm_element) and (ref_key in osm_element['tags']) and (osm_element['tags'][ref_key] == input_element['tags'][ref_key]):

					if ref_key == "ref:toll":
						log_file.write ("  Match with OSM id: %i\n" % osm_element['id'])

					# Loop tags of existing osm element and replace keys/values, or delete if within tag scope of tags in input file

					new_tags = copy.deepcopy(osm_element['tags'])
					for key, value in osm_element['tags'].items():

						colon = key.find(':')
						if colon >= 0:
							prefix_key = key[0:colon + 1]  # Prefix only, e.g. "fuel:"
						else:
							prefix_key = key

						# New tag value for existing key
						# Keep https url's

						if key in input_element['tags']:
							if value != input_element['tags'][key]:
								if not ((key in ['website', 'url', 'contact:website']) and\
										((value == input_element['tags'][key].replace("http", "https")) or\
										(value == input_element['tags'][key].replace("http", "https") + "/") or\
										(value == input_element['tags'][key].replace("http://", "https://www.")) or\
										(value == input_element['tags'][key].replace("http://", "https://www.") + "/")) or\
										(ref_key == "ref:toll" and key == "name")):
									new_tags[key] = input_element['tags'][key]
									modified = True
									log_file.write ("    Replaced: %s='%s' with '%s'\n" % (key, value, input_element['tags'][key]))
								else:
									log_file.write ("    Keep:     %s='%s'\n" % (key, value))

						# Tag not found, and to be deleted if within scope of input tags
						# Keep 4 tags for YX/7-Eleven stations and 2 tags for schools

						elif prefix_key in input_keys:
							if not(("brand" in input_element['tags']) and (input_element['tags']['brand'] == "YX 7-Eleven") and\
									(key in ['phone', 'email'])):
								del new_tags[key]
								modified = True
								log_file.write ("    Deleted:  %s='%s'\n" % (key, value))
							else:
								log_file.write ("    Keep:     %s='%s'\n" % (key, value))

					# Add new tags to osm element

					for key, value in input_element['tags'].items():
						if not(key in new_tags) and (key != key.upper()):
							new_tags[key] = value
							modified = True
							log_file.write ("    Added:    %s='%s'\n" % (key, value))

					osm_element['match'] = True
					osm_element['tags'] = new_tags
					if modified:
						osm_element['modify'] = True
						updated += 1
					found = True

					if ref_key != "ref:toll":  # Several occurances of ref:toll
						break

		else:
			log_file.write ("\nNO %s KEY\n" % ref_key.upper())  # Ref: not found in input file for this element

		# Append new element if not already in osm

		if not(found):
			node_id -= 1
			input_element['id'] = node_id
			input_element['type'] = "node"
			input_element['modify'] = True
			added += 1
			osm_data['elements'].append(input_element)

			log_file.write ("  ADDED NEW OBJECT TO OUPUT FILE:\n")
			for key, value in input_element['tags'].items():
				log_file.write ("    %s='%s'\n" % (key, value))


	# Tag elements in osm not found in input file

	for osm_element in osm_data['elements']:

		if ("tags" in osm_element) and (ref_key in osm_element['tags']) and not("match" in osm_element) and not("modify" in osm_element):
			osm_element['tags']['NOT_FOUND'] = "yes"
			osm_element['modify'] = True
			not_found += 1
			log_file.write ("\nOBJECT IN OSM NOT FOUND IN INPUT FILE:\n")
			for key, value in osm_element['tags'].items():
				log_file.write ("    %s='%s'\n" % (key, value))

	log_file.close()

	message ("\tUpdated:  %i\n" % updated)
	message ("\tAdded:    %i\n" % added)
	message ("\tNo match: %i (objects in OSM with %s not found in input file)\n" % (not_found, ref_key))
	message ("\tDetails in log file '%s'\n" % log_filename)



def indent_tree(elem, level=0):
	'''
	Insert line feeds into XLM file.
	'''

	i = "\n" + level*"  "
	if len(elem):
		if not elem.text or not elem.text.strip():
			elem.text = i + "  "
		if not elem.tail or not elem.tail.strip():
			elem.tail = i
		for elem in elem:
			indent_tree(elem, level+1)
		if not elem.tail or not elem.tail.strip():
			elem.tail = i
	else:
		if level and (not elem.tail or not elem.tail.strip()):
			elem.tail = i



def save_osm_file(filename):
	'''
	Output merged OSM file.
	'''

	# Generate XML

	message ("Saving file ...\n")
	osm_root = ET.Element("osm", version="0.6", generator="update2osm v%s" % version, upload="false")

	for element in osm_data['elements']:

		if element['type'] == "node":
			osm_element = ET.Element("node", lat=str(element['lat']), lon=str(element['lon']))

		elif element['type'] == "way":
			osm_element = ET.Element("way")
			if "nodes" in element:
				for node_ref in element['nodes']:
					osm_element.append(ET.Element("nd", ref=str(node_ref)))

		elif element['type'] == "relation":
			osm_element = ET.Element("relation")
			if "members" in element:
				for member in element['members']:
					osm_element.append(ET.Element("member", type=member['type'], ref=str(member['ref']), role=member['role']))

		if "tags" in element:
			for key, value in iter(element['tags'].items()):
				osm_element.append(ET.Element("tag", k=key, v=value))

		osm_element.set('id', str(element['id']))
		osm_element.set('visible', 'true')

		if "user" in element:  # Existing element
			osm_element.set('version', str(element['version']))
			osm_element.set('user', element['user'])
			osm_element.set('uid', str(element['uid']))
			osm_element.set('timestamp', element['timestamp'])
			osm_element.set('changeset', str(element['changeset']))

		if "modify" in element:
			osm_element.set('action', 'modify')

		osm_root.append(osm_element)
		
	# Output OSM/XML file

	osm_tree = ET.ElementTree(osm_root)
	indent_tree(osm_root)
	osm_tree.write(filename, encoding="utf-8", method="xml", xml_declaration=True)

	message ("\t%i elements saved to file '%s'\n" % (len(osm_data['elements']), out_filename))



# Main program

if __name__ == '__main__':

	# Read all data into memory
	
	message ("\nupdate2osm v%s\n" % version)

	if len(sys.argv) > 1:
		input_filename = sys.argv[1].lower()
	else:
		message ("Input filename.osm missing\n")
		sys.exit()

	if len(sys.argv) > 2:
		country = sys.argv[2].title()

	if ".osm" in input_filename:
		out_filename = input_filename.replace(".osm", "") + "_update.osm"
	else:
		out_filename = input_filename + "_update"

	today_date = time.strftime("%Y-%m-%d", time.localtime())
	log_filename = input_filename.replace(".osm", "") + "_update_log.txt"

	# Execute

	load_file(input_filename)
	load_overpass()
	merge(log_filename)
	save_osm_file(out_filename)

	message ("Done\n\n")
