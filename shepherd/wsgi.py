from apispec import APISpec
#from apispec.ext.flask import FlaskPlugin
from apispec_webframeworks.flask import FlaskPlugin
from apispec.ext.marshmallow import MarshmallowPlugin

import marshmallow
import json
import yaml
import os
import base64
import re

from flask import Flask, request, Response, render_template

from shepherd import __version__

from shepherd.schema import FlockIdSchema, FlockRequestOptsSchema, GenericResponseSchema
from shepherd.schema import LaunchResponseSchema

from shepherd.api import init_routes
from shepherd.pool import create_pool
from shepherd.imageinfo import ImageInfo


# ============================================================================
class APIFlask(Flask):
    REQ_TO_POOL = 'reqp:'
    MATCH_TS = re.compile(r'([\d]{1,20})/(.*)')

    def __init__(self, shepherd, pools_filename, images_filename, name=None, *args, **kwargs):
        self.shepherd = shepherd
        self.pools = {}
        self.imageinfos = {}

        self.init_pool_config(self.load_yaml_file(pools_filename))
        self.init_image_config(self.load_yaml_file(images_filename))

        name = name or __name__

        self.include_datetime = (os.environ.get('PROXY_HOST') != None)

        self._init_api()

        super(APIFlask, self).__init__(name, *args, **kwargs)

        self.config['TEMPLATES_AUTO_RELOAD'] = True
        self.jinja_env.auto_reload = True

    def load_yaml_file(self, filename):
        with open(filename, 'rt') as fh:
            contents = fh.read()
            contents = os.path.expandvars(contents)
            config = yaml.load(contents, Loader=yaml.Loader)
            return config

    def init_pool_config(self, config):
        for data in config['pools']:
            pool = create_pool(self.shepherd, self.shepherd.redis, data)
            self.pools[pool.name] = pool

        self.default_pool = os.environ.get('DEFAULT_POOL', config.get('default_pool', ''))

    def init_image_config(self, config):
        for name, data in config['images'].items():
            info = ImageInfo(self.shepherd.docker, **data)
            self.imageinfos[name] = info

        view = config.get('view', {})

        def load_value(name, default=''):
            value = view.get(name) or default
            return os.path.expandvars(value)

        self.error_template = load_value('error_template', 'error.html')
        self.home_template = load_value('home_template')
        self.controls_template = load_value('controls_template')
        self.view_template = load_value('view_template')
        self.view_image_prefix = load_value('image_prefix')
        self.view_override_image = load_value('override')
        self.view_default_flock = os.environ.get('DEFAULT_FLOCK', load_value('default_flock'))

    def parse_url_ts(self, url):
        timestamp = ''
        m = self.MATCH_TS.match(url)
        if m:
            timestamp = m.group(1)
            url = m.group(2)

        return timestamp, url

    def init_request_env(self, user_params):
        env = {
               'URL': user_params.get('url', ''),
               'TIMESTAMP': user_params.get('timestamp', ''),
               'VNC_PASS': base64.b64encode(os.urandom(21)).decode('utf-8'),
              }

        idle_timeout = os.environ.get('IDLE_TIMEOUT')
        if idle_timeout:
            env['IDLE_TIMEOUT'] = idle_timeout

        return env

    def do_request_url_ts(self, image_name, url):
       return self.do_request(image_name, user_params=user_params)

    def do_request(self, image_name, user_params=None, flock=None):
        user_params = user_params or {}
        flock = flock or self.view_default_flock
        full_image = self.view_image_prefix + image_name

        opts = {}
        opts['environ'] = self.init_request_env(user_params)
        opts['user_params'] = user_params
        opts['overrides'] = {self.view_override_image: full_image}

        return self.get_pool().request(flock, opts)

    def render_browser(self, reqid):
        return render_template(self.view_template,
                               reqid=reqid,
                               environ=os.environ)

    def render_controls(self, url='', image_name='', view_url=''):
        timestamp, url = self.parse_url_ts(url)
        return render_template(self.controls_template if url else self.home_template,
                               url=url,
                               timestamp=timestamp,
                               image_name=image_name,
                               view_url=view_url,
                               include_datetime=self.include_datetime)

    def render_error(self, error_info):
        print(error_info)
        for key, value in list(error_info.items()):
            if value.startswith(self.view_image_prefix):
                error_info[key] = value[len(self.view_image_prefix):]

        return render_template(self.error_template,
                               info=error_info), 400


    def get_pool(self, *, pool=None, reqid=None):
        if reqid:
            pool = self.shepherd.redis.get(self.REQ_TO_POOL + reqid)

        pool = pool or self.default_pool

        try:
            return self.pools[pool]
        except KeyError:
            raise NoSuchPool(pool)

    def _init_api(self):
        # Create an APISpec
        self.apispec = APISpec(
            title='Shepherd',
            version=__version__,
            openapi_version='3.0.0',
            plugins=[
                FlaskPlugin(),
                MarshmallowPlugin(),
            ],
        )


        self.apispec.components.schema('FlockId', schema=FlockIdSchema)
        self.apispec.components.schema('FlockRequestOpts', schema=FlockRequestOptsSchema)

        self.apispec.components.schema('GenericResponse', schema=GenericResponseSchema)

        self.apispec.components.schema('LaunchResponse', schema=LaunchResponseSchema)

    def close(self):
        for pool in self.pools.values():
            pool.shutdown()

    def add_url_rule(self, rule, endpoint=None, view_func=None, **kwargs):
        req_schema = kwargs.pop('req_schema', '')
        resp_schema = kwargs.pop('resp_schema', '')

        if req_schema or resp_schema:
            view_func = Validator(view_func, req_schema, resp_schema)

        if isinstance(rule, list):
            for one_rule in rule:
                super(APIFlask, self).add_url_rule(one_rule,
                                                   endpoint=endpoint,
                                                   view_func=view_func,
                                                   **kwargs)

        else:
            super(APIFlask, self).add_url_rule(rule,
                                               endpoint=endpoint,
                                               view_func=view_func,
                                               **kwargs)

        with self.test_request_context():
            self.apispec.path(view=view_func)


