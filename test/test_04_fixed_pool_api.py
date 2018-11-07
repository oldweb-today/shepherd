from gevent.monkey import patch_all; patch_all()
import pytest
import time
import itertools

from shepherd.wsgi import create_app


@pytest.fixture(scope='module')
def app(shepherd, fixed_pool):
    wsgi_app = create_app(shepherd, fixed_pool)
    return wsgi_app


@pytest.mark.usefixtures('client_class', 'docker_client')
class TestFixedPoolApi:
    ids = []
    pending = []

    @classmethod
    def sleep_try(cls, sleep_interval, max_time, test_func):
        max_count = float(max_time) / sleep_interval
        for counter in itertools.count():
            try:
                time.sleep(sleep_interval)
                test_func()
                return
            except:
                if counter >= max_count:
                    raise

    def remove_next(self, docker_client):
        cid = self.ids.pop()
        docker_client.containers.get(cid).kill()

    def start(self, reqid):
        res = self.client.post('/api/start_flock/' + reqid)
        data = res.json or {}
        return data

    def do_req(self, params):
        res = self.client.post('/api/request_flock/test_b', json=params)
        return res.json

    def queue_req(self):
        res, reqid = self.do_req_and_start()
        assert reqid
        TestFixedPoolApi.pending.append(reqid)
        return res, reqid

    def do_req_and_start(self, **params):
        res = self.do_req(params)
        if 'error' in res:
            return res

        reqid = res['reqid']
        res = self.client.post('/api/start_flock/' + reqid)
        data = res.json or {}
        return data, reqid

    def test_3_requests(self, redis):
        for x in range(1, 4):
            res, reqid = self.do_req_and_start()
            assert res['containers']['box']
            TestFixedPoolApi.ids.append(res['containers']['box']['id'])
            assert redis.scard('p:fixed-pool:f') == x

            # duplicate request get same response
            new_res = self.client.post('/api/start_flock/' + reqid)
            assert res == new_res.json

            #assert redis.get('p:fixed-pool:n2r:{0}'.format(x)) == reqid
            #assert redis.get('p:fixed-pool:r2n:{0}'.format(reqid)) == str(x)

    def test_pool_full_request(self, redis):
        for x in range(0, 10):
            res, reqid = self.queue_req()
            assert res['queued'] == x

    def test_expire_queue_next_in_order(self, redis, docker_client):
        self.remove_next(docker_client)

        def assert_done():
            assert redis.scard('p:fixed-pool:f') == 2

        self.sleep_try(0.2, 3.0, assert_done)

        res = self.client.post('/api/start_flock/' + self.pending[1])
        assert res.json['queued'] == 1

        res = self.client.post('/api/start_flock/' + self.pending[0])
        assert res.json['containers']['box']
        self.ids.append(res.json['containers']['box']['id'])

        res = self.client.post('/api/start_flock/' + self.pending[1])
        assert res.json['queued'] == 0

    def test_expire_queue_next_out_of_order(self, redis, docker_client):
        self.remove_next(docker_client)
        self.remove_next(docker_client)

        def assert_done():
            assert redis.scard('p:fixed-pool:f') == 1

        self.sleep_try(0.2, 3.0, assert_done)

        res = self.start(self.pending[4])
        assert res['queued'] == 3

        res = self.start(self.pending[2])
        assert res['containers']

        res = self.start(self.pending[4])
        assert res['queued'] == 3

        res = self.start(self.pending[1])
        assert res['containers']

        res = self.start(self.pending[4])
        assert res['queued'] == 1

        res = self.start(self.pending[3])
        assert res['queued'] == 0

    def test_expire_unused(self, redis, fixed_pool):
        res = self.start(self.pending[6])
        assert res['queued'] == 3

        res, reqid = self.queue_req()
        assert res['queued'] == 7

        # simulate expiry
        fixed_pool.remove_request(self.pending[3])
        fixed_pool.remove_request(self.pending[4])
        fixed_pool.remove_request(self.pending[5])
        fixed_pool.remove_request(self.pending[6])

        res = self.start(reqid)
        assert res['queued'] == 3

        res = self.start(self.pending[7])
        assert res['queued'] == 0

        res = self.start(self.pending[6])
        assert res['queued'] == 4

        res = self.start(self.pending[3])
        assert res['queued'] == 5

