from gevent.monkey import patch_all; patch_all()
import pytest
import time


# ============================================================================
@pytest.mark.usefixtures('client_class', 'docker_client')
class TestTimedPoolShutdownContainer:
    def test_start_flock(self, pool, redis):
        res = self.client.post('/api/request_flock/test_b')
        reqid = res.json['reqid']

        res = self.client.post('/api/start_flock/' + reqid)
        assert res.json['network']
        assert res.json['containers']['box']

        TestTimedPoolShutdownContainer.container = res.json['containers']['box']
        TestTimedPoolShutdownContainer.reqid = reqid

        assert redis.scard('p:test-pool:f') == 1
        assert redis.ttl('p:test-pool:rq:'+ reqid) <= 1.0

    def test_flock_kill_container(self, redis, pool, docker_client):
        assert redis.exists('p:test-pool:rq:' + self.reqid)

        docker_client.containers.get(self.container['id']).kill()

        time.sleep(1.1)

        assert not redis.exists('p:test-pool:rq:' + self.reqid)
        assert redis.scard('p:test-pool:f') == 0
        assert len(pool.stop_events) == 2

