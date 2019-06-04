from gevent.monkey import patch_all; patch_all()
import pytest
from utils import sleep_try

@pytest.fixture(scope='module')
def pool(app):
    return app.pools['test-pool']


# ============================================================================
@pytest.mark.usefixtures('client_class', 'docker_client')
class TestBasicApi:
    def test_api(self):
        res = self.client.get('/api')
        assert 'GenericResponse' in res.data.decode('utf-8')

    def test_request_invalid_flock(self):
        res = self.client.post('/api/flock/request/foo', json={'user_params': {'a': 'b'}})
        assert res.json == {'error': 'invalid_flock', 'flock': 'foo'}
        assert res.status_code == 404

    def test_request_invalid_req_params(self):
        res = self.client.post('/api/flock/request/test_1', json={'blah': 'foo', 'user_params': {'a': 'b'}})
        assert res.json == {'details': "{'blah': ['Unknown field.']}", 'error': 'invalid_options'}
        assert res.status_code == 400

    def test_request_invalid_overrides(self):
        res = self.client.post('/api/flock/request/test_b', json={'overrides': {'box': 'test-shepherd/alpine'}})
        assert res.json == {'error': 'invalid_image_param',
                            'image_passed': 'test-shepherd/alpine',
                            'label_expected': 'test.isbox=box'}

    def test_request_environ_allow_bool(self):
        res = self.client.post('/api/flock/request/test_b', json={'user_params': {'a': 'b'},
                                                                  'environ': {'FOO': True}})

        assert res.json['reqid']

    def test_flock_request(self):
        res = self.client.post('/api/flock/request/test_b', json={'user_params': {'a': 'b'},
                                                                  'environ': {'FOO': 'BAR'}})
        assert res.json['reqid']
        TestBasicApi.reqid = res.json['reqid']

    def test_invalid_pool(self, redis):
        res = self.client.post('/api/flock/request/test_b?pool=bad-pool')
        assert res.json == {'error': 'no_such_pool', 'pool': 'bad-pool'}

    def test_start_invalid_flock(self, redis):
        res = self.client.post('/api/flock/start/x-invalid')
        assert res.json == {'error': 'invalid_reqid'}

        assert not redis.hget('p:test-pool:i', 'size')

    def test_flock_start(self, pool, redis):
        res = self.client.post('/api/flock/start/' + self.reqid,
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

    def test_get_flock(self, pool, redis):
        res = self.client.get('/api/flock/' + self.reqid)
        assert res.json['user_params'] == {'a': 'b'}
        assert res.json['environ']
        assert res.json['image_list']
        assert res.json['id']

    def test_flock_stop(self, pool, redis):
        res = self.client.post('/api/flock/stop/' + self.reqid)
        assert res.json['success'] == True

        def assert_done():
            assert len(pool.stop_events) == 2

        sleep_try(0.2, 6.0, assert_done)

        for event in pool.stop_events:
            assert event['Action'] == 'die'
            assert event['Actor']['Attributes'][pool.shepherd.reqid_label] == self.reqid

        assert not redis.exists('p:test-pool:rq:' + self.reqid)
        assert redis.scard('p:test-pool:f') == 0

    def test_flock_remove(self, pool, redis):
        res = self.client.post('/api/flock/remove/' + self.reqid)
        assert res.json['success'] == True


