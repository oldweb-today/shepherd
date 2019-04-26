from gevent.monkey import patch_all; patch_all()
import pytest
from utils import sleep_try
import re


# ============================================================================
@pytest.mark.usefixtures('client_class', 'docker_client')
class TestImages:
    def test_image_all(self):
        res = self.client.get('/api/images/test-images')
        res = res.json

        assert res['busybox'] == {
            'id': 'busybox',
            'name': 'busy',
            'caps.small': '1',
            'caps.test': '2',
            'caps': 'small, test',
            'data': 'Some Data',
            'some': 'Value',
        }

        assert res['exit0'] == {
            'id': 'exit0',
            'name': 'testing-exit0',
            'caps.small': '1',
            'caps.test': '2',
            'caps': 'small, test',
            'data': 'Other Data',
            'some': 'Value',
        }

        assert res['alpine'] == {
            'id': 'alpine',
            'name': 'alpine',
            'caps': 'test',
            'caps.test': '3'
        }

        assert res['alpine-derived'] == {
            'id': 'alpine-derived',
            'name': 'alpine-derived',
            'caps': 'test',
            'caps.test': '4'
        }


    def test_images_query(self):
        res = self.client.get('/api/images/test-images?caps.small=1')

        assert set(res.json.keys()) == set(['busybox', 'exit0'])


    def test_images_query_by_name(self):
        res = self.client.get('/api/images/test-images?id=alpine')

        assert set(res.json.keys()) == set(['alpine'])

        assert res.json['alpine']['extra'] == 'bigvalue'

    def test_image_api(self, docker_client, redis):
        res = self.client.get('/api/request/alpine-derived/1996/http://example.com/path?foo=bar')

        assert res.json['reqid']


    def test_view(self, docker_client, redis):
        res = self.client.get('/view/alpine-derived/1996/http://example.com/path?foo=bar')

        text = res.data.decode('utf-8')

        m = re.search(r'reqid is: ([\w\d]+)', text)
        assert m

        reqid = m.group(1)
        TestImages.reqid = reqid

        res = self.client.post('/api/flock/start/' + self.reqid,
                               json={'environ': {'NEW': 'VALUE'}})

        info = res.json['containers']['base-alpine']

        assert info['environ']['NEW'] == 'VALUE'
        assert info['environ']['URL'] == 'http://example.com/path?foo=bar'
        assert info['environ']['TIMESTAMP'] == '1996'
        assert info['environ']['VNC_PASS']

        container = docker_client.containers.get(info['id'])

        assert container.labels['testlabel.name'] == 'alpine-derived'
        assert container.labels['testlabel.caps.test'] == '4'

        params = redis.hgetall('up:{0}'.format(info['ip']))
        assert params == {'reqid': self.reqid,
                          'TIMESTAMP': '1996',
                          'URL': 'http://example.com/path?foo=bar'}

    def test_attach(self):
        res = self.client.get('/attach/' + self.reqid)

        text = res.data.decode('utf-8')

        m = re.search(r'reqid is: ([\w\d]+)', text)
        assert m

        assert self.reqid == m.group(1)

    def test_remove(self):
        res = self.client.post('/api/flock/remove/' + self.reqid)
        assert res.json['success'] == True

    def test_view_error(self):
        res = self.client.get('/view/no-such-image/http://example.com/path?foo=bar')

        text = res.data.decode('utf-8')

        assert 'The image <b>no-such-image</b> is not a valid image.' in text

    def test_attach_error(self):
        res = self.client.get('/attach/' + self.reqid)

        text = res.data.decode('utf-8')

        assert 'Not a valid image request.' in text

