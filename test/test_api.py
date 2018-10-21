import pytest


from shepherd.wsgi import create_app

@pytest.fixture
def app(shepherd):
    wsgi_app = create_app(shepherd)
    return wsgi_app


@pytest.mark.usefixtures('client_class', 'docker_client')
class TestShepherdApi:
    def test_api(self):
        res = self.client.get('/api')
        assert 'GenericResponseSchema' in res.data.decode('utf-8')

    def test_request_invalid_flock(self):
        res = self.client.post('/api/request_flock/foo', json={'user_params': {'a': 'b'}})
        assert res.json == {'error': 'invalid_flock', 'flock': 'foo'}
        assert res.status_code == 404

    def test_request_invalid_req_params(self):
        res = self.client.post('/api/request_flock/test_1', json={'blah': 'foo', 'user_params': {'a': 'b'}})
        assert res.json == {'error': "{'blah': ['Unknown field.']}"}
        assert res.status_code == 400

    def test_request_invalid_overrides(self):
        res = self.client.post('/api/request_flock/test_b', json={'overrides': {'box': 'test-shepherd/alpine'}})
        assert res.json == {'error': 'invalid_image_param',
                            'image_expected': 'test-shepherd/busybox',
                            'image_passed': 'test-shepherd/alpine'}

    def test_request_flock(self):
        res = self.client.post('/api/request_flock/test_b', json={'user_params': {'a': 'b'}})
        assert res.json['reqid']
        TestShepherdApi.reqid = res.json['reqid']

    def test_start_invalid_flock(self):
        res = self.client.post('/api/start_flock/x-invalid')
        assert res.json == {'error': 'invalid_reqid'}

    def test_start_flock(self):
        res = self.client.post('/api/start_flock/' + self.reqid)
        assert res.json['network']
        assert res.json['containers']['box']

    def test_stop_flock(self):
        res = self.client.post('/api/stop_flock/' + self.reqid)
        assert res.json['success'] == True



