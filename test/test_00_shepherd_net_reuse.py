from gevent.monkey import patch_all; patch_all()
import pytest
import time
import docker

from shepherd.network_pool import CachedNetworkPool


@pytest.fixture(scope='function')
def reuse_network_pool(docker_client, redis):
    return CachedNetworkPool(docker_client, redis, network_templ='test-cached-pool', max_size=10)


# ============================================================================
@pytest.mark.usefixtures('client_class', 'docker_client')
class TestNetReuse:
    def launch(self, shepherd, docker_client, reuse_network_pool):
        res = shepherd.request_flock('test_b')

        reqid = res['reqid']

        res = shepherd.start_flock(reqid, network_pool=reuse_network_pool)

        assert res['containers']['box']
        assert res['containers']['box-2']

        box = docker_client.containers.get(res['containers']['box']['id'])
        box_2 = docker_client.containers.get(res['containers']['box-2']['id'])

        networks = list(box.attrs['NetworkSettings']['Networks'].keys())
        assert len(networks) == 1

        return reqid, networks[0]

    def test_launch_keep_network(self, shepherd, docker_client, reuse_network_pool):
        reqid, network = self.launch(shepherd, docker_client, reuse_network_pool)

        TestNetReuse.net_name = network

        res = shepherd.stop_flock(reqid, network_pool=reuse_network_pool)

        assert res == {'success': True}

    def test_network_still_exists(self, docker_client):
        assert docker_client.networks.get(self.net_name)

    def test_reuse(self, shepherd, docker_client, reuse_network_pool):
        reqid, network = self.launch(shepherd, docker_client, reuse_network_pool)

        assert TestNetReuse.net_name == network

        res = shepherd.stop_flock(reqid, network_pool=reuse_network_pool)

        assert res == {'success': True}

    def test_shutdown(self, docker_client, reuse_network_pool):
        reuse_network_pool.shutdown()

        with pytest.raises(docker.errors.NotFound):
            assert docker_client.networks.get(self.net_name)

