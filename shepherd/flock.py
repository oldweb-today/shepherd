import os
import base64
import json


# ===========================================================================
class FlockRequest(object):
    REQ_KEY = 'req:{0}'

    def __init__(self, reqid=None):
        if not reqid:
            reqid = self._make_reqid()
        self.reqid = reqid
        self.key = self.REQ_KEY.format(self.reqid)
        self.data = None

    def _make_reqid(self):
        return base64.b32encode(os.urandom(15)).decode('utf-8')

    def init_new(self, flock_name, req_opts):
        self.data = {'id': self.reqid,
                     'flock': flock_name,
                     'state': 'new',
                    }

        self._copy_if_set('overrides', req_opts)
        self._copy_if_set('environ', req_opts, default=dict())
        self._copy_if_set('user_params', req_opts, default=dict())
        self._copy_if_set('deferred', req_opts)
        return self

    def _copy_if_set(self, param, src, default=None):
        res = src.get(param, default)
        if res is not None:
            self.data[param] = res

    def update_env(self, environ, redis, save=False, expire=None):
        if not environ:
            return

        if self.data is None:
            self.load(redis)

        self.data['environ'].update(environ)

        if save:
            self.save(redis, expire=expire)

    def get_overrides(self):
        return self.data.get('overrides') or {}

    def get_state(self):
        return self.data and self.data.get('state', 'new')

    def set_state(self, state, redis):
        self.data['state'] = state
        self.save(redis)

    def set_network(self, network_name):
        self.data['net'] = network_name

    def get_network(self):
        return self.data.get('net')

    def load(self, redis):
        data = redis.get(self.key)
        self.data = json.loads(data) if data else {}
        return self.data != {}

    def save(self, redis, expire=None):
        redis.set(self.key, json.dumps(self.data), ex=expire)
        if expire is None:
            redis.persist(self.key)

    def load_cached_response(self, redis, required=False):
        if not self.load(redis):
            return {'error': 'invalid_reqid'}

        response = self.get_cached_response()
        if response:
            return response

        if required:
            return {'error': 'not_running'}

        return None

    def get_cached_response(self):
        return self.data.get('resp')

    def cache_response(self, resp, redis):
        self.data['state'] = 'running'
        self.data['resp'] = resp
        self.save(redis)

    def stop(self, redis):
        self.data.pop('resp', '')
        self.data['state'] = 'stopped'
        self.save(redis)

    def delete(self, redis):
        redis.delete(self.key)



