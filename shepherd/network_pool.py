import base64
import os
import traceback


# ============================================================================
class NetworkPool(object):
    NETWORK_NAME = 'shepherd.net-{0}'
    NETWORK_LABEL = 'owt.network.managed'

    def __init__(self, docker, network_templ=None, name='owt.netpool.default'):
        self.docker = docker
        self.network_templ = network_templ or self.NETWORK_NAME
        self.labels = {self.NETWORK_LABEL: name}
        self.pool_name = name

    def new_name(self):
        name = base64.b32encode(os.urandom(10)).decode('utf-8')
        return self.network_templ.format(name)

    def create_network(self):
        name = self.new_name()
        return self.docker.networks.create(name, labels=self.labels)

    def remove_network(self, network):
        try:
            assert(network.attrs['Labels'][self.NETWORK_LABEL] == self.pool_name)
            network.remove()
            return True
        except Exception as e:
            return False

    def shutdown(self):
        pass


# ============================================================================
class CachedNetworkPool(NetworkPool):
    NETWORKS_LIST_KEY = 'n:{0}'

    def __init__(self, docker, redis, max_size=10, **kwargs):
        super(CachedNetworkPool, self).__init__(docker, **kwargs)
        self.max_size = max_size
        self.redis = redis
        self.networks_key = self.NETWORKS_LIST_KEY.format(self.pool_name)

    def shutdown(self):
        while True:
            network_name = self.redis.spop(self.networks_key)
            if not network_name:
                break

            try:
                network = self.docker.networks.get(network_name)
                network.remove()
            except:
                pass

    def create_network(self):
        try:
            name = self.redis.spop(self.networks_key)
            network = self.docker.networks.get(name)
            return network
        except:
            return super(CachedNetworkPool, self).create_network()

    def remove_network(self, network):
        try:
            if self.redis.scard(self.networks_key) >= self.max_size:
                return super(CachedNetworkPool, self).remove_network(network)

            network.reload()
            if len(network.containers) != 0:
                return False

            self.redis.sadd(self.networks_key, network.name)
            return True

        except:
            traceback.print_exc()
            return False


