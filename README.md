# update2osm

Loads objects from OSM and generates osm file with updated tags and objects based on given input file.

Usage: <code>python update2osm.py <input_file.osm></code>

* Input file must contain exactly one *ref:* tag (e.g. *ref:esso*) to uniqely identify each object in OSM
* All objects with *ref:* tags in Norway are loaded from OSM and updated according to the input file
* Tags which are present in the input file at least once are tested and either updated, added or removed
* If a prefix tag is present in the input file, then all tags with this prefix is considered within the scope of the update.
  - Example: If *fuel:diesel* is present in the input file, then *fuel:octane_98* will be removed if that tag is not also in the input file
* New objects in the input file which are not present in OSM will be added to the output file
* Objects in OSM with the given *ref:* tag with no match in the input file will be tagged with *NO_MATCH=yes*. Please delete object manually if desired, or retag.
* The name of the output file is the same as the input file + *_update.osm*
* A detailed log is written to the file *update_log.txt*
* Only nodes are supported in the input file

Please review the generated output file before uploading to OSM.
