from gevent.monkey import patch_all; patch_all()
import pytest
from utils import sleep_try
from shepherd.pool import LaunchAllPool
from shepherd.wsgi import create_app
from shepherd.kubeshepherd import KubeShepherd
import time
import os


TEST_REQID_LABEL = 'owt.test.shepherd'

TEST_DIR = os.path.join(os.path.dirname(__file__), 'data')

TEST_FLOCKS = os.path.join(TEST_DIR, 'test_flocks.yaml')


@pytest.fixture(scope='module')
def shepherd(redis):
    shep = KubeShepherd(redis,
                        reqid_label=TEST_REQID_LABEL,
                        untracked_check_time=0,
                        job_duration=30.0)

    shep.load_flocks(TEST_FLOCKS)
    return shep

@pytest.fixture(scope='module')
def app(shepherd, pool):
    wsgi_app = create_app(shepherd, pool)
    return wsgi_app

@pytest.fixture(scope='module')
def pool(redis, shepherd):
    pool = LaunchAllPool('test-pool', shepherd, redis, duration=30.0, expire_check=0.3)

    yield pool

    pool.shutdown()



# ============================================================================
@pytest.mark.usefixtures('client_class', 'docker_client')
class TestKubeApi:
    def test_request_flock(self):
        res = self.client.post('/api/request_flock/test_b_kube', json={'user_params': {'a': 'b'},
                                                                       'environ': {'FOO': 'BAR'}})
        assert res.json['reqid']
        TestKubeApi.reqid = res.json['reqid']

    def test_start_flock(self, shepherd, redis):
        res = self.client.post('/api/start_flock/' + self.reqid,
                               json={'environ': {'NEW': 'VALUE'}})

        assert res.json['containers']['box']
        assert res.json['containers']['box']['environ']['NEW'] == 'VALUE'
        assert not res.json['network']

        def assert_done():
            res = shepherd.batch_api.list_namespaced_job(namespace='default',
                   label_selector=shepherd.reqid_label + '=' + self.reqid)

            assert len(res.items) == 1
            assert res.items[0].status.active

            res = shepherd.core_api.list_namespaced_pod(namespace='default',
                   label_selector=shepherd.reqid_label + '=' + self.reqid)

            assert len(res.items) == 1
            assert res.items[0].status.phase == 'Running'

            res = shepherd.core_api.list_namespaced_service(namespace='default',
                   label_selector=shepherd.reqid_label + '=' + self.reqid)

            assert len(res.items) == 1
            assert res.items[0].status

        sleep_try(0.2, 6.0, assert_done)

        assert redis.exists('p:test-pool:rq:' + self.reqid)
        assert redis.scard('p:test-pool:f') == 1

    def test_start_flock_again(self):
        res = self.client.post('/api/start_flock/' + self.reqid,
                               json={'environ': {'NEW': 'VALUE'}})

        assert res.json['containers']['box']
        assert res.json['containers']['box']['environ']['NEW'] == 'VALUE'
        assert not res.json['network']

    def test_get_flock(self, pool, redis):
        res = self.client.get('/api/flock/' + self.reqid)
        assert res.json['user_params'] == {'a': 'b'}
        assert res.json['environ']
        assert res.json['image_list']
        assert res.json['id']

    def test_stop_flock(self, shepherd, redis):
        time.sleep(10.0)

        res = self.client.post('/api/stop_flock/' + self.reqid)
        assert res.json['success'] == True

        res = shepherd.batch_api.list_namespaced_job(namespace='default',
               label_selector=shepherd.reqid_label + '=' + self.reqid)

        assert len(res.items) == 1
        assert not res.items[0].status.active

        assert not redis.exists('p:test-pool:rq:' + self.reqid)
        assert redis.scard('p:test-pool:f') == 0

    def test_verify_objects_removed(self, shepherd):
        def assert_done():
            res = shepherd.batch_api.list_namespaced_job(namespace='default',
                   label_selector=shepherd.reqid_label + '=' + self.reqid)

            assert len(res.items) == 0

            res = shepherd.core_api.list_namespaced_pod(namespace='default',
                   label_selector=shepherd.reqid_label + '=' + self.reqid)

            assert len(res.items) == 0

            res = shepherd.core_api.list_namespaced_service(namespace='default',
                   label_selector=shepherd.reqid_label + '=' + self.reqid)

            assert len(res.items) == 0

        sleep_try(0.2, 60.0, assert_done)


