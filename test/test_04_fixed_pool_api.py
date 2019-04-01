from gevent.monkey import patch_all; patch_all()
import pytest

from shepherd.wsgi import create_app
from utils import sleep_try


@pytest.mark.usefixtures('client_class', 'docker_client')
class TestFixedPoolApi:
    ids = []
    pending = []

    def remove_next(self, docker_client):
        cid = self.ids.pop()
        try:
            docker_client.containers.get(cid).kill()
        except:
            pass

    def start(self, reqid):
        res = self.client.post('/api/flock/start/' + reqid)
        data = res.json or {}
        return data

    def do_req(self, params):
        res = self.client.post('/api/flock/request/test_b?pool=fixed-pool', json=params)
        return res.json

    def queue_req(self):
        res, reqid = self.do_req_and_start()
        assert reqid
        TestFixedPoolApi.pending.append(reqid)
        return res, reqid

    def do_req_and_start(self, **params):
        res = self.do_req(params)
        if 'error' in res:
            return res, None

        reqid = res['reqid']
        res = self.client.post('/api/flock/start/' + reqid)
        data = res.json or {}
        return data, reqid

    def delete_reqid(self, redis, reqid):
        redis.delete('p:fixed-pool:r:' + reqid)

    def test_launch_3_requests_no_queue(self, redis):
        for x in range(1, 4):
            res, reqid = self.do_req_and_start()
            assert res['containers']['box']
            TestFixedPoolApi.ids.append(res['containers']['box']['id'])
            assert redis.scard('p:fixed-pool:f') == x

            # duplicate request get same response
            new_res = self.client.post('/api/flock/start/' + reqid)
            assert res == new_res.json

    def test_pool_full_queue_requests(self, redis):
        for x in range(0, 10):
            res, reqid = self.queue_req()
            assert res['queue'] == x

    def test_expire_queue_next_in_order(self, redis, docker_client):
        self.remove_next(docker_client)

        def assert_done():
            assert redis.scard('p:fixed-pool:f') == 2

        sleep_try(0.2, 6.0, assert_done)

        res = self.client.post('/api/flock/start/' + self.pending[1])
        assert res.json['queue'] == 1

        res = self.client.post('/api/flock/start/' + self.pending[0])
        assert res.json['containers']['box']
        self.ids.append(res.json['containers']['box']['id'])

        res = self.client.post('/api/flock/start/' + self.pending[1])
        assert res.json['queue'] == 0

        self.pending.pop(0)

    def test_expire_queue_next_out_of_order(self, redis, docker_client):
        res = self.start(self.pending[0])
        assert res['queue'] == 0

        res = self.start(self.pending[1])
        assert res['queue'] == 1

        res = self.start(self.pending[2])
        assert res['queue'] == 2

        self.remove_next(docker_client)
        self.remove_next(docker_client)

        def assert_done():
            assert redis.scard('p:fixed-pool:f') == 1

        sleep_try(0.2, 6.0, assert_done)

        res = self.start(self.pending[2])
        assert res['queue'] == 2

        res = self.start(self.pending[1])
        assert res['containers']

        res = self.start(self.pending[2])
        assert res['queue'] == 1

        res = self.start(self.pending[3])
        assert res['queue'] == 2

        res = self.start(self.pending[0])
        assert res['containers']

        res = self.start(self.pending[2])
        assert res['queue'] == 0

        res = self.start(self.pending[3])
        assert res['queue'] == 1

        self.pending.pop(0)
        self.pending.pop(0)

    def test_expire_unused(self, redis):
        def assert_done():
            assert redis.scard('p:fixed-pool:f') == 3

        sleep_try(0.2, 6.0, assert_done)

        assert redis.hget('p:fixed-pool:i', 'max_size') == '3'

        res = self.start(self.pending[3])
        assert res['queue'] == 3

        res, reqid = self.queue_req()
        assert res['queue'] == 7

        assert reqid == self.pending[7]

        # simulate delete
        self.delete_reqid(redis, self.pending[0])
        self.delete_reqid(redis, self.pending[1])
        self.delete_reqid(redis, self.pending[2])
        self.delete_reqid(redis, self.pending[4])

        # removed expired reqids
        res = self.start(self.pending[3])
        assert res['queue'] == 0

        res = self.start(self.pending[5])
        assert res['queue'] == 1

        res = self.start(self.pending[7])
        assert res['queue'] == 3

        # get new number
        res = self.start(self.pending[0])
        assert res['queue'] == 4


