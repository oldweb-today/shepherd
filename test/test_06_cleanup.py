from gevent.monkey import patch_all; patch_all()

import pytest
import time
import itertools
import docker

from shepherd.wsgi import create_app

@pytest.mark.usefixtures('client_class', 'docker_client')
class TestCleanup(object):
    @classmethod
    def sleep_try(cls, sleep_interval, max_time, test_func):
        max_count = float(max_time) / sleep_interval
        for counter in itertools.count():
            try:
                time.sleep(sleep_interval)
                test_func()
                return
            except:
                if counter >= max_count:
                    raise

    def _count_containers(self, docker_client, shepherd):
        return len(docker_client.containers.list(filters={'label': shepherd.reqid_label}))

    def _count_volumes(self, docker_client, shepherd):
        return len(docker_client.volumes.list(filters={'label': shepherd.reqid_label}))

    def _count_networks(self, docker_client, shepherd):
        return len(docker_client.networks.list(filters={'label': shepherd.network_pool.network_label}))

    def test_ensure_flock_stop(self, docker_client):
        res = self.client.post('/api/request_flock/test_b')

        reqid = res.json['reqid']

        res = self.client.post('/api/start_flock/{0}'.format(reqid))

        assert res.json['containers']

        box = docker_client.containers.get(res.json['containers']['box']['id'])
        box_2 = docker_client.containers.get(res.json['containers']['box-2']['id'])

        box.remove(force=True)

        def assert_removed():
            with pytest.raises(docker.errors.NotFound):
                box = docker_client.containers.get(res.json['containers']['box-2']['id'])

        self.sleep_try(0.3, 10.0, assert_removed)

    def test_check_untracked_cleanup(self, docker_client, redis, shepherd):
        num_containers = self._count_containers(docker_client, shepherd)
        num_volumes = self._count_volumes(docker_client, shepherd)
        num_networks = self._count_volumes(docker_client, shepherd)

        for x in range(0, 3):
            res = self.client.post('/api/request_flock/test_vol')

            reqid = res.json['reqid']

            res = self.client.post('/api/start_flock/{0}'.format(reqid))

            assert res.json['containers']

        assert num_containers < self._count_containers(docker_client, shepherd)
        assert num_volumes < self._count_volumes(docker_client, shepherd)
        assert num_networks < self._count_networks(docker_client, shepherd)

        # wipe all redis data
        redis.flushdb()

        def assert_removed():
            assert num_containers == self._count_containers(docker_client, shepherd)
            assert num_volumes == self._count_volumes(docker_client, shepherd)
            assert num_networks == self._count_networks(docker_client, shepherd)

        self.sleep_try(0.5, 10.0, assert_removed)
