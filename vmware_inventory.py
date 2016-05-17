#!/usr/bin/env python
# VMware vSphere Python SDK
# Copyright (c) 2008-2015 VMware, Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Python program for listing the vms on an ESX / vCenter host
"""

from __future__ import print_function

from pyVim.connect import SmartConnect, Disconnect

import argparse
import atexit
import getpass
import os
import six
import ssl

from six.moves import configparser
from collections import defaultdict

try:
    import json
except ImportError:
    import simplejson as json


class VMWareInventory(object):

    __name__ = 'VMWareInventory'

    maxlevel = 1
    config = None
    cache_max_age = None
    cache_path_cache = None
    cache_path_index = None
    server = None
    port = None
    username = None
    password = None


    def _empty_inventory(self):
        return {"_meta" : {"hostvars" : {}}}


    def __init__(self):
        self.inventory = self._empty_inventory()
        self.index = {}

        # Read settings and parse CLI arguments
        self.parse_cli_args()
        self.read_settings()

        # Cache
        if self.args.refresh_cache:
            self.do_api_calls_update_cache()
        elif not self.is_cache_valid():
            self.do_api_calls_update_cache()

        #import epdb; epdb.st()

        # Data to print
        if self.args.host:
            data_to_print = self.get_host_info()

        elif self.args.list:
            # Display list of instances for inventory
            if self.inventory == self._empty_inventory():
                data_to_print = self.get_inventory_from_cache()
            else:
                data_to_print = json.dumps(self.inventory, indent=2)
        print(data_to_print)


    def is_cache_valid(self):
        ''' Determines if the cache files have expired, or if it is still valid '''

        if os.path.isfile(self.cache_path_cache):
            mod_time = os.path.getmtime(self.cache_path_cache)
            current_time = time()
            if (mod_time + self.cache_max_age) > current_time:
                if os.path.isfile(self.cache_path_index):
                    return True

        return False

    def write_to_cache(self, index, cache_path):
        pass

    def do_api_calls_update_cache(self):
        instances = self.get_instances()
        #import epdb; epdb.st()
	self.inventory = self.instances_to_inventory(instances)
	#import epdb; epdb.st()
        self.write_to_cache(self.inventory, self.cache_path_cache)
        self.write_to_cache(self.index, self.cache_path_index)

    def get_inventory_from_cache(self):
        pass


    def read_settings(self):
        ''' Reads the settings from the vmware.ini file '''
        if six.PY3:
            config = configparser.ConfigParser()
        else:
            config = configparser.SafeConfigParser()
        self.config = config    
        vmware_default_ini_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'vmware.ini')
        vmware_ini_path = os.path.expanduser(os.path.expandvars(os.environ.get('VMWARE_INI_PATH', vmware_default_ini_path)))
        config.read(vmware_ini_path)

	cache_name = 'ansible-vmware'

        self.cache_dir = os.path.expanduser(config.get('vmware', 'cache_path'))
        if self.cache_dir and not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)
        self.cache_path_cache = self.cache_dir + "/%s.cache" % cache_name
        self.cache_path_index = self.cache_dir + "/%s.index" % cache_name
        self.cache_max_age = config.getint('vmware', 'cache_max_age')

        self.server = config.get('vmware', 'server')
        self.port = config.get('vmware', 'port')
        self.username = config.get('vmware', 'username')
        self.password = config.get('vmware', 'password')
        #import epdb; epdb.st()


    def parse_cli_args(self):
        ''' Command line argument processing '''

        parser = argparse.ArgumentParser(description='Produce an Ansible Inventory file based on PyVmomi')
        parser.add_argument('--list', action='store_true', default=True,
                           help='List instances (default: True)')
        parser.add_argument('--host', action='store',
                           help='Get all the variables about a specific instance')
        parser.add_argument('--refresh-cache', action='store_true', default=False,
                           help='Force refresh of cache by making API requests to VSphere (default: False - use cache files)')
        self.args = parser.parse_args()


    def get_instances(self):
        instances = []        
        context = ssl.SSLContext(ssl.PROTOCOL_TLSv1)
        context.verify_mode = ssl.CERT_NONE
        si = SmartConnect(host=self.server,
                         user=self.username,
                         pwd=self.password,
                         port=int(self.port),
                         sslContext=context)
        if not si:
            print("Could not connect to the specified host using specified "
                "username and password")
            return -1

        atexit.register(Disconnect, si)

        content = si.RetrieveContent()
        for child in content.rootFolder.childEntity:
            if hasattr(child, 'vmFolder'):
                datacenter = child
                vmFolder = datacenter.vmFolder
                vmList = vmFolder.childEntity
                for vm in vmList:
                    if hasattr(vm, 'childEntity'):
                        vmList = vm.childEntity
                        for c in vmList:
                            instances.append(c)
                    else:
                        instances.append(vm)
        return instances


    def instances_to_inventory(self, instances):
	inventory = self._empty_inventory()
        inventory['all'] = {}
        inventory['all']['hosts'] = []
        for instance in instances:

            # Get all known info about this instance
            rdata = self.facts_from_vobj(instance)

            # FIXME - make the key user configurable based on rdata
            inv_key = instance.config.name + '_' + instance.config.uuid

            # Put it in the inventory
            if not inv_key in inventory['all']['hosts']:
                inventory['all']['hosts'].append(inv_key)
                inventory['_meta']['hostvars'][inv_key] = rdata

        #import pprint; pprint.pprint(inventory)
	return inventory


    def facts_from_vobj(self, vobj, rdata={}, level=0):

        if level > self.maxlevel:
            return rdata

        bad_types = ['Array']
        safe_types = [int, bool, str, float]
        iter_types = [dict, list]

        methods = dir(vobj)
        methods = [str(x) for x in methods if not x.startswith('_')]
        methods = [x for x in methods if not x in bad_types]

        for method in methods:

            if method in rdata:
                continue

            methodToCall = getattr(vobj, method)
            method = method.lower()

            # Store if type is a primitive
            if type(methodToCall) in safe_types:
                try:
                    rdata[method] = methodToCall
                except Exception as e:
                    print(e)
                    import epdb; epdb.st()

            # Objects usually have a dict property
            elif hasattr(methodToCall, '__dict__'):

                # the dicts will have objects for values, get rid of those
                safe_dict = {}

                for k,v in methodToCall.__dict__.iteritems():

                    # Try not to recurse into self
                    if hasattr(v, '__name__'):
                        if v.__name__ == 'VMWareInventory':
                            continue                     

                    # Skip private methods
                    if k.startswith('_'):
                        continue

                    # Make all keys lower                        
                    k = k.lower()

                    if type(v) in safe_types:
                        safe_dict[k] = v    
                    elif not v:
                        pass    
                    elif type(v) in iter_types:
                        pass
                    else:

                        # Recurse through this method to get deeper data
                        if level < self.maxlevel:
                            vdata = None
                            vdata = self.facts_from_vobj(methodToCall, level=(level+1))

                            if method not in rdata:
                                rdata[method] = {}

                            for vk, vv in vdata.iteritems():
                                vk = vk.lower()
                                if method not in rdata[method]:
                                     rdata[method][vk] = None
                                if vk not in rdata[method]:
                                    safe_dict[vk] = vv
                        
                if safe_dict:        
                    try:
                        rdata[method] = safe_dict
                    except Exception as e:
                        print(e)
                        import epdb; epdb.st()
                        pass

        return rdata



# Run the script
VMWareInventory()


