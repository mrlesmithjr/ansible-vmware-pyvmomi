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
                data_to_print = self.json_format_dict(self.inventory, True)

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
        ''' Reads the settings from the ec2.ini file '''
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
            print(instance)

            # FIXME - make the key user configurable
            inv_key = instance.config.name + '_' + instance.config.uuid



            ## CONFIG
            iconfig = instance.summary.config
            if not inv_key in inventory['all']['hosts']:
                inventory['all']['hosts'].append(inv_key)
                inventory['_meta']['hostvars'][inv_key] = {}
                inventory['_meta']['hostvars'][inv_key]['summary'] = {}
                inventory['_meta']['hostvars'][inv_key]['summary']['config'] = {}


                # summary.config ...
                methods = dir(iconfig)
                methods = [x for x in methods if not x.startswith('_')]
                for method in methods:
                    methodToCall = getattr(iconfig, method)
                    #import epdb; epdb.st()
                    if hasattr(methodToCall, '__call__'):
                        method_data = methodToCall()
                        #print(method_data)
                        #import epdb; epdb.st()
                    else:
                        if type(methodToCall) in [int, bool, str]:
                            inventory['_meta']['hostvars'][inv_key]['summary']['config'][method] = methodToCall
                        #else:    
                        #    print(methodToCall)
                        #    import epdb; epdb.st()

        import epdb; epdb.st()
	return inventory


    ###################################################
    # OLD ...
    ###################################################


    def PrintVmInfo(vm, depth=1):
       """
       Print information for a particular virtual machine or recurse into a folder
        with depth protection
       """
       maxdepth = 10

       # if this is a group it will have children. if it does, recurse into them
       # and then return
       if hasattr(vm, 'childEntity'):
          if depth > maxdepth:
             return
          vmList = vm.childEntity
          for c in vmList:
             PrintVmInfo(c, depth+1)
          return

       #import epdb; epdb.st()
       summary = vm.summary
       print("Name       : ", summary.config.name)
       print("Path       : ", summary.config.vmPathName)
       print("Guest      : ", summary.config.guestFullName)
       annotation = summary.config.annotation
       if annotation != None and annotation != "":
          print("Annotation : ", annotation)
       print("State      : ", summary.runtime.powerState)
       print("UUID       : ", vm.config.uuid)
       if summary.guest != None:
          ip = summary.guest.ipAddress
          if ip != None and ip != "":
             print("IP         : ", ip)
       if summary.runtime.question != None:
          print("Question  : ", summary.runtime.question.text)
       print("")


    def main():
       """
       Simple command-line program for listing the virtual machines on a system.
       """

       args = GetArgs()
       if args.password:
          password = args.password
       else:
          password = getpass.getpass(prompt='Enter password for host %s and '
                                            'user %s: ' % (args.host,args.user))


       context = ssl.SSLContext(ssl.PROTOCOL_TLSv1)
       context.verify_mode = ssl.CERT_NONE
       si = SmartConnect(host=args.host,
                         user=args.user,
                         pwd=password,
                         port=int(args.port),
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
                PrintVmInfo(vm)
       return 0

# Run the script
VMWareInventory()


