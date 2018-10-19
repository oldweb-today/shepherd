import docker
import fakeredis
import json
import os
import pytest
import time
import glob
from shepherd.shepherd import Shepherd


# ============================================================================
class TestShepherd(object):
    NETWORKS_NAME = 'test-shepherd.net:{0}'

    TEST_DIR = os.path.join(os.path.dirname(__file__), 'data')

    TEST_FLOCKS = os.path.join(TEST_DIR, 'test_flocks.yaml')

    @classmethod
    def setup_class(cls):
        cls.redis = fakeredis.FakeStrictRedis(db=2, decode_responses=True)
        cls.shepherd = Shepherd(cls.redis, cls.NETWORKS_NAME)
        cls.shepherd.load_flocks(cls.TEST_FLOCKS)

        cls.docker = docker.from_env()

        for filename in glob.glob(os.path.join(cls.TEST_DIR, 'Dockerfile.*')):
            path, dockerfile = os.path.split(filename)
            name = dockerfile.rsplit('.', 1)[1]
            cls.docker.images.build(path=path,
                                    dockerfile=dockerfile,
                                    tag='test-shepherd/' + name,
                                    rm=True)

    @classmethod
    def teardown_class(cls):
        for image in cls.docker.images.list('test-shepherd/*'):
            cls.docker.images.remove(image.tags[0], force=True)

    def test_reqid(self):
        res = self.shepherd.request_flock('test_1', overrides={'base-alpine': 'test-shepherd/alpine-derived'},
                                                    environment={'FOO': 'BAR2'})
        reqid = res['reqid']
        TestShepherd.reqid = reqid
        assert reqid
        assert json.loads(self.redis.get('req:' + reqid))['flock'] == 'test_1'

    def test_is_ancestor(self):
        assert self.shepherd.is_ancestor_of('test-shepherd/busybox', 'busybox')

    def test_not_ancestor(self):
        assert self.shepherd.is_ancestor_of('test-shepherd/invalid', 'busybox') == False
        assert self.shepherd.is_ancestor_of('test-shepherd/invalid', 'busybox-invalid') == False

    def test_launch(self):
        flock = self.shepherd.start_flock(self.reqid)

        TestShepherd.flock = flock
        containers = flock['containers']

        # verify images
        assert self.docker.containers.get(containers['base-alpine']['id']).image.tags[0] == 'test-shepherd/alpine-derived:latest'
        assert self.docker.containers.get(containers['busybox']['id']).image.tags[0] == 'test-shepherd/busybox:latest'
        assert self.docker.containers.get(containers['another-box']['id']).image.tags[0] == 'test-shepherd/busybox:latest'

        # verify env vars
        env = self.docker.containers.get(containers['another-box']['id']).attrs['Config']['Env']

        # default
        assert 'VAR=BAR' in env
        assert 'TEST=FOO' in env

        # overriden!
        assert 'FOO=BAR2' in env

        # verify ports on busybox set!
        assert set(containers['busybox']['ports'].keys()) == {'port_a', 'port_b'}
        for value in containers['busybox']['ports'].values():
            assert value > 0

        for name, info in containers.items():
            container = self.docker.containers.get(info['id'])
            assert container

            assert 'FOO=BAR2' in container.attrs['Config']['Env']
            # assert ip is set
            assert info['ip'] != ''

        # verify network
        assert self.docker.networks.get(flock['network'])

    def test_stop(self):
        time.sleep(0.5)
        res = self.shepherd.stop_flock(self.reqid)

        flock = TestShepherd.flock
        containers = flock['containers']

        for name, info in containers.items():
            with pytest.raises(docker.errors.NotFound):
                self.docker.containers.get(info['id'])

        with pytest.raises(docker.errors.NotFound):
            assert self.docker.networks.get(flock['network'])

        assert not self.redis.exists('req:' + self.reqid)


