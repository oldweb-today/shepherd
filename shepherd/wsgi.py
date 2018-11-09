from apispec import APISpec
from apispec.ext.flask import FlaskPlugin
from apispec.ext.marshmallow import MarshmallowPlugin

import marshmallow
import json

from flask import Flask, jsonify, request, Response

from shepherd import __version__

from shepherd.schema import FlockIdSchema, FlockRequestOptsSchema, GenericResponseSchema
from shepherd.schema import LaunchResponseSchema

from shepherd.api import init_routes


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
                input_data = request.json or{}
                req_params = self.req_schema().load(input_data)
                kwargs['request'] = req_params
            except marshmallow.exceptions.ValidationError as ve:
                return self.make_response({'error': 'invalid_options', 'details': str(ve)}, 400)

        try:
            resp = self.the_func(*args, **kwargs)

        except NoSuchPool as ns:
            return self.make_response({'error': 'no_such_pool', 'pool': str(ns)}, 400)

        except Exception as e:
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
class APIFlask(Flask):
    def __init__(self, shepherd, pools, name=None, **kwargs):
        self.shepherd = shepherd

        if not isinstance(pools, dict):
            self.pools = {'': pools}
        else:
            self.pools = pools

        name = name or __name__

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

        super(APIFlask, self).__init__(name, **kwargs)

        self.apispec.definition('FlockId', schema=FlockIdSchema)
        self.apispec.definition('FlockRequestOpts', schema=FlockRequestOptsSchema)

        self.apispec.definition('GenericResponse', schema=GenericResponseSchema)

        self.apispec.definition('LaunchResponse', schema=LaunchResponseSchema)

    def get_pool(self, name):
        try:
            return self.pools[name]
        except KeyError:
            raise NoSuchPool(name)

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
            self.apispec.add_path(view=view_func)


# ============================================================================
def create_app(shepherd, pool, **kwargs):
    app = APIFlask(shepherd, pool, **kwargs)

    init_routes(app)

    return app

