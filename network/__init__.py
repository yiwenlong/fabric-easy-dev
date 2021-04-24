#
# Copyright 2020 Yiwenlong(wlong.yi#gmail.com)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import os
import time
import yaml

from orgconfig import config_organizations, find_node, KEY_ORGANIZATIONS
from channel import config_sys_channel, config_user_channels, KEY_SYS_CHANNEL, KEY_USER_CHANNELS
from chiancode import config_chaincodes, KEY_USER_CHAINCODES
from api import support as api_support
from utils.fileutil import mkdir_if_need


class Network:

    def __init__(self, config_file, target_dir):

        if not os.path.exists(config_file):
            raise ValueError("Config file not exists: %s" % config_file)
        with open(config_file, 'r') as conf:
            raw_conf = yaml.load(conf, yaml.CLoader)

        self.Dir = target_dir
        mkdir_if_need(self.Dir)

        if KEY_ORGANIZATIONS not in raw_conf:
            raise Exception("No organization found in config file: %s" % config_file)
        self.orgs_map = config_organizations(raw_conf[KEY_ORGANIZATIONS], target_dir)

        if KEY_SYS_CHANNEL not in raw_conf:
            raise Exception("No system channel found in config file: %s" % config_file)
        self.sys_channel = config_sys_channel(self.orgs_map, raw_conf[KEY_SYS_CHANNEL])
        self.sys_channel_cache_dir = os.path.join(target_dir, self.sys_channel.Name)
        mkdir_if_need(self.sys_channel_cache_dir)

        self.channel_cache_dir = os.path.join(target_dir, "user-channels")
        mkdir_if_need(self.channel_cache_dir)

        if KEY_USER_CHANNELS in raw_conf:
            self.channels = config_user_channels(self.orgs_map, raw_conf[KEY_USER_CHANNELS])

        if KEY_USER_CHAINCODES in raw_conf:
            self.chaincodes = config_chaincodes(raw_conf[KEY_USER_CHAINCODES])

        self.api_cache_dir = os.path.join(target_dir, "api")
        mkdir_if_need(self.api_cache_dir)

    def echo_hosts(self, ip="127.0.0.1"):
        hosts_cache = ""
        for org in self.orgs_map.values():
            hosts_cache += "\n"
            hosts_cache += "# fabric network host configs for organization: %s\n" % org.Name
            for p in org.PeerNodes.values():
                hosts_cache += "%s\t%s\n" % (ip, p.Domain)
            for o in org.OrdererNodes.values():
                hosts_cache += "%s\t%s\n" % (ip, o.Domain)
        print(hosts_cache)

    def deploy(self):
        self.sys_channel.deploy(self.sys_channel_cache_dir)

    def boot(self):
        self.sys_channel.boot()

    def stop(self):
        self.sys_channel.stop()

    def clear(self):
        self.sys_channel.clear()

    def up(self):
        self.sys_channel.deploy(self.sys_channel_cache_dir)
        self.sys_channel.boot()

        time.sleep(15)

        orderer = self.sys_channel.Ords[0]
        for ch_name in self.channels:
            self.channel_create(ch_name, orderer.FullName)
            ch = self.__channel__(ch_name)
            for org in ch.Orgs.values():
                for peer in org.PeerNodes.values():
                    self.channel_join(ch_name, peer.FullName, orderer.FullName)

    def down(self):
        self.clear()
        os.system("rm -fr %s" % self.Dir)

    def status(self, node_name=None):
        if node_name is None:
            self.sys_channel.status()
        else:
            node = find_node(self.orgs_map, node_name)
            node.deploy_handler.display()

    def __channel_cache_dir__(self, ch_name):
        return os.path.join(self.channel_cache_dir, ch_name)

    def __channel__(self, ch_name):
        if ch_name not in self.channels:
            raise Exception("No such channel configuration: %s" % ch_name)
        return self.channels[ch_name]

    def __chaincode__(self, cc_name):
        if cc_name not in self.chaincodes:
            raise Exception("No such chaincode configuration: %s" % cc_name)
        return self.chaincodes[cc_name]

    def channel_create(self, ch_name, orderer_name):
        orderer = find_node(self.orgs_map, orderer_name)
        support = api_support.cli_api_support(orderer.Org.admin(), self.__channel_cache_dir__(ch_name))
        ch = self.__channel__(ch_name)
        channel_api = support.channel(ch, orderer)
        tx = ch.create_tx(channel_api.api.Dir)
        channel_api.create(tx)

    def channel_join(self, ch_name, peer_name, orderer_name):
        peer = find_node(self.orgs_map, peer_name)
        orderer = find_node(self.orgs_map, orderer_name)
        support = api_support.cli_api_support(peer.Org.admin(), self.__channel_cache_dir__(ch_name))
        ch = self.__channel__(ch_name)
        ch_api = support.channel(ch, orderer)
        ch_api.join(peer)

    def channel_list(self, peer_name):
        peer = find_node(self.orgs_map, peer_name)
        support = api_support.cli_api_support(peer.Org.admin(), self.api_cache_dir)
        support.peer(peer).list_channels()

    def chaincode_list_installed(self, peer_name):
        peer = find_node(self.orgs_map, peer_name)
        support = api_support.cli_api_support(peer.Org.admin(), self.api_cache_dir)
        support.peer(peer).list_installed_chaincodes()

    def chaincode_install(self, peer_name, cc_name):
        peer = find_node(self.orgs_map, peer_name)
        support = api_support.cli_api_support(peer.Org.admin(), self.api_cache_dir)
        support.peer(peer).install_chaincode(self.chaincodes[cc_name])

    def chaincode_approve(self, peer_name, orderer_name, cc_name, package_id, ch_name=None):
        peer = find_node(self.orgs_map, peer_name)
        orderer = find_node(self.orgs_map, orderer_name)
        support = api_support.cli_api_support(peer.Org.admin(), self.__channel_cache_dir__(ch_name))
        cc = self.chaincodes[cc_name]
        cc_api = support.chaincode_lifecycle(cc, peer, orderer)
        if ch_name is not None:
            cc_api.approve(ch_name, package_id)
        else:
            for _ch_name in cc.Channels:
                cc_api.approve(_ch_name, package_id)

    def chaincode_query_approve(self, peer_name, ch_name, cc_name):
        peer = find_node(self.orgs_map, peer_name)
        support = api_support.cli_api_support(peer.Org.admin(), self.api_cache_dir)
        support.peer(peer.deploy_handler.Address).chaincode_query_approved(self.chaincodes[cc_name], ch_name)
