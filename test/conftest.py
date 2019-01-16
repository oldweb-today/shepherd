from shepherd.pool import LaunchAllPool, FixedSizePool, PersistentPool
from shepherd.shepherd import Shepherd
from shepherd.wsgi import create_app

import pytest
import fakeredis
import os
import docker
import glob
import gevent.lock


NETWORKS_NAME = 'test-shepherd.net:{0}'

TEST_DIR = os.path.join(os.path.dirname(__file__), 'data')

TEST_FLOCKS = os.path.join(TEST_DIR, 'test_flocks.yaml')

TEST_REQID_LABEL = 'owt.test.shepherd'

TEST_NETWORK_LABEL = 'owt.test.network'


# ============================================================================
class DebugMixin(object):
    def __init__(self, *args, **kwargs):
        super(DebugMixin, self).__init__(*args, **kwargs)
        self.start_events = []
        self.stop_events = []
        self._lock = gevent.lock.Semaphore()

        self.reqid_starts = {}
        self.reqid_stops = {}

    def handle_die_event(self, reqid, event, attrs):
        self.stop_events.append(event)

        try:
            reqid = attrs[TEST_REQID_LABEL]
            with self._lock:
                self.reqid_stops[reqid] = self.reqid_stops.get(reqid, 0) + 1
        except:
            pass

        super(DebugMixin, self).handle_die_event(reqid, event, attrs)

    def handle_start_event(self, reqid, event, attrs):
        self.start_events.append(event)

        try:
            reqid = attrs[TEST_REQID_LABEL]
            with self._lock:
                self.reqid_starts[reqid] = self.reqid_starts.get(reqid, 0) + 1
        except:
            pass

        super(DebugMixin, self).handle_start_event(reqid, event, attrs)

class DebugLaunchAllPool(DebugMixin, LaunchAllPool):
    pass


class DebugPersistentPool(DebugMixin, PersistentPool):
    pass


# ============================================================================
@pytest.fixture(scope='module')
def redis():
    return fakeredis.FakeStrictRedis(db=2, decode_responses=True)


@pytest.fixture(scope='module')
def shepherd(redis):
    shep = Shepherd(redis,
                    reqid_label=TEST_REQID_LABEL,
                    network_templ=NETWORKS_NAME,
                    network_label=TEST_NETWORK_LABEL,
                    untracked_check_time=0)

    shep.load_flocks(TEST_FLOCKS)
    return shep


@pytest.fixture(scope='module')
def pool(redis, shepherd):
    pool = DebugLaunchAllPool('test-pool', shepherd, redis, duration=1.2, expire_check=0.3)

    yield pool

    pool.shutdown()


@pytest.fixture(scope='module')
def fixed_pool(redis, shepherd):
    pool = FixedSizePool('fixed-pool', shepherd, redis,
                         duration=60.0,
                         max_size=3,
                         expire_check=0.3,
                         number_ttl=25.0)

    yield pool

    pool.shutdown()


@pytest.fixture(scope='module', params=['remove-on-pause', 'stop-on-pause'])
def persist_pool(request, redis, shepherd):
    stop_on_pause = (request.param=='stop-on-pause')
    pool = DebugPersistentPool('persist-pool', shepherd, redis,
                       duration=2.0,
                       max_size=3,
                       expire_check=0.3,
                       grace_time=1,
                       stop_on_pause=stop_on_pause,
                       network_pool_size=2)

    yield pool

    pool.shutdown()




@pytest.fixture(scope='module')
def app(shepherd, pool):
    wsgi_app = create_app(shepherd, pool)
    return wsgi_app



@pytest.fixture(scope='session')
def docker_client():
    docker_cli = docker.from_env()

    for filename in sorted(glob.glob(os.path.join(TEST_DIR, 'Dockerfile.*'))):
        path, dockerfile = os.path.split(filename)
        name = dockerfile.rsplit('.', 1)[1]
        docker_cli.images.build(path=path,
                                dockerfile=dockerfile,
                                tag='test-shepherd/' + name,
                                rm=True)

    yield docker_cli

    for image in docker_cli.images.list('test-shepherd/*'):
        docker_cli.images.remove(image.tags[0], force=True)


@pytest.fixture(scope='module')
def external_net(docker_client):
    with pytest.raises(docker.errors.NotFound):
        assert docker_client.networks.get('test-shepherd-external-net')

    net = docker_client.networks.create('test-shepherd-external-net')

    try:
        yield net

    finally:
        net.remove()

    with pytest.raises(docker.errors.NotFound):
        assert docker_client.networks.get('test-shepherd-external-net')




