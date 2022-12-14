import pathlib
import json
import yaml
import random
import string
import base64
import argparse
import logging
import os.path as osp
import json
import os
import toml
import time 

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from eth import create_eth_address, get_genesis_content

logger = logging.getLogger()
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s %(levelname)-8s %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

encode = lambda s: base64.b64encode(str.encode(s)).decode()

config.load_kube_config()


class GethLightClient:
    """
    Geth Light Client
    """
    def __init__(self, name):
        self.name = name
        self.k8s_config_dir = pathlib.Path('k8s-geth-light-client/')

    def create_namespace(self):
        config = self.k8s_config_dir / 'namespace.yaml'
        with config.open() as f:
            body = yaml.safe_load(f)

        body['metadata']['name'] = self.name

        try:
            api_instance = client.CoreV1Api()
            api_instance.create_namespace(body)
        except ApiException as e:
            error = json.loads(e.body)
            if error['code'] == 409 and error['reason'] == 'AlreadyExists':
                return
            else:
                raise

        logger.debug(f'Created namespace "{self.name}"')

    def delete_namespace(self):
        try:
            v1 = client.CoreV1Api()
            v1.delete_namespace(name=self.name, body=client.V1DeleteOptions())
        except ApiException as e:
            if e.status == 404:
                # don't throw if namespace doesn't exist
                return
            else:
                raise
        logger.debug(f'Deleted namespace "{self.name}"')

    def create_service(self):
        config = self.k8s_config_dir / 'service.yaml'
        with config.open() as f:
            body = yaml.safe_load(f)

        try:
            api_instance = client.CoreV1Api()
            api_instance.create_namespaced_service(self.name, body)
        except ApiException as e:
            error = json.loads(e.body)
            if error['code'] == 409 and error['reason'] == 'AlreadyExists':
                return
            else:
                raise

        logger.debug('Created Service')

    def create_deployment(self):
        config = self.k8s_config_dir / 'deployment.yaml'
        with config.open() as f:
            body = yaml.safe_load(f)

        try:
            api_instance = client.AppsV1Api()
            api_instance.create_namespaced_deployment(self.name, body)
        except ApiException as e:
            error = json.loads(e.body)
            if error['code'] == 409 and error['reason'] == 'AlreadyExists':
                return
            else:
                raise

        logger.debug('Created Deployment')

    def create(self):
        self.create_namespace()
        self.create_service()
        self.create_deployment()

    def delete(self):
        # this will delete all objects under the namespace
        self.delete_namespace()


