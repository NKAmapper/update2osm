#!/usr/bin/env python
# -*- coding: utf8

# update2osm
# Compares input file with corresponding dataset in OSM and produces updated file.
# Finds a "ref:" tag in input file and uses this tag to match with data in OSM.
# Deletes tags from OSM object which are not present in input file (only if tag is part of the input dataset).
# "Equal prefix rule": If e.g. "fuel:diesel" is part of input dataset, then all "fuel:" tags must be part of the input dataset to survive.

# Usage: python update_ref.py [input_filename.osm]
# Input file name must end with .osm
# Output file name is appended with "_update.osm"
# Detailed log file: "_update_log.txt" + date


import json
import sys
import urllib
import urllib2
import copy
import time
from xml.etree import ElementTree


version = "0.3.0"

header = {"User-Agent": "osm-no/update_ref/" + version}


escape_characters = {
	'"': "&quot;",
	"'": "&apos;",
	"<": "&lt;",
	">": "&gt;"
}


# Escape string for osm xml file

def escape (value):

	value = value.replace("&", "&amp;")
	for change, to in escape_characters.iteritems():
		value = value.replace(change, to)
	return value


# Generate one osm tag

def osm_tag (key, value):

	value = value.strip()
	if value:
		value = escape(value).encode('utf-8')
		key = escape(key).encode('utf-8')
		line = "    <tag k='%s' v='%s' />\n" % (key, value)
		file_out.write (line)


# Generate one osm line

def osm_line (value):

	value = value.encode('utf-8')
	file_out.write (value)


# Generate node, way or relation

def generate_osm_element (element):

	if element['id'] < 0:
		line = "  <node id='%i' action='modify' visible='true' lat='%f' lon='%f'>\n" % (element['id'], element['lat'], element['lon'])
		osm_line (line)

	else:
		if "modify" in element:
			action_text = "action='modify' "
		else:
			action_text = ""

		line = u"  <%s id='%i' %stimestamp='%s' uid='%i' user='%s' visible='true' version='%i' changeset='%i'"\
				% (element['type'], element['id'], action_text, element['timestamp'], element['uid'], escape(element['user']),\
				element['version'], element['changeset'])

		if element['type'] == "node":
			line_end = " lat='%f' lon='%f'>\n" % (element['lat'], element['lon'])
		else:
			line_end = ">\n"

		osm_line (line + line_end)

	if "nodes" in element:
		for node in element['nodes']:
			line = "    <nd ref='%i' />\n" % node
			osm_line (line)

	if "members" in element:
		for member in element['members']:
			line = "    <member type='%s' ref='%i' role='%s' />\n" % (escape(member['type']), member['ref'], member['role'])
			osm_line (line)

	if "tags" in element:
		for key, value in element['tags'].iteritems():
			osm_tag (key, value)

	line = "  </%s>\n" % element['type']
	osm_line (line)


# Output message

def message (line):

	sys.stdout.write (line)
	sys.stdout.flush()


# Main program

