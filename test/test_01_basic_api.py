from gevent.monkey import patch_all; patch_all()
import pytest
from utils import sleep_try


# ============================================================================
@pytest.mark.usefixtures('client_class', 'docker_client')
class TestBasicApi:
    def test_api(self):
        res = self.client.get('/api')
        assert 'GenericResponseSchema' in res.data.decode('utf-8')

    def test_request_invalid_flock(self):
        res = self.client.post('/api/request_flock/foo', json={'user_params': {'a': 'b'}})
        assert res.json == {'error': 'invalid_flock', 'flock': 'foo'}
        assert res.status_code == 404

    def test_request_invalid_req_params(self):
        res = self.client.post('/api/request_flock/test_1', json={'blah': 'foo', 'user_params': {'a': 'b'}})
        assert res.json == {'details': "{'blah': ['Unknown field.']}", 'error': 'invalid_options'}
        assert res.status_code == 400

    def test_request_invalid_overrides(self):
        res = self.client.post('/api/request_flock/test_b', json={'overrides': {'box': 'test-shepherd/alpine'}})
        assert res.json == {'error': 'invalid_image_param',
                            'image_expected': 'test-shepherd/busybox',
                            'image_passed': 'test-shepherd/alpine'}

    def test_request_environ_allow_bool(self):
        res = self.client.post('/api/request_flock/test_b', json={'user_params': {'a': 'b'},
                                                                  'environ': {'FOO': True}})

        assert res.json['reqid']

    def test_request_flock(self):
        res = self.client.post('/api/request_flock/test_b', json={'user_params': {'a': 'b'},
                                                                  'environ': {'FOO': 'BAR'}})
        assert res.json['reqid']
        TestBasicApi.reqid = res.json['reqid']

    def test_invalid_pool(self, redis):
        res = self.client.post('/api/bad-pool/request_flock/test_b')
        assert res.json == {'error': 'no_such_pool', 'pool': 'bad-pool'}

    def test_start_invalid_flock(self, redis):
        res = self.client.post('/api/start_flock/x-invalid')
        assert res.json == {'error': 'invalid_reqid'}

        assert not redis.hget('p:test-pool:i', 'size')

    def test_start_flock(self, pool, redis):
        res = self.client.post('/api/start_flock/' + self.reqid,
                               json={'environ': {'NEW': 'VALUE'}})

        assert res.json['containers']['box']
        assert res.json['containers']['box']['environ']['NEW'] == 'VALUE'
        assert res.json['network']

        def assert_done():
            assert len(pool.start_events) == 2

        sleep_try(0.2, 6.0, assert_done)

        for event in pool.start_events:
            assert event['Action'] == 'start'
            assert event['Actor']['Attributes'][pool.shepherd.reqid_label] == self.reqid

        assert redis.exists('p:test-pool:rq:' + self.reqid)
        assert redis.scard('p:test-pool:f') == 1

    def test_stop_flock(self, pool, redis):
        res = self.client.post('/api/stop_flock/' + self.reqid)
        assert res.json['success'] == True

        def assert_done():
            assert len(pool.stop_events) == 2

        sleep_try(0.2, 6.0, assert_done)

        for event in pool.stop_events:
            assert event['Action'] == 'die'
            assert event['Actor']['Attributes'][pool.shepherd.reqid_label] == self.reqid

        assert not redis.exists('p:test-pool:rq:' + self.reqid)
        assert redis.scard('p:test-pool:f') == 0


