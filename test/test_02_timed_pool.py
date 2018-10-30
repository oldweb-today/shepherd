from gevent.monkey import patch_all; patch_all()
import pytest
import time


# ============================================================================
@pytest.mark.usefixtures('client_class', 'docker_client')
class TestTimedPoolApi:
    def test_start_flock(self, pool, redis):
        res = self.client.post('/api/request_flock/test_b')
        reqid = res.json['reqid']

        res = self.client.post('/api/start_flock/' + reqid)
        assert res.json['network']
        assert res.json['containers']['box']

        assert redis.scard('p:test-pool:f') == 1
        assert redis.ttl('p:test-pool:rq:'+ reqid) <= 1.0

        TestTimedPoolApi.reqid = reqid

    def test_flock_still_running(self, redis):
        time.sleep(0.9)

        assert redis.exists('p:test-pool:rq:' + self.reqid)
        assert redis.scard('p:test-pool:f') == 1

    def test_flock_wait_expire(self, redis):
        time.sleep(3.2)

        assert not redis.exists('p:test-pool:rq:' + self.reqid)
        assert redis.scard('p:test-pool:f') == 0


