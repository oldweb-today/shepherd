from gevent.monkey import patch_all; patch_all()

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
                        environ={'FOO': 'BAR2'},
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

    def test_start(self, shepherd, docker_client):
        env = {'ANOTHER': 'VALUE'}
        flock = shepherd.start_flock(self.reqid, environ=env)

        TestShepherd.flock = flock
        containers = flock['containers']

        # verify images
        assert docker_client.containers.get(containers['base-alpine']['id']).image.tags[0] == 'test-shepherd/alpine-derived:latest'
        assert docker_client.containers.get(containers['busybox']['id']).image.tags[0] == 'test-shepherd/busybox:latest'
        assert docker_client.containers.get(containers['another-box']['id']).image.tags[0] == 'test-shepherd/busybox:latest'

    def test_already_launched(self, shepherd):
        # duplicate call is the same
        flock2 = shepherd.start_flock(self.reqid)
        assert flock2 == TestShepherd.flock

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

        # added at start
        assert 'ANOTHER=VALUE' in env

        # verify ports on busybox set!
        assert set(containers['busybox']['ports'].keys()) == {'port_a', 'port_b'}
        for value in containers['busybox']['ports'].values():
            assert value > 0

        # check all
        for name, info in containers.items():
            container = docker_client.containers.get(info['id'])
            assert container

            assert 'FOO=BAR2' in container.attrs['Config']['Env']

            # assert labels
            assert container.labels[Shepherd.SHEP_REQID_LABEL] == self.reqid

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

        assert shepherd.is_valid_flock(self.reqid)

        res = shepherd.stop_flock(self.reqid)

        assert not shepherd.is_valid_flock(self.reqid)

        assert res == {'success': True}

        flock = TestShepherd.flock
        containers = flock['containers']

        for name, info in containers.items():
            with pytest.raises(docker.errors.NotFound):
                docker_client.containers.get(info['id'])

        with pytest.raises(docker.errors.NotFound):
            assert docker_client.networks.get(flock['network'])

        assert not redis.exists('req:' + self.reqid)

        assert redis.keys(Shepherd.USER_PARAMS_KEY.format('*')) == []

    def test_start_with_external_link(self, docker_client, shepherd):
        res = shepherd.request_flock('test_external')

        reqid = res['reqid']

        res = shepherd.start_flock(reqid)

        assert res['error'] == 'start_error'

        ext = None

        try:
            ext = docker_client.containers.run('test-shepherd/busybox',
                                               name='test_external_container_1',
                                               detach=True,
                                               auto_remove=True)

            res = shepherd.start_flock(reqid)

            assert res['error'] == 'invalid_reqid'

            # new reqid needed
            res = shepherd.request_flock('test_external')
            reqid = res['reqid']

            res = shepherd.start_flock(reqid)

            assert res['containers']

            ext.reload()

            networks = ext.attrs['NetworkSettings']['Networks']
            assert res['network'] in networks

            assert 'external' in networks[res['network']]['Aliases']

        finally:
            try:
                shepherd.stop_flock(reqid)
            except:
                pass

            if ext:
                ext.kill()


        with pytest.raises(docker.errors.NotFound):
            assert docker_client.networks.get(res['network'])


    def test_start_with_external_net(self, docker_client, shepherd):
        # if this fails, network already exists!
        # need to clean up manually
        with pytest.raises(docker.errors.NotFound):
            assert docker_client.networks.get('test-shepherd-external-net')


        res = shepherd.request_flock('test_external_net')

        reqid = res['reqid']

        res = shepherd.start_flock(reqid)

        assert res['error'] == 'start_error'

        net = None

        try:
            net = docker_client.networks.create('test-shepherd-external-net')

            res = shepherd.start_flock(reqid)

            assert res['error'] == 'invalid_reqid'

            # new reqid needed
            res = shepherd.request_flock('test_external_net')
            reqid = res['reqid']

            res = shepherd.start_flock(reqid)

            assert res['containers']['container-1']
            assert res['containers']['container-2']
            container_1 = docker_client.containers.get(res['containers']['container-1']['id'])
            container_2 = docker_client.containers.get(res['containers']['container-2']['id'])

            # ensure external network only in container-2
            assert 'test-shepherd-external-net' not in container_1.attrs['NetworkSettings']['Networks']
            assert 'test-shepherd-external-net' in container_2.attrs['NetworkSettings']['Networks']

            net.reload()
            assert len(net.containers) == 1
            assert net.containers[0] == container_2

        finally:
            try:
                shepherd.stop_flock(reqid)
            except:
                pass


        try:
            net.reload()
            assert net.containers == []

        finally:
            net.remove()

        with pytest.raises(docker.errors.NotFound):
            assert docker_client.networks.get('test-shepherd-external-net')

    def test_pause_resume(self, shepherd, docker_client):
        res = shepherd.request_flock('test_b')

        reqid = res['reqid']

        assert shepherd.is_valid_flock(reqid, 'new')

        response = shepherd.start_flock(reqid, pausable=True)

        for container in response['containers'].values():
            assert docker_client.containers.get(container['id']).status == 'running'

        res = shepherd.pause_flock(reqid, grace_time=1)

        time.sleep(1.5)

        assert shepherd.is_valid_flock(reqid, 'paused')

        for container in response['containers'].values():
            assert docker_client.containers.get(container['id']).status == 'exited'

        res = shepherd.resume_flock(reqid)

        assert shepherd.is_valid_flock(reqid, 'running')

        for container in response['containers'].values():
            assert docker_client.containers.get(container['id']).status == 'running'

        res = shepherd.stop_flock(reqid, keep_reqid=True)

        # reqid not removed yet, set to 'stopped'
        assert shepherd.is_valid_flock(reqid, 'stopped')

        # containers removed
        for container in response['containers'].values():
            with pytest.raises(docker.errors.NotFound):
                docker_client.containers.get(container['id'])

        res = shepherd.stop_flock(reqid)

        # reqid removed
        assert not shepherd.is_valid_flock(reqid, 'stopped')
        assert not shepherd.is_valid_flock(reqid)

