from gevent.monkey import patch_all; patch_all()
import pytest
from utils import sleep_try


# ============================================================================
@pytest.mark.usefixtures('client_class', 'docker_client')
class TestTimedPoolApi:
    def test_flock_start(self, redis):
        res = self.client.post('/api/flock/request/test_b')
        reqid = res.json['reqid']

        res = self.client.post('/api/flock/start/' + reqid)
        assert res.json['network']
        assert res.json['containers']['box']

        assert redis.scard('p:test-pool:f') == 1
        assert redis.ttl('p:test-pool:rq:'+ reqid) <= 1.0

        TestTimedPoolApi.reqid = reqid

    def test_flock_still_running(self, redis):
        def assert_done():
            assert redis.exists('p:test-pool:rq:' + self.reqid)
            assert redis.scard('p:test-pool:f') == 1

        sleep_try(0.2, 6.0, assert_done)

    def test_flock_wait_expire(self, redis):
        def assert_done():
            assert not redis.exists('p:test-pool:rq:' + self.reqid)
            assert redis.scard('p:test-pool:f') == 0

        sleep_try(0.2, 6.0, assert_done)

