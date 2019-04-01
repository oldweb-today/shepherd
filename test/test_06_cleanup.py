from gevent.monkey import patch_all; patch_all()

import pytest
import docker

from shepherd.wsgi import create_app
from utils import sleep_try


@pytest.mark.usefixtures('client_class', 'docker_client', 'shepherd')
class TestCleanup(object):
    def _count_containers(self, docker_client, shepherd):
        return len(docker_client.containers.list(filters={'label': shepherd.reqid_label}, ignore_removed=True))

    def _count_volumes(self, docker_client, shepherd):
        return len(docker_client.volumes.list(filters={'label': shepherd.reqid_label}))

    def _count_networks(self, docker_client, shepherd):
        return len(docker_client.networks.list(filters={'label': shepherd.network_pool.network_label}))

    def test_start_loop(self, shepherd):
        assert shepherd.untracked_check_time == 0
        shepherd.start_cleanup_loop(2.0)
        assert shepherd.untracked_check_time == 2.0

    def test_ensure_flock_stop(self, docker_client):
        res = self.client.post('/api/flock/request/test_b')

        reqid = res.json['reqid']

        res = self.client.post('/api/flock/start/{0}'.format(reqid))

        assert res.json['containers']

        box = docker_client.containers.get(res.json['containers']['box']['id'])
        box_2 = docker_client.containers.get(res.json['containers']['box-2']['id'])

        box.remove(force=True)

        def assert_removed():
            with pytest.raises(docker.errors.NotFound):
                box = docker_client.containers.get(res.json['containers']['box-2']['id'])

        sleep_try(0.3, 10.0, assert_removed)

    def test_check_untracked_cleanup(self, docker_client, redis, shepherd):
        num_containers = self._count_containers(docker_client, shepherd)
        num_volumes = self._count_volumes(docker_client, shepherd)
        num_networks = self._count_volumes(docker_client, shepherd)

        for x in range(0, 3):
            res = self.client.post('/api/flock/request/test_vol')

            reqid = res.json['reqid']

            res = self.client.post('/api/flock/start/{0}'.format(reqid))

            assert res.json['containers']

        assert num_containers < self._count_containers(docker_client, shepherd)
        assert num_volumes < self._count_volumes(docker_client, shepherd)
        assert num_networks < self._count_networks(docker_client, shepherd)

        # wipe all redis data
        redis.flushdb()

        def assert_removed():
            assert num_containers == self._count_containers(docker_client, shepherd)
            assert num_volumes == self._count_volumes(docker_client, shepherd)
            #assert num_networks == self._count_networks(docker_client, shepherd)

        sleep_try(2.0, 20.0, assert_removed)

    def test_redis_pool_and_reqid_cleanup(self, docker_client, redis):
        reqids = []

        # start and kill containers
        res = self.client.post('/api/flock/request/test_vol', json={'user_params': {'foo': 'bar'}})

        reqid = res.json['reqid']

        res = self.client.post('/api/flock/start/{0}'.format(reqid))

        reqids.append(reqid)

        try:
            docker_client.containers.get(res.json['containers']['box-1']['id']).remove(force=True)
        except:
            pass

        try:
            docker_client.containers.get(res.json['containers']['box-2']['id']).remove(force=True)
        except:
            pass

        def assert_removed():
            for reqid in reqids:
                assert not redis.exists('req:' + reqid)

            assert len(redis.smembers('p:test-pool:f')) == 0
            assert redis.keys('*') == []

        sleep_try(1.0, 10.0, assert_removed)