class PrivateNetwork:
    """
    Private Ethereum Network (using geth)
    """
    def __init__(self, name):
        self.name = name
        self.namespace = name
        self.accounts = []

    def create_accounts(self, num=10):
        for i in range(num):
            account = create_eth_address()
            self.accounts.append(account)

    def create_namespace(self):
        path = pathlib.Path('k8s/namespace.yaml')
        with path.open() as f:
            body = yaml.safe_load(f)

        body['metadata']['name'] = self.name

        api_instance = client.CoreV1Api()
        api_instance.create_namespace(body)

        logger.debug(f'Created namespace "{self.name}"')

    def delete_namespace(self):
        v1 = client.CoreV1Api()
        try:
            v1.delete_namespace(name=self.name, body=client.V1DeleteOptions())
        except ApiException as e:
            if e.status == 404:
                # don't throw if namespace doesn't exist
                return
            else:
                raise
        logger.debug(f'Deleted namespace "{self.name}"')

    def create_configmap(self):
        genesis = get_genesis_content(self.accounts)

        path = pathlib.Path('k8s/configmap.yaml')
        with path.open() as f:
            body = yaml.safe_load(f)
            body['data']['genesis.json'] = genesis

        api_instance = client.CoreV1Api()
        api_instance.create_namespaced_config_map(self.namespace, body)

        logger.debug('Created ConfigMap')

    def create_secret(self, account):
        path = pathlib.Path('k8s/secret.yaml')
        with path.open() as f:
            body = yaml.safe_load(f)

        password = ''.join(random.choices(string.ascii_letters + string.digits,
                                          k=10))

        body['data']['address'] = encode(account['address'])
        body['data']['private_key'] = encode(account['private_key'])
        body['data']['password'] = encode(password)

        api_instance = client.CoreV1Api()
        api_instance.create_namespaced_secret(self.namespace, body)

        logger.debug('Created Secret')

    def create_service(self):
        path = pathlib.Path('k8s/service.yaml')
        with path.open() as f:
            body = yaml.safe_load(f)

        api_instance = client.CoreV1Api()
        api_instance.create_namespaced_service(self.namespace, body)

        logger.debug('Created Service')

    def create_deployment(self):
        path = pathlib.Path('k8s/deployment.yaml')
        with path.open() as f:
            body = yaml.safe_load(f)

        api_instance = client.AppsV1Api()
        api_instance.create_namespaced_deployment(self.namespace, body)

        logger.debug('Created Deployment')
    
    def create_deployment_by_path(self, path):
        path = pathlib.Path(path)
        with path.open() as f:
            body = yaml.safe_load(f)

        api_instance = client.AppsV1Api()
        api_instance.create_namespaced_deployment(self.namespace, body)

        logger.debug('Created Deployment')

    def create_deployment_by_path_replicas(self, path, replicas):
        path = pathlib.Path(path)
        with path.open() as f:
            body = yaml.safe_load(f)

        body["spec"]["replicas"] = replicas

        api_instance = client.AppsV1Api()
        api_instance.create_namespaced_deployment(self.namespace, body)

        logger.debug('Created Deployment')

    def delete(self):
        # this will delete all objects under the namespace
        self.delete_namespace()

    def create_by_config(self, config_path):
        nameInfo = os.popen("kubectl get namespaces").read()
        if self.namespace in nameInfo:
            deleteFlag = input("namespace {} already exists, delete? y/n???".format(self.namespace))
            if deleteFlag != "y" and deleteFlag != "yes":
                return
            self.delete_namespace()
            while self.namespace in nameInfo:
                print("waiting ...")
                time.sleep(1)
                nameInfo = os.popen("kubectl get namespaces").read()
                
        self.create_namespace()
        self.create_service()

        config = None
        with open(config_path) as f:
            config = json.load(f)
        if config is None:
            print(config_path, "open failed")
            return
        graph = config["graph"]
        bitxhub_replicas = len(graph)
        eth_replicas = sum(p["eth"] for p in graph)

        nodeInfo = os.popen("kubectl get nodes -o wide").read()
        nodeIpList = [nodeItem.split()[5] for nodeItem in nodeInfo.split('\n') if nodeItem != '' and "Ready" in nodeItem]
        print(nodeIpList)

        self.create_deployment_by_path_replicas('k8s/deployment-ether.yaml', eth_replicas)
        # self.create_deployment_by_path_replicas('k8s/deployment-bitxhub.yaml', bitxhub_replicas)
        for nodeIp in nodeIpList:
            if nodeIp == "10.206.0.7":
                continue

            cmd = "sshpass -p {} scp -r {} {}@{}:{}".format(config["passwd"], config["root_bitxhub"], config["user"], nodeIp, config["base"])
            print(cmd)
            os.system(cmd)
            
            cmd = "sshpass -p {} scp -r {} {}@{}:{}".format(config["passwd"], config["bitxhub"], config["user"], nodeIp, config["base"])
            print(cmd)
            os.system(cmd)

        d = {}
        for i in range(bitxhub_replicas):
            body = None
            path = pathlib.Path('k8s/pod-bitxhub.yaml')
            with path.open() as f:
                body = yaml.safe_load(f)

            
            body['metadata']['name'] = 'bitxhub-{}'.format(i)
            body['spec']['containers'][0]['name'] = 'bitxhub-{}'.format(i)
            body['spec']['containers'][0]['args'] = ['123{}'.format(i)]
            # body['spec']['containers'][0]['volumeMounts'][0]["name"]= ['123{}'.format(i)]
            if i == 0:
                body['spec']['volumes'][0]['hostPath']['path'] = osp.join(config["base"], "root_bitxhub")
            else:
                body['spec']['volumes'][0]['hostPath']['path'] =  osp.join(config["base"], "bitxhub")

            # fa = open("test.yaml", "w")
            # fa.write(yaml.dump(body))
            # return

            api_instance = client.CoreV1Api()
            api_instance.create_namespaced_pod(self.namespace, body)
            d['bitxhub-{}'.format(i)] = {
                'bitxhubId': '123{}'.format(i)
            }

        while True:
            # read bitxhub data from pods
            bitxhubInfo = os.popen("kubectl get pods -n {} -o wide | grep bitxhub".format(self.namespace)).read()
            bitxhubIpList = [bitxhubItem.split()[-4] for bitxhubItem in bitxhubInfo.split('\n') if bitxhubItem != '']
            bitxhubNameList = [bitxhubItem.split()[0] for bitxhubItem in bitxhubInfo.split('\n') if bitxhubItem != '']
            print(bitxhubIpList)
            print(bitxhubNameList)
            if "<none>" not in bitxhubIpList:
                break
            print("container starting...")
            time.sleep(1)

        while True:
            ethInfo = os.popen("kubectl get pods -n {} -o wide | grep geth".format(self.namespace)).read()
            print(ethInfo)
            ethIpList = [ethItem.split()[-4] for ethItem in ethInfo.split('\n') if ethItem != '']
            ethNameList = [ethItem.split()[0] for ethItem in ethInfo.split('\n') if ethItem != '']
            print(ethIpList)
            print(ethNameList)
            if "<none>" not in ethIpList:
                break
            print("container starting...")
            time.sleep(1)


        for i in range(bitxhub_replicas):
            d['bitxhub-{}'.format(i)]['bitxhubIp'] = bitxhubIpList[i]
            fetch = graph[i]["eth"]
            ips = []
            names = []
            for j in range(fetch):
                names.append(ethNameList.pop(0))
                ips.append(ethIpList.pop(0))

            d['bitxhub-{}'.format(i)]['chainNameList'] =  names
            d['bitxhub-{}'.format(i)]['chainIpList'] =  ips
            d['bitxhub-{}'.format(i)]['pierPrefixName'] =  "pier-{}".format(i)

        json.dump(d, open("graph_{}.json".format(self.namespace), "w"), indent=4)



    def create(self):
        # self.create_accounts()
        # # print address and private key
        # for account in self.accounts:
        #     print('Address:', account['address'],
        #           'Private Key:', account['private_key'])
        self.create_namespace()
        # self.create_secret(self.accounts[0])
        # self.create_configmap()
        self.create_service()
        # self.create_deployment()
        self.create_deployment_by_path('k8s/deployment-ether.yaml')
        self.create_deployment_by_path('k8s/deployment-bitxhub.yaml')
        # self.create_deployment_by_path('k8s/deployment-pier.yaml')


    def deploy(self):
        # ethInfo = os.popen("kubectl get pods -n {} -o wide | grep geth".format(self.namespace)).read()
        # ethIpList = [ethItem.split()[-4] for ethItem in ethInfo.split('\n') if ethItem != '']

        # connect bitxhubId with ethereum when deploy broker contract
        d = {}
        graph_json = None
        with open("graph_{}.json".format(self.namespace)) as f:
            graph_json = json.load(f)

        appchainId = 0
        for bitxhubName, item in graph_json.items():
            bitxhubId = item["bitxhubId"]
            bitxhubIp = item["bitxhubIp"]
            for ethIp in item["chainIpList"]:
                print("handle ip: ", ethIp)
                print("handle bitxhub_id: ", bitxhubId)
                cmd = 'goduck ether contract deploy --code-path $HOME/goduck/scripts/example/broker.sol --address http://{}:8545  "{}^ethappchain{}^["0xc7F999b83Af6DF9e67d0a37Ee7e900bF38b3D013","0x79a1215469FaB6f9c63c1816b45183AD3624bE34","0x97c8B516D19edBf575D72a172Af7F418BE498C37","0xc0Ff2e0b3189132D815b8eb325bE17285AC898f8"]^1^["0x20F7Fac801C5Fc3f7E20cFbADaA1CDb33d818Fa3"]^1"| grep 0x'.format(ethIp, bitxhubId, appchainId)
                broker_addr = os.popen(cmd).read()
                if broker_addr == "":
                    print(cmd)
                    print(os.popen(cmd).read())
                    print("error command")
                    return
                broker_addr = broker_addr.split()[-1]
                print("\tbroker addr:", broker_addr)

                cmd = 'goduck ether contract deploy --address http://{}:8545  --code-path $HOME/goduck/scripts/example/transfer.sol {}| grep 0x'.format(ethIp, broker_addr)
                transfer_addr = os.popen(cmd).read().split()[-1]
                print("\ttransfer addr:", transfer_addr)

                cmd = 'goduck ether contract invoke --key-path $HOME/goduck/scripts/docker/quick_start/account.key --abi-path $HOME/goduck/scripts/example/broker.abi --address http://{}:8545 {} audit "{}^1"'.format(ethIp, broker_addr, transfer_addr)
                os.popen(cmd).read()
                print("\t??????????????????")

                d[ethIp] = {"broker": broker_addr, "transfer": transfer_addr, "id": "ethappchain{}".format(appchainId), "bitxhub_id": bitxhubId}
                appchainId += 1

        json.dump(d, open("deploy_{}.json".format(self.namespace), "w"), indent=4)


    def create_deployment_pier(self, pier):
        path = pathlib.Path('k8s/deployment-pier.yaml')
        with path.open() as f:
            body = yaml.safe_load(f)

        config = None
        with open(pier) as f:
            config = json.load(f)

        if config is None:
            print(pier, "open failed")
            return
        
        # bitxhubInfo = os.popen("kubectl get pods -n {} -o wide | grep bitxhub".format(self.namespace)).read()
        # bitxhubIpList = [bitxhubItem.split()[-4] for bitxhubItem in bitxhubInfo.split('\n') if bitxhubItem != '']
        # bitxhubNameList = [bitxhubItem.split()[0] for bitxhubItem in bitxhubInfo.split('\n') if bitxhubItem != '']
        # print(bitxhubIpList)
        # print(bitxhubNameList)

        # ethInfo = os.popen("kubectl get pods -n {} -o wide | grep geth".format(self.namespace)).read()
        # ethIpList = [ethItem.split()[-4] for ethItem in ethInfo.split('\n') if ethItem != '']
        # ethNameList = [ethItem.split()[0] for ethItem in ethInfo.split('\n') if ethItem != '']
        # print(ethIpList)
        # print(ethNameList)

        nodeInfo = os.popen("kubectl get nodes -o wide").read()
        nodeIpList = [nodeItem.split()[5] for nodeItem in nodeInfo.split('\n') if nodeItem != '' and "Ready" in nodeItem]
        print(nodeIpList)

        pier_json = {}
        # graph_json = None
        # with open("graph_{}".format(self.namespace)) as f:
        #     graph_json = json.load(f)
        # graph = config["graph"]
        # for i in range(len(graph)):
        #     subGraph = graph[i]
        #     ethNum = subGraph["eth"]
        #     bitxhubIp = bitxhubIpList.pop()
        #     bitxhubName = bitxhubNameList.pop()
        #     ethIps = []
        #     ethNames = []
        #     for j in range(ethNum):
        #         ethIps.append(ethIpList.pop())
        #         ethNames.append(ethNameList.pop())
        #     graph_json[bitxhubName]["chainNameList"] = ethNames.copy()
        #     graph_json[bitxhubName]["chainIpList"] = ethIps.copy()
        #     graph_json[bitxhubName]["pierPrefixName"] = "pier-{}".format(i)
        #     # graph_json[bitxhubName] = {
        #     #     "chainNameList": ethNames.copy(),
        #     #     "chainIpList": ethIps.copy(),
        #     #     "pierPrefixName": "pier-{}".format(i)
        #     # }

        graph_json = None
        with open("graph_{}.json".format(self.namespace)) as f:
            graph_json = json.load(f)

        for i, (bitxhubName, item) in enumerate(graph_json.items()):
            bitxhubIp = item["bitxhubIp"]
            for j in range(len(item["chainIpList"])):
                ethIp = item["chainIpList"][j]
            #for j, ethIp in item["chainIpList"]:
                mount_pier = osp.join(config["base"], "mount_pier{}{}".format(i, j))
                cmd = "rm -rf {}".format(mount_pier)
                os.system(cmd)
                cmd = "mkdir -p {} && {} --repo={} init relay".format(mount_pier, config['pier'], mount_pier)
                os.system(cmd)
                cmd = "cp -r {} {} && cp -r {} {}".format(config['plugins'], osp.join(mount_pier, 'plugins'), config['ether'], osp.join(mount_pier, 'ether'))
                os.system(cmd)
                deploy_json = json.load(open("deploy_{}.json".format(self.namespace)))
                addrs = [bitxhubIp + ':6001{}'.format(i) for i in range(1, 5)]
                pier_toml = toml.load(osp.join(mount_pier, "pier.toml"))
                pier_toml['mode']['relay']['addrs'] = addrs
                pier_toml['mode']['relay']['timeout_limit'] = "10s"
                pier_toml['mode']['union']['addrs'] = addrs
                pier_toml['appchain']['id'] = deploy_json[ethIp]["id"]
                pier_toml['appchain']['plugin'] = "eth-client"
                pier_toml['appchain']['config'] = "ether"
                # print(toml.dumps(pier_toml))
                toml.dump(pier_toml, open(osp.join(mount_pier, "pier.toml"), "w"))

                ethereum_toml = toml.load(osp.join(mount_pier, "ether/ethereum.toml"))
                ethereum_toml['ether']['addr'] = "ws://{}:8546".format(ethIp)
                ethereum_toml['ether']['contract_address'] = deploy_json[ethIp]['broker']
                toml.dump(ethereum_toml, open(osp.join(mount_pier, "ether/ethereum.toml"), "w"))

                for nodeIp in nodeIpList:
                    if nodeIp == "10.206.0.7":
                        continue
                    cmd = "sshpass -p {} scp -r {} {}@{}:{}".format(config["passwd"], mount_pier, config["user"], nodeIp, config["base"])
                    print(cmd)
                    os.system(cmd)

                body['metadata']['name'] = "pier-{}-{}".format(i, j)

                body['spec']['containers'][0]['volumeMounts'][0]['name'] = "pier-{}-{}".format(i, j)
                body['spec']['containers'][0]['volumeMounts'][0]['mountPath'] = "/root/.pier"
                body['spec']['volumes'][0]['name'] = "pier-{}-{}".format(i, j)
                body['spec']['volumes'][0]['hostPath']['path'] = mount_pier
                body['spec']['volumes'][0]['hostPath']['type'] = "Directory"

                body['spec']['containers'][0]['name'] = "pier-0-{}".format(j)
                # body['spec']['containers'][0]['volumeMounts'][0]['name'] = "pier-0-{}-toml".format(j)
                # body['spec']['containers'][0]['volumeMounts'][1]['name'] = "pier-0-{}-ether".format(j)
                # body['spec']['containers'][0]['volumeMounts'][2]['name'] = "pier-0-{}-plugins".format(j)
                # body['spec']['volumes'][0]['name'] = "pier-0-{}-toml".format(j)
                # body['spec']['volumes'][0]['hostPath']['path'] = osp.join(mount_pier, "pier.toml")
                # body['spec']['volumes'][1]['name'] = "pier-0-{}-ether".format(j)
                # body['spec']['volumes'][1]['hostPath']['path'] = osp.join(mount_pier, "ether")
                # body['spec']['volumes'][2]['name'] = "pier-0-{}-plugins".format(j)
                # body['spec']['volumes'][2]['hostPath']['path'] = osp.join(mount_pier, "plugins")
                api_instance = client.CoreV1Api()
                api_instance.create_namespaced_pod(self.namespace, body)
                print("create namespaced pod {}:{}".format(bitxhubIp, ethIp))

                pier_json["pier-{}-{}".format(i, j)] = {
                    "bitxhubName": bitxhubName, 
                    "appchain_id": deploy_json[ethIp]["id"], 
                    "appchain_name": "eth{}{}".format(i, j),
                    "appchain_type": "ETH",
                    "appchain_ip": ethIp,
                }

        json.dump(pier_json, open("pier_{}.json".format(self.namespace), "w"), indent=4)
        #json.dump(graph_json, open("graph_{}.json".format(self.namespace), "w"), indent=4)
    
    def register(self, configPath):
        config = None
        with open(configPath) as f:
            config = json.load(f)
        if config is None:
            print(configPath, "open failed")
            return
        bitxhub_path = config["bitxhub"]

        pier = None
        with open("pier_{}.json".format(self.namespace)) as f:
            pier = json.load(f)
        if pier is None:
            print("pier_{}.json".format(self.namespace), "open failed")
            return
        
        deploy = None
        with open("deploy_{}.json".format(self.namespace)) as f:
            deploy = json.load(f)
        if deploy is None:
            print("deploy_{}.json".format(self.namespace), "open failed")
            return

        pierInfo = os.popen("kubectl get pods -n {} -o wide | grep pier".format(self.namespace)).read()
        pierNameList = [pierItem.split()[0] for pierItem in pierInfo.split('\n') if pierItem != '']
        pierIpList = [pierItem.split()[0] for pierItem in pierInfo.split('\n') if pierItem != '']

        def exec_cmd(pierName, cmd):
            cmd = "kubectl exec -it {} -n {} -- {}".format(pierName, self.namespace, cmd)
            print("\t", cmd)

            return os.popen(cmd).read()
            
        for pierName in pierNameList:
            print("handle pier", pierName)
            # cmd = "kubectl cp {} {}:/usr/local/bin -c {} -n {}".format(bitxhub_path, pierName, pierName, self.namespace)
            cmd = "kubectl cp {} {}:/usr/local/bin -n {}".format(bitxhub_path, pierName, self.namespace)
            print("\t", cmd)
            os.system(cmd)

            bitxhubName = pier[pierName]['bitxhubName']

            cmd = "bitxhub key show --path /root/.pier/key.json | grep address"
            pierId = exec_cmd(pierName, cmd).split()[-1]

            # ???????????????
            cmd = "bitxhub client transfer --key /root/bitxhub/scripts/build/node1/key.json --to {} --amount 100000000000000000".format(pierId)
            print("\t", exec_cmd(bitxhubName, cmd))

            cmd = 'pier --repo /root/.pier appchain register --appchain-id "{}" --name "{}"' \
                  ' --type "{}" --trustroot /root/.pier/ether/ether.validators --broker' \
                  ' {} --desc "desc" --master-rule "0x00000000000000000000000000000000000000a2"'\
                  ' --rule-url "http://github.com" --admin {}'\
                  ' --reason "reason"'.format(
                        pier[pierName]['appchain_id'], 
                        pier[pierName]['appchain_name'], 
                        pier[pierName]['appchain_type'],
                        deploy[pier[pierName]['appchain_ip']]['broker'],
                        pierId
                        )
            print("\t", exec_cmd(pierName, cmd))

            for nodeId in range(1, 4):
                cmd = 'bitxhub --repo /root/bitxhub/scripts/build/node{} client governance vote --id {}-0 --info approve --reason approve'.format(nodeId, pierId)
                print("\t", exec_cmd(bitxhubName, cmd))
            
            cmd = 'pier --repo /root/.pier appchain service register --appchain-id "{}"' \
                  ' --service-id "{}" --name "{}"'\
                  ' --intro "" --type CallContract --permit "" --details "test"--reason "reason"'.format(
                        pier[pierName]['appchain_id'], 
                        deploy[pier[pierName]['appchain_ip']]['transfer'],
                        "service-{}".format(pierName)
                  )
            print("\t", exec_cmd(pierName, cmd))

            for nodeId in range(1, 4):
                cmd = 'bitxhub --repo /root/bitxhub/scripts/build/node{} client governance vote --id {}-1 --info approve --reason approve'.format(nodeId, pierId)
                print("\t", exec_cmd(bitxhubName, cmd))

    def create_deployment_union_pier(self, pier):
        path = pathlib.Path('k8s/deployment-union-pier.yaml')
        with path.open() as f:
            body = yaml.safe_load(f)

        config = None
        with open(pier) as f:
            config = json.load(f)

        if config is None:
            print(pier, "open failed")
            return

        nodeInfo = os.popen("kubectl get nodes -o wide").read()
        nodeIpList = [nodeItem.split()[5] for nodeItem in nodeInfo.split('\n') if nodeItem != '' and "Ready" in nodeItem]
        print(nodeIpList)

        union_pier_json = {}
        graph_json = None
        with open("graph_{}.json".format(self.namespace)) as f:
            graph_json = json.load(f)

        for i, (bitxhubName, item) in enumerate(graph_json.items()):
            bitxhubIp = item["bitxhubIp"]
            bitxhubId = item["bitxhubId"]
            
            mount_union_pier = osp.join(config["base"], "mount_union_pier{}".format(i))
            cmd = "rm -rf {}".format(mount_union_pier)
            os.system(cmd)

            if i == 0:
                pier_path = config['root_pier']
            else:
                pier_path = config['pier']

            cmd = "mkdir -p {} && {} --repo={} init union --addPier 127.0.0.1:4343#fjksdd".format(mount_union_pier, pier_path, mount_union_pier)
            os.system(cmd)
            cmd = "{} --repo={} p2p id".format(pier_path, mount_union_pier)
            unionPierId = os.popen(cmd).read()
           
            deploy_json = json.load(open("deploy_{}.json".format(self.namespace)))
            addrs = [bitxhubIp + ':6001{}'.format(i) for i in range(1, 5)]
            pier_toml = toml.load(osp.join(mount_union_pier, "pier.toml"))
            pier_toml['mode']['relay']['addrs'] = addrs
            pier_toml['mode']['relay']['timeout_limit'] = "10s"
            pier_toml['mode']['union']['addrs'] = addrs
            print(toml.dumps(pier_toml))
            toml.dump(pier_toml, open(osp.join(mount_union_pier, "pier.toml"), "w"))


            for nodeIp in nodeIpList:
                if nodeIp == "10.206.0.7":
                    continue
                cmd = "sshpass -p {} scp -r {} {}@{}:{}".format(config["passwd"], mount_union_pier, config["user"], nodeIp, config["base"])
                print(cmd)
                os.system(cmd)

            body['metadata']['name'] = "union-{}".format(i)

            body['spec']['containers'][0]['volumeMounts'][0]['name'] = "union-{}".format(i)
            body['spec']['volumes'][0]['name'] = "union-{}".format(i)
            body['spec']['volumes'][0]['hostPath']['path'] = mount_union_pier
            body['spec']['volumes'][0]['hostPath']['type'] = "Directory"

            body['spec']['containers'][0]['name'] = "union-{}".format(i)
        
            api_instance = client.CoreV1Api()
            api_instance.create_namespaced_pod(self.namespace, body)

            union_pier_json["union-{}".format(i)] = {
                "bitxhubName": bitxhubName, 
                "bitxhubIp": bitxhubIp, 
                "bitxhubId": bitxhubId,
                #"union_pier_ip": unionPierIpList[i],
                "union_pier_port": "4343",
                "union_pier_p2p_id":unionPierId.strip(),
            }
        while True:
            unionPierInfo = os.popen("kubectl get pods -n {} -o wide | grep union".format(self.namespace)).read()
            unionPierIpList = [unionPierItem.split()[-4] for unionPierItem in unionPierInfo.split('\n') if unionPierItem != '']
            unionPierNameList = [unionPierItem.split()[0] for unionPierItem in unionPierInfo.split('\n') if unionPierItem != '']
            print(unionPierIpList)
            print(unionPierNameList)
            if "<none>" not in unionPierIpList:
                break
            print("container starting...")
            time.sleep(1)

        for i in range(len(unionPierIpList)):
            index = unionPierNameList.index("union-{}".format(i))
            union_pier_json["union-{}".format(i)]["union_pier_ip"] = unionPierIpList[index]

        json.dump(union_pier_json, open("union_{}.json".format(self.namespace), "w"), indent=4)

    def create_deployment_union_network_config(self, pier):
        config = None
        with open(pier) as f:
            config = json.load(f)

        if config is None:
            print(pier, "open failed")
            return

        union_json = None
        with open("union_{}.json".format(self.namespace)) as f:
            union_json = json.load(f)

        rootPierIp = union_json["union-0"]["union_pier_ip"]
        rootUnionPort = union_json["union-0"]["union_pier_port"]
        root_mount_union_pier = osp.join(config["base"], "mount_union_pier0")
        root_pier_toml = toml.load(osp.join(root_mount_union_pier, "network.toml"))
        root_hosts = ["/ip4/{}/tcp/{}/p2p/".format(rootPierIp, rootUnionPort)]
        root_pier_toml['piers'][0]['hosts'] = root_hosts
        root_pier_toml['piers'][0]['pid'] = union_json["union-0"]["union_pier_p2p_id"]
        root_struct = {"hosts": root_hosts, "pid": union_json["union-0"]["union_pier_p2p_id"]}

        for i, (unionName, item) in enumerate(union_json.items()):
            if i == 0:
                continue
            unionPort = item["union_pier_port"]
            unionP2pId = item["union_pier_p2p_id"]
            unionIp = item["union_pier_ip"]
            
            mount_union_pier = osp.join(config["base"], "mount_union_pier{}".format(i))
            pier_toml = toml.load(osp.join(mount_union_pier, "network.toml"))
            
            hosts = ["/ip4/{}/tcp/{}/p2p/".format(unionIp, unionPort)]
            pier_toml['piers'][0]['hosts'] = hosts
            pier_toml['piers'][0]['pid'] = unionP2pId
            pier_toml['piers'].append(root_struct)

            toml.dump(pier_toml, open(osp.join(mount_union_pier, "network.toml"), "w"))

            root_pier_toml['piers'].append(
                pier_toml['piers'][0]
            )
        toml.dump(root_pier_toml, open(osp.join(root_mount_union_pier, "network.toml"), "w"))

    def create_deployment_union_start(self, pier):
        config = None
        with open(pier) as f:
            config = json.load(f)

        if config is None:
            print(pier, "open failed")
            return

        union_json = None
        with open("union_{}.json".format(self.namespace)) as f:
            union_json = json.load(f)

        for i in range(len(union_json.items())):
            mount_union_pier = osp.join(config["base"], "mount_union_pier{}".format(i))
            unionPierName = "union-{}".format(i)
            # cmd = "kubectl cp {} {}:/usr/local/bin -c {} -n {}".format(bitxhub_path, pierName, pierName, self.namespace)
            cmd = "kubectl cp {}/network.toml {}:/root/.pier/ -n {}".format(mount_union_pier, unionPierName, self.namespace)
            print("\t", cmd)
            os.system(cmd)

            cmd = "cp {} {}".format("~/union.validators", mount_union_pier)
            print(cmd)
            os.system(cmd)

            cmd = "kubectl cp {}/union.validators {}:/root/.pier/ -n {}".format(mount_union_pier, unionPierName, self.namespace)
            print("\t", cmd)
            os.system(cmd)

            if i == 0:
                cmd = "kubectl cp {} {}:/usr/local/bin/pier -n {}".format(config["root_pier"], unionPierName, self.namespace)
            else:
                cmd = "kubectl cp {} {}:/usr/local/bin/pier -n {}".format(config["pier"], unionPierName, self.namespace)
            print("\t", cmd)
            os.system(cmd)

            cmd = 'kubectl exec {} -n {} -- sh -c "pier start > log.txt &"'.format(unionPierName, self.namespace)
            print("\t", cmd)
            os.system(cmd)
        

    def union_pier_register(self, configPath):
        config = None
        with open(configPath) as f:
            config = json.load(f)
        if config is None:
            print(configPath, "open failed")
            return

        union_json = None
        with open("union_{}.json".format(self.namespace)) as f:
            union_json = json.load(f)
        if union_json is None:
            print("union_{}.json".format(self.namespace), "open failed")
            return        

        def exec_cmd(pierName, cmd):
            cmd = "kubectl exec -it {} -n {} -- {}".format(pierName, self.namespace, cmd)
            print("\t", cmd)

            return os.popen(cmd).read()

        rootBitxhubName = union_json["union-0"]["bitxhubName"]
        rootBitxhubId = union_json["union-0"]["bitxhubId"]
        rootAppchainName = "bitxhub_{}".format(rootBitxhubId)
            
        for i, (unionName, item) in enumerate(union_json.items()):
            bitxhubName = item["bitxhubName"]

            if i == 0:
                bitxhub_path = config["root_bitxhub"]
            else:
                bitxhub_path = config["bitxhub"]
    
            cmd = "kubectl cp {} {}:/usr/local/bin/bitxhub -n {}".format(bitxhub_path, unionName, self.namespace)
            print("\t", cmd)
            os.system(cmd)

            cmd = "bitxhub key show --path /root/.pier/key.json | grep address"
            pierId = exec_cmd(unionName, cmd).split()[-1]

            # ???????????????
            cmd = "bitxhub client transfer --key /root/bitxhub/scripts/build/node1/key.json --to {} --amount 100000000000000000".format(pierId)
            print("\t", exec_cmd(bitxhubName, cmd))


            if i != 0:
                cmd = 'pier --repo /root/.pier appchain register --appchain-id "{}" --name "{}"' \
                    ' --type "{}" --trustroot /root/.pier/union.validators ' \
                    ' --broker "0x0000000000000000000000000000000000000019"' \
                    ' --desc "desc" --master-rule "0x00000000000000000000000000000000000000a2"'\
                    ' --rule-url "http://github.com" --admin {}'\
                    ' --reason "reason"'.format(
                            rootBitxhubId, 
                            rootAppchainName, 
                            "relaychain",
                            pierId
                            )
                print("\t", exec_cmd(unionName, cmd))

                for nodeId in range(1, 4):
                    cmd = 'bitxhub --repo /root/bitxhub/scripts/build/node{} client governance vote --id {}-0 --info approve --reason approve'.format(nodeId, pierId)
                    print("\t", exec_cmd(bitxhubName, cmd))

            else:
                for j in range(1, len(union_json.items())):
                    bitxhubId = union_json["union-{}".format(j)]["bitxhubId"]
                    appchainName = "bitxhub_{}".format(bitxhubId)
                    cmd = 'pier --repo /root/.pier appchain register --appchain-id "{}" --name "{}"' \
                            ' --type "{}" --trustroot /root/.pier/union.validators ' \
                            ' --broker "0x0000000000000000000000000000000000000019"' \
                            ' --desc "desc" --master-rule "0x00000000000000000000000000000000000000a2"'\
                            ' --rule-url "http://github.com" --admin {}'\
                            ' --reason "reason"'.format(
                                bitxhubId, 
                                appchainName, 
                                "relaychain",
                                pierId
                                )
                    print("\t", exec_cmd(unionName, cmd))

                    for nodeId in range(1, 4):
                        cmd = 'bitxhub --repo /root/bitxhub/scripts/build/node{} client governance vote --id {}-{} --info approve --reason approve'.format(nodeId, pierId, j-1)
                        print("\t", exec_cmd(bitxhubName, cmd))




