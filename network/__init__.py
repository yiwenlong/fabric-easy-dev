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
import subprocess
import sys
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
            self.channels = config_user_channels(self.orgs_map, self.channel_cache_dir, raw_conf[KEY_USER_CHANNELS])

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
        self.setup_channels()
        self.setup_chaincodes()

    def down(self):
        self.clear()
        os.system("rm -fr %s" % self.Dir)

    def status(self, node_name=None):
        if node_name is None:
            self.sys_channel.status()
        else:
            node = find_node(self.orgs_map, node_name)
            node.deploy_handler.display()

    def channel(self, ch_name):
        if ch_name not in self.channels:
            raise Exception("No such channel configuration: %s" % ch_name)
        return self.channels[ch_name]

    def chaincode(self, cc_name):
        if cc_name not in self.chaincodes:
            raise Exception("No such chaincode configuration: %s" % cc_name)
        return self.chaincodes[cc_name]

    def setup_channels(self):
        orderer = self.sys_channel.Ords[0].FullName
        for ch_name in self.channels:
            self.setup_channel(ch_name, orderer)

    def setup_channel(self, ch_name, orderer_name=None):
        ch = self.channel(ch_name)
        if orderer_name is None:
            orderer_name = self.sys_channel.Ords[0].FullName
        ch.create(orderer_name)
        for org in ch.Orgs.values():
            for peer in org.PeerNodes.values():
                ch.join(orderer_name, peer.FullName)

    def setup_chaincodes(self):
        # check is docker running?
        if os.system("docker ps > /dev/null 2>&1") != 0:
            print("检查到您的 docker 没有在运行")
            print("!!运行 chaincode 需要用到 docker 环境.")
            print("!!您可以在启动 docker 之后执行 'python example.py setup_chaincodes' 继续使用 chaincode.")
            sys.exit(1)
        orderer = self.sys_channel.Ords[0].FullName
        for cc_name in self.chaincodes:
            self.setup_chaincode(cc_name, orderer)

    def setup_chaincode(self, cc_name, orderer_name=None):
        cc = self.chaincode(cc_name)
        for ch_name in cc.Channels:
            self._define_chaincode_(cc, ch_name, orderer_name)

    def _define_chaincode_(self, cc, ch_name, orderer_name=None):
        ch = self.channel(ch_name)
        if orderer_name is None:
            orderer_name = self.sys_channel.Ords[0].FullName
        endorsers = []
        for ch_org in ch.Orgs.values():
            ch_org.tree_walk_peers(lambda peer: self.chaincode_install(peer.FullName, cc.Name))
            endorser = ch_org.default_endorser().FullName
            package_id = self.chaincode_package_id(endorser, cc.Name, cc.Version)
            self.chaincode_approve(ch_name, cc.Name, endorser, orderer_name, package_id)
            endorsers.append(endorser)
        self.chaincode_commit(ch_name, cc.Name, orderer_name, *endorsers)
        time.sleep(5)
        self.chaincode_invoke(ch_name, cc.Name, '{"function":"InitLedger","Args":[]}', orderer_name, *endorsers)
        time.sleep(3)
        for endorser in endorsers:
            self.chaincode_query(ch_name, cc.Name, '{"Args":["GetAllAssets"]}', endorser)

    def channel_create(self, ch_name, orderer_name):
        ch = self.channel(ch_name)
        ch.create(orderer_name)

    def channel_join(self, ch_name, peer_name, orderer_name):
        ch = self.channel(ch_name)
        ch.join(orderer_name, peer_name)

    def channel_list(self, peer_name):
        peer = find_node(self.orgs_map, peer_name)
        support = api_support.cli_api_support(peer.Org.admin(), self.api_cache_dir)
        support.peer(peer).list_channels()

    def chaincode_list_installed(self, peer_name):
        peer = find_node(self.orgs_map, peer_name)
        support = api_support.cli_api_support(peer.Org.admin(), self.api_cache_dir)
        support.peer(peer).list_installed_chaincodes()

    def chaincode_package_id(self, peer_name, cc_name, cc_version):
        peer = find_node(self.orgs_map, peer_name)
        support = api_support.cli_api_support(peer.Org.admin(), self.api_cache_dir)
        return support.peer(peer).query_chaincode_package_id(cc_name, cc_version)

    def chaincode_install(self, peer_name, cc_name):
        peer = find_node(self.orgs_map, peer_name)
        support = api_support.cli_api_support(peer.Org.admin(), self.api_cache_dir)
        cc = self.chaincode(cc_name)
        if support.peer(peer).install_chaincode(cc) is None:
            print("Chaincode: %s.%s has already on node: %s" % (cc.Name, cc.Version, peer_name))

    def chaincode_approve(self, ch_name, cc_name, peer_name, orderer_name, package_id):
        ch = self.channel(ch_name)
        cc = self.chaincode(cc_name)
        cc.approve(ch, peer_name, orderer_name, package_id)

    def chaincode_query_approve(self, ch_name, cc_name, peer_name):
        ch = self.channel(ch_name)
        cc = self.chaincode(cc_name)
        cc.query_approve(ch, peer_name)

    def chaincode_check_commit_readiness(self, ch_name, cc_name, peer_name):
        ch = self.channel(ch_name)
        cc = self.chaincode(cc_name)
        cc.check_commit_readiness(ch, peer_name)

    def chaincode_commit(self, ch_name, cc_name, orderer_name, *endorser_names):
        ch = self.channel(ch_name)
        cc = self.chaincode(cc_name)
        cc.commit(ch, orderer_name, endorser_names)

    def chaincode_query_committed(self, ch_name, cc_name, peer_name):
        ch = self.channel(ch_name)
        cc = self.chaincode(cc_name)
        cc.query_committed(ch, peer_name)

    def chaincode_invoke(self, ch_name, cc_name, params, orderer_name, *endorser_names):
        ch = self.channel(ch_name)
        cc = self.chaincode(cc_name)
        cc.invoke(ch, orderer_name, endorser_names, params)

    def chaincode_query(self, ch_name, cc_name, params, peer_name):
        ch = self.channel(ch_name)
        cc = self.chaincode(cc_name)
        cc.query(ch, peer_name, params)
