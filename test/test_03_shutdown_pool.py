from gevent.monkey import patch_all; patch_all()
import pytest
import time
from utils import sleep_try


# ============================================================================
@pytest.mark.usefixtures('client_class', 'docker_client')
class TestTimedPoolShutdownContainer:
    def test_flock_start(self, redis):
        res = self.client.post('/api/flock/request/test_b')
        reqid = res.json['reqid']

        res = self.client.post('/api/flock/start/' + reqid)
        assert res.json['network']
        assert res.json['containers']['box']

        TestTimedPoolShutdownContainer.container = res.json['containers']['box']
        TestTimedPoolShutdownContainer.reqid = reqid

        def assert_done():
            assert redis.scard('p:test-pool:f') == 1
            assert redis.ttl('p:test-pool:rq:'+ reqid) == 1.0

        sleep_try(0.2, 6.0, assert_done)

    def test_flock_kill_container(self, redis, app, docker_client):
        assert redis.exists('p:test-pool:rq:' + self.reqid)

        try:
            docker_client.containers.get(self.container['id']).kill()
        except:
            pass

        pool = app.pools['test-pool']

        def assert_done():
            assert not redis.exists('p:test-pool:rq:' + self.reqid)
            assert redis.scard('p:test-pool:f') == 0
            assert len(pool.stop_events) == 2

        sleep_try(0.2, 6.0, assert_done)


