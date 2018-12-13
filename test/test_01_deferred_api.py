from gevent.monkey import patch_all; patch_all()
import pytest
import time
import itertools

from shepherd.wsgi import create_app


@pytest.fixture(scope='module')
def app(pool, shepherd):
    pools = {'pool': pool,
            }
    wsgi_app = create_app(shepherd, pools)
    return wsgi_app


@pytest.mark.usefixtures('client_class', 'docker_client')
class TestDeferred(object):
    def test_deferred_flock_start(self):
        res = self.client.post('/api/pool/request_flock/test_deferred')

        TestDeferred.reqid = res.json['reqid']

        res = self.client.post('/api/pool/start_flock/{0}'.format(self.reqid))

        assert res.json['containers']
        assert 'deferred' in res.json['containers']['box-p']
        assert 'deferred' not in res.json['containers']['box-1']

    def test_deferred_start_container(self):
        res = self.client.post('/api/pool/start_deferred/{0}/box-p'.format(self.reqid))

        assert res.json['id']
        assert res.json['ip']
        assert res.json['ports']['port_a']

        # same result, already started
        res2 = self.client.post('/api/pool/start_deferred/{0}/box-p'.format(self.reqid))
        assert res.json == res2.json

    def test_deferred_err_not_deferred(self):
        res = self.client.post('/api/pool/start_deferred/{0}/box-1'.format(self.reqid))
        assert res.json == {'error': 'invalid_deferred', 'flock': 'test_deferred'}

    def test_deferred_flock_stop(self):
        res = self.client.post('/api/pool/stop_flock/{0}'.format(self.reqid))
        assert res.json == {'success': True}

    def test_deferred_only(self):
        res = self.client.post('/api/pool/request_flock/test_def_only')

        self.reqid = res.json['reqid']

        res = self.client.post('/api/pool/start_flock/{0}'.format(self.reqid))

        for n, container in res.json['containers'].items():
            assert container['deferred']
            assert set(container.keys()) == {'deferred', 'image'}

        res = self.client.post('/api/pool/start_deferred/{0}/box-p'.format(self.reqid))

        # res not updated to reflect
        res = self.client.post('/api/pool/start_flock/{0}'.format(self.reqid))

        # box-p started, has id
        assert 'id' in res.json['containers']['box-p']

        # box-1 not yet launched, no id
        assert 'id' not in res.json['containers']['box-1']

        res = self.client.post('/api/pool/stop_flock/{0}'.format(self.reqid))
        assert res.json == {'success': True}



