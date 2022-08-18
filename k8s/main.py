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

    def delete(self):
        # this will delete all objects under the namespace
        self.delete_namespace()

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
        ethInfo = os.popen("kubectl get pods -n {} -o wide | grep geth".format(self.namespace)).read()
        ethIpList = [ethItem.split()[-4] for ethItem in ethInfo.split('\n') if ethItem != '']
        d = {}
        for i, ethIp in enumerate(ethIpList):
            print("handle ip: ", ethIp)
            cmd = 'goduck ether contract deploy --code-path $HOME/goduck/scripts/example/broker.sol --address http://{}:8545  "1356^ethappchain{}^["0xc7F999b83Af6DF9e67d0a37Ee7e900bF38b3D013","0x79a1215469FaB6f9c63c1816b45183AD3624bE34","0x97c8B516D19edBf575D72a172Af7F418BE498C37","0xc0Ff2e0b3189132D815b8eb325bE17285AC898f8"]^1^["0x20F7Fac801C5Fc3f7E20cFbADaA1CDb33d818Fa3"]^1"| grep 0x'.format(ethIp, i + 1)
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
            print("\t合约审计成功")

            d[ethIp] = {"broker": broker_addr, "transfer": transfer_addr, "id": "ethappchain{}".format(i + 1)}
        json.dump(d, open("addr_{}.json".format(self.namespace), "w"), indent=4)


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
        
        bitxhubInfo = os.popen("kubectl get pods -n {} -o wide | grep bitxhub".format(self.namespace)).read()
        bitxhubIpList = [bitxhubItem.split()[-4] for bitxhubItem in bitxhubInfo.split('\n') if bitxhubItem != '']
        print(bitxhubIpList)

        ethInfo = os.popen("kubectl get pods -n {} -o wide | grep geth".format(self.namespace)).read()
        ethIpList = [ethItem.split()[-4] for ethItem in ethInfo.split('\n') if ethItem != '']
        print(ethIpList)

        graph = config["graph"]
        for i in range(len(graph)):
            subGraph = graph[i]
            ethNum = subGraph["eth"]
            bitxhubIp = bitxhubIpList.pop()
            ethIps = []
            for j in range(ethNum):
                ethIps.append(ethIpList.pop())

            for j, ethIp in enumerate(ethIps):
                mount_pier = osp.join(config["base"], "mount_pier{}{}".format(i, j))
                cmd = "rm -rf {}".format(mount_pier)
                os.system(cmd)
                cmd = "mkdir -p {} && {} --repo={} init relay".format(mount_pier, config['pier'], mount_pier)
                os.system(cmd)
                cmd = "cp -r {} {} && cp -r {} {}".format(config['plugins'], osp.join(mount_pier, 'plugins'), config['ether'], osp.join(mount_pier, 'ether'))
                os.system(cmd)
                addr_json = json.load(open("addr_{}.json".format(self.namespace)))
                addrs = [bitxhubIp + ':6001{}'.format(i) for i in range(1, 5)]
                pier_toml = toml.load(osp.join(mount_pier, "pier.toml"))
                pier_toml['mode']['relay']['addrs'] = addrs
                pier_toml['mode']['relay']['timeout_limit'] = "10s"
                pier_toml['mode']['union']['addrs'] = addrs
                pier_toml['appchain']['id'] = addr_json[ethIp]["id"]
                pier_toml['appchain']['plugin'] = "eth-client"
                pier_toml['appchain']['config'] = "ether"
                # print(toml.dumps(pier_toml))
                toml.dump(pier_toml, open(osp.join(mount_pier, "pier.toml"), "w"))

                ethereum_toml = toml.load(osp.join(mount_pier, "ether/ethereum.toml"))
                ethereum_toml['ether']['addr'] = "ws://{}:8546".format(ethIp)
                ethereum_toml['ether']['contract_address'] = addr_json[ethIp]['broker']
                toml.dump(ethereum_toml, open(osp.join(mount_pier, "ether/ethereum.toml"), "w"))

                cmd = "sshpass -p asdsaads. scp -r {} jyb@10.206.0.11:{}".format(mount_pier, config["base"])
                print(cmd)
                os.system(cmd)
                cmd = "sshpass -p asdsaads. scp -r {} jyb@10.206.0.5:{}".format(mount_pier, config["base"])
                print(cmd)
                os.system(cmd)

                body['metadata']['name'] = "pier-0-{}".format(j)

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
            # self.create_deployment_by_path('k8s/deployment-pier.yaml')
    
    def register(self, configPath):
        config = None
        with open(configPath) as f:
            config = json.load(f)
        if config is None:
            print(config, "open failed")
            return
        pierInfo = os.popen("kubectl get pods -n {} -o wide | grep pier".format(self.namespace)).read()
        pierNameList = [pierItem.split()[0] for pierItem in pierInfo.split('\n') if pierItem != '']
        for pierName in pierNameList:
            cmd = "kubectl cp {} {}:/usr/local/bin -c {} -n {}".format(config["bitxhub"], pierName, pierName, self.namespace)
            os.system(cmd)



def main():
    parser = argparse.ArgumentParser(description='k8s ethereum')
    parser.add_argument('--name', dest='name', required=True)
    parser.add_argument('--light', dest='light', action='store_true', default=False)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--create', dest='create', action='store_true', default=False)
    group.add_argument('--delete', dest='delete', action='store_true', default=False)
    group.add_argument('--deploy', dest='deploy', action='store_true', default=False)
    group.add_argument('--pier', dest='pier', default="")
    group.add_argument('--register', dest='register', default="")
    args = parser.parse_args()

    if args.light:
        logging.info('Starting Geth Light Client')
        n = GethLightClient(args.name)
    else:
        logging.info('Starting Geth in Private Network')
        n = PrivateNetwork(args.name)
    
    if args.create:
        logger.info(f'Creating "{args.name}"')
        n.create()
    elif args.delete:
        logger.info(f'Deleting "{args.name}"')
        n.delete()
    elif args.pier != "":
        n.create_deployment_pier(args.pier)
    elif args.deploy:
        n.deploy()
    elif args.register != "":
        n.register(args.register)


if __name__ == '__main__':
    main()
