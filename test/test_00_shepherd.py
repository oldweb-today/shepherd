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

    def test_flock_setup(self, shepherd):
        assert len(shepherd.flocks) == 6

    def test_flock_dir_load(self, redis):
        testshep = Shepherd(redis)

        test_dir = os.path.join(os.path.dirname(__file__), 'data', 'flocks')

        os.environ['EXTERNAL_NET'] = 'NET'
        os.environ['BAR_PATH'] = 'B1'

        testshep.load_flocks(test_dir)

        assert len(testshep.flocks) == 3

        # not interpolated
        assert testshep.flocks['test_1']['containers'][2]['environment']['TEST'] == '${FOO}'

        # vars interpolated
        assert testshep.flocks['test_2']['containers'][1]['external_network'] == 'NET'
        assert testshep.flocks['test_3']['volumes']['bar'] == 'B1'

        os.environ.pop('EXTERNAL_NET')
        os.environ.pop('BAR_PATH')

    def test_reqid(self, shepherd, redis):
        req_opts = dict(overrides={'base-alpine': 'test-shepherd/alpine-derived'},
                        environ={'FOO': 'BAR2', 'SOME': ''},
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

    def test_has_label(self, shepherd):
        assert shepherd.image_has_label('test-shepherd/busybox', 'test.isbusybox')
        assert shepherd.image_has_label('test-shepherd/busybox', 'test.isbusybox=1')

    def test_not_has_label(self, shepherd):
        assert shepherd.image_has_label('test-shepherd/invalid', 'test.isbusybox=2') == False
        assert shepherd.image_has_label('test-shepherd/busybox', 'test.islapine') == False

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

    def test_verify_launch(self, docker_client, redis, shepherd):
        flock = TestShepherd.flock
        containers = flock['containers']

        # verify env vars
        env = docker_client.containers.get(containers['another-box']['id']).attrs['Config']['Env']

        # default
        assert 'VAR=BAR' in env
        assert 'TEST=FOO' in env

        # overriden!
        assert 'FOO=BAR2' in env
        assert 'SOME=' in env

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
            assert container.labels[shepherd.reqid_label] == self.reqid

            # assert ip is set
            assert info['ip'] != ''

            # user params only set for 'base-alpine'
            user_params_key = Shepherd.USER_PARAMS_KEY.format(info['ip'])

            if name == 'base-alpine':
                params_with_reqid = self.USER_PARAMS.copy()
                params_with_reqid['reqid'] = self.reqid
                assert redis.hgetall(user_params_key) == params_with_reqid

            else:
                assert not redis.exists(user_params_key)

            if name == 'another-box':
                assert info['environ'] == {
                    'ANOTHER': 'VALUE',
                    'TEST': 'FOO',
                    'VAR': 'BAR',
                    'FOO': 'BAR2',
                    'SOME': '',
                }

            else:
                assert info['environ'] == {
                    'ANOTHER': 'VALUE',
                    'FOO': 'BAR2',
                    'SOME': '',
                }

        # verify network
        assert docker_client.networks.get(flock['network'])

    def test_stop(self, shepherd, docker_client):
        flock = TestShepherd.flock
        containers = flock['containers']

        for container in containers.values():
            assert docker_client.containers.get(container['id']).status == 'running'

        res = shepherd.stop_flock(self.reqid, grace_time=1)

        time.sleep(1.5)

        assert shepherd.is_valid_flock(self.reqid, 'stopped')

        for container in containers.values():
            assert docker_client.containers.get(container['id']).status == 'exited'

    def test_remove(self, docker_client, shepherd, redis):
        time.sleep(0.5)

        assert shepherd.is_valid_flock(self.reqid)

        res = shepherd.remove_flock(self.reqid)

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

    def test_volumes(self, shepherd, docker_client):
        res = shepherd.request_flock('test_vol')

        reqid = res['reqid']

        res = shepherd.start_flock(reqid)

        assert res['containers']['box-1']
        assert res['containers']['box-2']
        box_1 = docker_client.containers.get(res['containers']['box-1']['id'])
        box_2 = docker_client.containers.get(res['containers']['box-2']['id'])

        vol_1 = 'vol-tmp-' + reqid
        vol_2 = 'vol-bar-' + reqid

        mounts_1 = {m['Name']: m for m in box_1.attrs['Mounts']}
        mounts_2 = {m['Name']: m for m in box_2.attrs['Mounts']}

        assert mounts_1 == mounts_2

        assert docker_client.volumes.get(vol_1)
        assert docker_client.volumes.get(vol_2)

        res = shepherd.remove_flock(reqid)

        assert res == {'success': True}

        with pytest.raises(docker.errors.NotFound):
            assert docker_client.volumes.get(vol_1)

        with pytest.raises(docker.errors.NotFound):
            assert docker_client.volumes.get(vol_2)

    def test_no_external_net_error(self,docker_client, shepherd):
        res = shepherd.request_flock('test_external_net')

        reqid = res['reqid']

        res = shepherd.start_flock(reqid)

        assert res['error'] == 'start_error'

        TestShepherd.net_reqid = reqid

    def test_start_with_external_net(self, docker_client, shepherd, external_net):
        reqid = self.net_reqid
        try:
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
            assert len(container_1.attrs['NetworkSettings']['Networks']) == 1

            assert 'test-shepherd-external-net' in container_2.attrs['NetworkSettings']['Networks']
            assert len(container_2.attrs['NetworkSettings']['Networks']) == 2

            external_net.reload()
            assert len(external_net.containers) == 1
            assert external_net.containers[0] == container_2

        finally:
            try:
                shepherd.remove_flock(reqid)
            except:
                pass

        external_net.reload()
        assert external_net.containers == []

    def test_start_deferred_container(self, shepherd, docker_client):
        res = shepherd.request_flock('test_deferred')

        reqid = res['reqid']

        res = shepherd.start_flock(reqid)

        assert res['containers']['box-1']['id']
        assert res['containers']['box-p']['deferred']
        assert 'id' not in res['containers']['box-p']

        box_1 = docker_client.containers.get(res['containers']['box-1']['id'])
        assert box_1.status == 'running'

        # not a deferred container
        res = shepherd.start_deferred_container(reqid, 'box-1')
        assert res == {'error': 'invalid_deferred', 'flock': 'test_deferred'}

        res = shepherd.start_deferred_container(reqid, 'box-p')

        assert res['id']
        assert res['ip']
        assert res['ports']['port_a']

        box_p = docker_client.containers.get(res['id'])
        assert box_p.status == 'running'

        # start again, already started
        res2 = shepherd.start_deferred_container(reqid, 'box-p')

        assert res == res2

        res = shepherd.remove_flock(reqid)

        assert res['success'] == True

    def test_start_not_deferred_container(self, shepherd, docker_client):
        res = shepherd.request_flock('test_deferred', {'deferred': {'box-p': False}})

        reqid = res['reqid']

        res = shepherd.start_flock(reqid)

        assert res['containers']['box-1']['id']
        assert res['containers']['box-p']['id']

        box_1 = docker_client.containers.get(res['containers']['box-1']['id'])
        assert box_1.status == 'running'

        box_p = docker_client.containers.get(res['containers']['box-p']['id'])
        assert box_p.status == 'running'

        res = shepherd.remove_flock(reqid)

        assert res['success'] == True

