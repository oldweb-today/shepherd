from gevent.monkey import patch_all; patch_all()
import pytest
import time
import docker
from utils import sleep_try


@pytest.fixture(scope='module', params=['persist-pool'])
def persist_pool(request, app):
    return app.pools[request.param]


@pytest.mark.usefixtures('client_class', 'docker_client')
class TestPersistPoolApi:
    reqids = []

    def start(self, reqid):
        res = self.client.post('/api/flock/start/' + reqid)
        data = res.json or {}
        return data

    def stop(self, reqid):
        res = self.client.post('/api/flock/remove/' + reqid)
        data = res.json or {}
        return data

    def do_req(self, persist_pool, params):
        res = self.client.post('/api/flock/request/test_b?pool=' + persist_pool.name, json=params)
        return res.json

    def do_req_and_start(self, persist_pool, **params):
        res = self.do_req(persist_pool, params)
        if 'error' in res:
            return res, None

        reqid = res['reqid']
        res = self.client.post('/api/flock/start/' + reqid)
        data = res.json or {}
        TestPersistPoolApi.reqids.append(reqid)
        return data, reqid

    def test_dont_reque_on_clean_exit(self, redis, persist_pool, docker_client):
        # if a clean exit (exit code, 0)
        res, reqid = self.do_req_and_start(persist_pool, overrides={'box': 'test-shepherd/exit0'})
        assert res['containers']['box']
        assert redis.scard('p:{0}:f'.format(persist_pool.name)) == 1

        new_res = self.client.post('/api/flock/start/' + reqid)

        def assert_done():
            # not running
            assert redis.scard('p:{0}:f'.format(persist_pool.name)) == 0

            # not queued for restart
            assert redis.scard('p:{0}:ws'.format(persist_pool.name)) == 0

            assert len(persist_pool.start_events) == 2
            assert len(persist_pool.stop_events) == 2

            assert persist_pool.reqid_starts[reqid] == 2
            assert persist_pool.reqid_stops[reqid] == 2

        sleep_try(0.2, 20.0, assert_done)

        containers = res['containers']
        for container in containers.values():
            assert docker_client.containers.get(container['id']).status == 'exited'

        rem_res = self.client.post('/api/flock/remove/' + reqid)

        assert rem_res.json.get('success')

        for container in containers.values():
            with pytest.raises(docker.errors.NotFound):
                docker_client.containers.get(container['id'])

        persist_pool.start_events.clear()
        persist_pool.stop_events.clear()

        persist_pool.reqid_starts.clear()
        persist_pool.reqid_stops.clear()

    def test_full_continue_running(self, redis, persist_pool):
        for x in range(1, 4):
            res, reqid = self.do_req_and_start(persist_pool)
            assert res['containers']['box']
            assert redis.scard('p:{0}:f'.format(persist_pool.name)) == x

            # duplicate request get same response
            new_res = self.client.post('/api/flock/start/' + reqid)
            assert res == new_res.json

        def assert_done():
            assert len(persist_pool.start_events) == 6
            assert len(persist_pool.stop_events) == 0

            assert redis.llen('p:{0}:wq'.format(persist_pool.name)) == 0
            assert redis.scard('p:{0}:f'.format(persist_pool.name)) == 3

        sleep_try(0.2, 5.0, assert_done)

    def test_full_queue_additional(self, redis, persist_pool):
        assert len(persist_pool.start_events) == 6

        for x in range(1, 4):
            res, reqid = self.do_req_and_start(persist_pool)
            assert res['queue'] == x - 1
            assert redis.scard('p:{0}:f'.format(persist_pool.name)) == 3

            assert redis.llen('p:{0}:wq'.format(persist_pool.name)) == x
            assert redis.scard('p:{0}:ws'.format(persist_pool.name)) == x

            # ensure double start doesn't move position
            res = self.client.post('/api/flock/start/' + reqid)
            assert res.json['queue'] == x - 1

        for x in range(1, 10):
            time.sleep(2.1)

            llen = redis.llen('p:{0}:wq'.format(persist_pool.name))
            scard = redis.scard('p:{0}:ws'.format(persist_pool.name))
            assert llen in (2, 3)
            assert scard in (2, 3)

        def assert_done():
            assert len(persist_pool.reqid_starts) >= 6
            assert len(persist_pool.reqid_stops) >= 6

            assert all(value >= 2 for value in persist_pool.reqid_starts.values())
            assert all(value >= 2 for value in persist_pool.reqid_stops.values())

            assert len(persist_pool.start_events) >= 14
            assert len(persist_pool.stop_events) >= 10


        sleep_try(0.2, 20.0, assert_done)

    def test_stop_one_run_next(self, redis, persist_pool):
        reqid = redis.srandmember('p:{0}:f'.format(persist_pool.name))

        num_started = len(persist_pool.start_events)
        num_stopped = len(persist_pool.stop_events)

        self.stop(reqid)

        def assert_done():
            assert len(persist_pool.stop_events) >= num_stopped + 2
            assert len(persist_pool.start_events) >= num_started + 2

        sleep_try(0.2, 5.0, assert_done)

    def test_remove_all(self, redis, persist_pool):
        while len(self.reqids) > 0:
            remove = self.reqids.pop()
            self.stop(remove)
            #time.sleep(0.2)

        def assert_done():
            assert redis.scard('p:{0}:f'.format(persist_pool.name)) == 0

            assert redis.llen('p:{0}:wq'.format(persist_pool.name)) == 0
            assert redis.scard('p:{0}:ws'.format(persist_pool.name)) == 0
            assert redis.scard('p:{0}:a'.format(persist_pool.name)) == 0

            assert persist_pool.reqid_starts == persist_pool.reqid_stops

        sleep_try(0.2, 30.0, assert_done)