def main():
    parser = argparse.ArgumentParser(description='k8s ethereum')
    parser.add_argument('--name', dest='name', required=True)
    parser.add_argument('--light', dest='light', action='store_true', default=False)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--create', dest='create', default="")
    group.add_argument('--delete', dest='delete', action='store_true', default=False)
    group.add_argument('--deploy', dest='deploy', action='store_true', default=False)
    group.add_argument('--pier', dest='pier', default="")
    group.add_argument('--register', dest='register', default="")
    group.add_argument('--union', dest='union', default="")
    group.add_argument('--unionConfig', dest='config', default="")
    group.add_argument('--unionStart', dest='start', default="")
    group.add_argument('--unionRegister', dest='URegister', default="")
    args = parser.parse_args()

    if args.light:
        logging.info('Starting Geth Light Client')
        n = GethLightClient(args.name)
    else:
        logging.info('Starting Geth in Private Network')
        n = PrivateNetwork(args.name)
    
    if args.create != "":
        logger.info(f'Creating "{args.name}"')
        n.create_by_config(args.create)
    elif args.delete:
        logger.info(f'Deleting "{args.name}"')
        n.delete()
    elif args.pier != "":
        n.create_deployment_pier(args.pier)
    elif args.union != "":
        n.create_deployment_union_pier(args.union)
    elif args.config != "":
        n.create_deployment_union_network_config(args.config)
    elif args.start != "":
        n.create_deployment_union_start(args.start)
    elif args.URegister != "":
        n.union_pier_register(args.URegister)
    elif args.deploy:
        n.deploy()
    elif args.register != "":
        n.register(args.register)


if __name__ == '__main__':
    main()
