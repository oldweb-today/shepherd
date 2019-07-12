from gevent.monkey import patch_all; patch_all()
import pytest

from shepherd.wsgi import create_app


@pytest.mark.usefixtures('client_class', 'docker_client')
class TestDeferred(object):
    def test_deferred_flock_start(self, redis):
        res = self.client.post('/api/flock/request/test_deferred?pool=test-pool')

        TestDeferred.reqid = res.json['reqid']

        res = self.client.post('/api/flock/start/{0}'.format(self.reqid))

        assert redis.exists('reqp:' + self.reqid)

        assert res.json['containers']
        assert 'deferred' in res.json['containers']['box-p']
        assert 'deferred' not in res.json['containers']['box-1']

    def test_deferred_start_container(self):
        res = self.client.post('/api/flock/start_deferred/{0}/box-p'.format(self.reqid))

        assert res.json['id']
        assert res.json['ip']
        assert res.json['ports']['port_a']

        # same result, already started
        res2 = self.client.post('/api/flock/start_deferred/{0}/box-p'.format(self.reqid))
        assert res.json == res2.json

    def test_deferred_err_not_deferred(self):
        res = self.client.post('/api/flock/start_deferred/{0}/box-1'.format(self.reqid))
        assert res.json == {'error': 'invalid_deferred', 'flock': 'test_deferred'}

    def test_deferred_flock_remove(self, redis):
        res = self.client.post('/api/flock/remove/{0}'.format(self.reqid))
        assert res.json == {'success': True}
        assert not redis.exists('reqp:' + self.reqid)

    def test_deferred_only(self):
        res = self.client.post('/api/flock/request/test_def_only?pool=test-pool')

        self.reqid = res.json['reqid']

        res = self.client.post('/api/flock/start/{0}'.format(self.reqid))

        for n, container in res.json['containers'].items():
            assert container['deferred']
            assert set(container.keys()) == {'deferred', 'image'}

        res = self.client.post('/api/flock/start_deferred/{0}/box-p'.format(self.reqid))

        # res not updated to reflect
        res = self.client.post('/api/flock/start/{0}'.format(self.reqid))

        # box-p started, has id
        assert 'id' in res.json['containers']['box-p']

        # box-1 not yet launched, no id
        assert 'id' not in res.json['containers']['box-1']

        res = self.client.post('/api/flock/remove/{0}'.format(self.reqid))
        assert res.json == {'success': True}

    def test_deferred_override(self):
        # switch which container is deferred
        json = {'deferred': {'box-p': False, 'box-1': True}}

        res = self.client.post('/api/flock/request/test_deferred?pool=test-pool', json=json)

        reqid = res.json['reqid']

        res = self.client.post('/api/flock/start/{0}'.format(reqid))

        assert res.json['containers']
        assert 'deferred' in res.json['containers']['box-1']
        assert 'deferred' not in res.json['containers']['box-p']

        res = self.client.post('/api/flock/stop/{0}'.format(reqid))
        assert res.json == {'success': True}

