# -*- encoding: utf-8 -*-
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
import yaml
from channel.configtx import ConfigTxSupport

KEY_SYS_CHANNEL = "SystemChannel"
KEY_USER_CHANNELS = "UserChannels"


def __default_tx_support__():
    return ConfigTxSupport()


class SystemChannel(dict):

    def __getattr__(self, item):
        return self[item]

    def __init__(self, orgs_map, **config):
        super(SystemChannel, self).__init__()
        self.update(config)

        self.Orgs = [orgs_map[name] for name in self.Organizations]
        self.Ords = [orgs_map[org_name].OrdererNodes[node_name]
                     for ordorgs in self.Orderers
                     for org_name in ordorgs
                     for node_name in ordorgs[org_name]]

    def genesis(self, cache_dir, tx_support=__default_tx_support__()):
        return tx_support.generate_syschannel_genesis_block(self, cache_dir)

    def deploy(self, cache_dir):
        genesis_block_file = self.genesis(cache_dir)
        for org in self.Orgs:
            org.deploy_peers()
        for ord in self.Ords:
            ord.deploy_handler.deploy(genesis_block_file)

    def boot(self):
        for org in self.Orgs:
            for node in org.PeerNodes.values():
                node.deploy_handler.proc_handler.boot()
        for ord in self.Ords:
            ord.deploy_handler.proc_handler.boot()

    def stop(self):
        for org in self.Orgs:
            for node in org.PeerNodes.values():
                node.deploy_handler.proc_handler.stop()
        for ord in self.Ords:
            ord.deploy_handler.proc_handler.stop()


class UserChannel(dict):

    def __getattr__(self, item):
        return self[item]

    def __init__(self, orgs_map, **config):
        super(UserChannel, self).__init__()
        self.update(config)
        self.Orgs = [orgs_map[name] for name in self.Organizations]

    def create_tx(self, cache_dir, tx_support=__default_tx_support__()):
        return tx_support.generate_create_channel_tx(self, cache_dir)


def config_sys_channel(orgs_map, config_file):
    if not os.path.exists(config_file):
        raise ValueError("Config file not exists: %s" % config_file)
    with open(config_file, 'r') as conf:
        raw_conf = yaml.load(conf, yaml.CLoader)
    if KEY_SYS_CHANNEL not in raw_conf:
        raise Exception("No system channel found in config file: %s" % config_file)
    return SystemChannel(orgs_map, **raw_conf[KEY_SYS_CHANNEL])