if __name__ == '__main__':

	# Read all data into memory
	
	if len(sys.argv) == 2:
		input_filename = sys.argv[1].lower()
	else:
		message ("Input filename.osm missing\n")
		sys.exit()

	if input_filename.find(".osm") >= 0:
		out_filename = input_filename.replace(".osm", "") + "_update.osm"
	else:
		out_filename = input_filename + "_update"

	today_date = time.strftime("%Y-%m-%d", time.localtime())
	log_filename = input_filename.replace(".osm", "") + "_update_log_" + today_date +  ".txt"


	# First loop all input nodes to copy data and produce tag inventory

	tree = ElementTree.parse(input_filename)
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

	message ("\nUpdating elements with '%s'\n" % ref_key)
	message ("%i elements in input file" % len(input_elements))
	if ref_input_count < len(input_elements):
		message (" (%i with %s key)\n" % (ref_input_count, ref_key))
	else:
		message ("\n")

	if not(ref_key):
		message ("*** No ref: key found\n")
		sys.exit()


	# Get all existing object from Overpass

	message ("Loading from Overpass... ")
	query = '[out:json][timeout:60];(area[admin_level=2][name=Norge];)->.a;(nwr["%s"](area.a););(._;<;);(._;>;);out meta;' % ref_key
	request = urllib2.Request('https://overpass-api.de/api/interpreter?data=' + urllib.quote(query), headers=header)
	file = urllib2.urlopen(request)
	osm_data = json.load(file)
	file.close()

	ref_osm_count = 0
	for element in osm_data['elements']:
		if ("tags" in element) and (ref_key in element['tags']):
			ref_osm_count += 1

	message ("\n%i elements in OSM with %s" % (ref_osm_count, ref_key))
	if len(osm_data['elements']) > ref_osm_count:
		message (", + %i connected elements\n" % (len(osm_data['elements']) - ref_osm_count))
	else:
		message ("\n")

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
			log_file.write ("\n%s: %s\n" % (ref_key, input_element['tags'][ref_key]))

			for osm_element in osm_data['elements']:
				if ("tags" in osm_element) and (ref_key in osm_element['tags']) and (osm_element['tags'][ref_key] == input_element['tags'][ref_key]):

					# Loop tags of existing osm element and replace keys/values, or delete if within tag scope of tags in input file

					new_tags = copy.deepcopy(osm_element['tags'])
					for key, value in osm_element['tags'].iteritems():

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
										(value == input_element['tags'][key].replace("http", "https") + "/"))):
									new_tags[key] = input_element['tags'][key]
									modified = True
									log_file.write ("    Replaced: %s='%s' with '%s'\n" % (key.encode("utf-8"), value.encode("utf-8"),\
																						input_element['tags'][key].encode("utf-8")))
								else:
									log_file.write ("    Keep:     %s='%s'\n" % (key.encode("utf-8"), value.encode("utf-8")))

						# Tag not found, and to be deleted if within scope of input tags
						# Keep 4 tags for YX/7-Eleven stations and 2 tags for schools

						elif prefix_key in input_keys:
							if not(("brand" in input_element['tags']) and (input_element['tags']['brand'] == "YX 7-Eleven") and\
									(key in ['phone', 'email'])):
								del new_tags[key]
								modified = True
								log_file.write ("    Deleted:  %s='%s'\n" % (key.encode("utf-8"), value.encode("utf-8")))
							else:
								log_file.write ("    Keep:     %s='%s'\n" % (key.encode("utf-8"), value.encode("utf-8")))

					# Add new tags to osm element

					for key, value in input_element['tags'].iteritems():
						if not(key in new_tags) and (key != key.upper()):
							new_tags[key] = value
							modified = True
							log_file.write ("    Added:    %s='%s'\n" % (key.encode("utf-8"), value.encode("utf-8")))

					osm_element['match'] = True
					osm_element['tags'] = new_tags
					if modified:
						osm_element['modify'] = True
						updated += 1
					found = True
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

			log_file.write ("    ADDED NEW OBJECT TO OUPUT FILE:\n")
			for key, value in input_element['tags'].iteritems():
				log_file.write ("    %s='%s'\n" % (key.encode("utf-8"), value.encode("utf-8")))


	# Tag elements in osm not found in input file

	for osm_element in osm_data['elements']:

		if ("tags" in osm_element) and (ref_key in osm_element['tags']) and not("match" in osm_element) and not("modify" in osm_element):
			osm_element['tags']['NOT_FOUND'] = "yes"
#			osm_element['modify'] = True
			not_found += 1
			log_file.write ("\nOBJECT IN OSM NOT FOUND IN INPUT FILE:\n")
			for key, value in osm_element['tags'].iteritems():
				log_file.write ("    %s='%s'\n" % (key.encode("utf-8"), value.encode("utf-8")))


	# Produce file

	file_out = open(out_filename, "w")
	file_out.write ('<?xml version="1.0" encoding="UTF-8"?>\n')
	file_out.write ('<osm version="0.6" generator="update_ref v%s" upload="false">\n' % version)

	for element in osm_data['elements']:
		generate_osm_element (element)

	file_out.write ('</osm>\n')
	file_out.close()
	log_file.close()

	message ("\nSummary of changes written to output file %s:\n" % out_filename)
	message ("  Updated:  %i\n" % updated)
	message ("  Added:    %i\n" % added)
	message ("  No match: %i (objects in OSM with %s not found in input file)\n" % (not_found, ref_key))
	message ("\nDetails in log file %s\n\n" % log_filename)
