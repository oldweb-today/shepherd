import docker.errors
import fakeredis
import json
import os
import pytest
import time
import glob
from shepherd.shepherd import Shepherd


# ============================================================================
@pytest.mark.usefixtures('docker_client', 'shepherd', 'redis')
class TestShepherd(object):
    USER_PARAMS = {'data': 'val',
                   'another': '1'}

    def test_reqid(self, shepherd, redis):
        req_opts = dict(overrides={'base-alpine': 'test-shepherd/alpine-derived'},
                        environment={'FOO': 'BAR2'},
                        user_params=self.USER_PARAMS)

        res = shepherd.request_flock('test_1', req_opts)

        reqid = res['reqid']
        TestShepherd.reqid = reqid
        assert reqid
        assert json.loads(redis.get('req:' + reqid))['flock'] == 'test_1'

    def test_is_ancestor(self, shepherd):
        assert shepherd.is_ancestor_of('test-shepherd/busybox', 'busybox')

    def test_not_ancestor(self, shepherd):
        assert shepherd.is_ancestor_of('test-shepherd/invalid', 'busybox') == False
        assert shepherd.is_ancestor_of('test-shepherd/invalid', 'busybox-invalid') == False

    def test_launch(self, shepherd, docker_client):
        flock = shepherd.start_flock(self.reqid)

        TestShepherd.flock = flock
        containers = flock['containers']

        # verify images
        assert docker_client.containers.get(containers['base-alpine']['id']).image.tags[0] == 'test-shepherd/alpine-derived:latest'
        assert docker_client.containers.get(containers['busybox']['id']).image.tags[0] == 'test-shepherd/busybox:latest'
        assert docker_client.containers.get(containers['another-box']['id']).image.tags[0] == 'test-shepherd/busybox:latest'

    def test_verify_launch(self, docker_client, redis):
        flock = TestShepherd.flock
        containers = flock['containers']

        # verify env vars
        env = docker_client.containers.get(containers['another-box']['id']).attrs['Config']['Env']

        # default
        assert 'VAR=BAR' in env
        assert 'TEST=FOO' in env

        # overriden!
        assert 'FOO=BAR2' in env

        # verify ports on busybox set!
        assert set(containers['busybox']['ports'].keys()) == {'port_a', 'port_b'}
        for value in containers['busybox']['ports'].values():
            assert value > 0

        # check all
        for name, info in containers.items():
            container = docker_client.containers.get(info['id'])
            assert container

            assert 'FOO=BAR2' in container.attrs['Config']['Env']

            # assert ip is set
            assert info['ip'] != ''

            # user params only set for 'base-alpine'
            user_params_key = Shepherd.USER_PARAMS_KEY.format(info['ip'])

            if name == 'base-alpine':
                assert redis.hgetall(user_params_key) == self.USER_PARAMS

            else:
                assert not redis.exists(user_params_key)

        # verify network
        assert docker_client.networks.get(flock['network'])

    def test_stop(self, docker_client, shepherd, redis):
        time.sleep(0.5)
        res = shepherd.stop_flock(self.reqid)

        flock = TestShepherd.flock
        containers = flock['containers']

        for name, info in containers.items():
            with pytest.raises(docker.errors.NotFound):
                docker_client.containers.get(info['id'])

        with pytest.raises(docker.errors.NotFound):
            assert docker_client.networks.get(flock['network'])

        assert not redis.exists('req:' + self.reqid)

        assert redis.keys(Shepherd.USER_PARAMS_KEY.format('*')) == []