# ============================================================================
class Validator():
    def __init__(self, the_func, req_schema=None, resp_schema=None):
        self.the_func = the_func
        self.req_schema = req_schema
        self.resp_schema = resp_schema
        self.__doc__ = the_func.__doc__
        self.__name__ = the_func.__name__

    def make_response(self, resp, status_code=200, mimetype='application/json'):
        response = Response(json.dumps(resp), mimetype=mimetype)
        if status_code != 200:
            response.status_code = status_code

        return response

    def __call__(self, *args, **kwargs):
        status_code = 200
        resp = None

        if self.req_schema:
            try:
                input_data = request.json or {}
                req_params = self.req_schema().load(input_data)
                kwargs['request'] = req_params
            except marshmallow.exceptions.ValidationError as ve:
                return self.make_response({'error': 'invalid_options', 'details': str(ve)}, 400)

        try:
            resp = self.the_func(*args, **kwargs)

        except NoSuchPool as ns:
            return self.make_response({'error': 'no_such_pool', 'pool': str(ns)}, 400)

        except Exception as e:
            import traceback
            traceback.print_exc()
            return self.make_response({'error': str(e)}, 400)

        if self.resp_schema:
            try:
                schema = self.resp_schema()
                if 'error' in resp:
                    status_code = 404
                else:
                    resp = schema.dump(resp)

            except marshmallow.exceptions.ValidationError as ve:
                status_code = 400
                resp = {'error': str(ve)}

        return self.make_response(resp, status_code)


# ============================================================================
class NoSuchPool(Exception):
    pass



# ============================================================================
def create_app(*args, **kwargs):
    app = APIFlask(*args, **kwargs)

    init_routes(app)

    return app

