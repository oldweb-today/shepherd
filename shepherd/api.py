from shepherd.schema import FlockIdSchema, FlockRequestOptsSchema, GenericResponseSchema
from shepherd.schema import LaunchResponseSchema, LaunchContainerSchema, FlockRequestDataSchema
from shepherd.shepherd import FlockRequest

from flask import Response, request
import json


# ============================================================================
def init_routes(app):
    @app.route('/api/flock/request/<flock>', methods=['POST'], endpoint='request_flock',
               req_schema=FlockRequestOptsSchema,
               resp_schema=GenericResponseSchema)
    def request_flock(flock, **kwargs):
        """Request a new flock
        ---
        post:
            summary: Request a new flock by flock id
            parameters:
                - in: path
                  name: flock
                  schema: FlockIdSchema
                  description: Flock id from the flocks.yaml file

                - in: query
                  name: pool
                  schema: {type: string}
                  description: the scheduling pool to use for this flock

            requestBody:
                description: optional user params, environment, and image overrides
                required: false
                content:
                    application/json:
                        schema: FlockRequestOptsSchema

            responses:
                200:
                    description: A flock response
                    schema: GenericResponseSchema

                400:
                    schema: GenericResponseSchema

                404:
                    schema: GenericResponseSchema
        """
        pool = request.args.get('pool', '')
        return app.get_pool(pool=pool).request(flock, kwargs.get('request'))


    @app.route('/api/flock/start/<reqid>', methods=['POST'],
               resp_schema=LaunchResponseSchema)
    def start_flock(reqid):
        """Start a flock from reqid
        ---
        post:
            summary: Request a new flock by flock id
            parameters:
                - in: path
                  name: reqid
                  schema: {type: string}
                  description: a unique request id that was created from flock request

                - in: path
                  name: pool
                  schema: {type: string}
                  description: the scheduling pool to use for this flock

            responses:
                200:
                    description: A flock launch response
                    schema: LaunchResponseSchema

                400:
                    schema: GenericResponseSchema

                404:
                    schema: GenericResponseSchema
        """
        json_data = request.json or {}
        return app.get_pool(reqid=reqid).start(reqid, environ=json_data.get('environ'))

    @app.route('/api/flock/stop/<reqid>', methods=['POST'],
               resp_schema=GenericResponseSchema)
    def stop_flock(reqid):
        """Stop a flock from reqid
        ---
        post:
            summary: Stop flock by id
            parameters:
                - in: path
                  name: reqid
                  schema: {type: string}
                  description: a unique request id that was created from flock request

                - in: path
                  name: pool
                  schema: {type: string}
                  description: the scheduling pool to use for this flock

            responses:
                200:
                    description: Returns 'success' if stopped
                    schema: GenericResponseSchema

                400:
                    schema: GenericResponseSchema

                404:
                    schema: GenericResponseSchema
        """
        app.get_pool(reqid=reqid).stop(reqid)
        return {'success': True}


    @app.route('/api/flock/start_deferred/<reqid>/<name>', methods=['POST'],
               resp_schema=LaunchContainerSchema)
    def start_deferred_container(reqid, name):
        """Start a 'deferred' container that was not started automatically
           in an existing running flock
        ---
        post:
            summary: Request a new flock by flock id
            parameters:
                - in: path
                  name: reqid
                  schema: {type: string}
                  description: a unique request id that was created from flock request

                - in: path
                  name: pool
                  schema: {type: string}
                  description: the scheduling pool to use for this flock

                - in: path
                  name: name
                  schema: {type: string}
                  description: the name of deferred container to start

            responses:
                200:
                    description: A container launch response
                    schema: GenericResponseSchema

                400:
                    schema: GenericResponseSchema

                404:
                    schema: GenericResponseSchema
        """
        return app.get_pool(reqid=reqid).start_deferred_container(reqid, name)

    @app.route(['/api/flock/<reqid>'],
               methods=['GET'],
               resp_schema=FlockRequestDataSchema)
    def get_flock(reqid):
        """ Get information of a running flock request
        ---
        get:
            summary: Get information about a running flock
            parameters:
                - in: path
                  name: reqid
                  schema: {type: string}
                  description: a unique request id that was created from flock request

            responses:
                200:
                    description: Flock request info
                    schema: GenericResponseSchema

                404:
                    description: Flock request not found
                    schema: GenericResponseSchema
        """

        flock_req = FlockRequest(reqid)
        if not flock_req.load(app.shepherd.redis):
            return {'error': 'invalid_reqid'}

        return flock_req.data


    @app.route('/api/images/<image_group>', methods=['GET'])
    def get_images(image_group):
        res = app.imageinfos[image_group].list_images(request.args)
        return Response(json.dumps(res), mimetype='application/json')


    @app.route('/api', methods=['GET'])
    def print_api():
        return Response(app.apispec.to_yaml(), mimetype='text/yaml')


    @app.route('/api/request/<image_name>/<path:url>')
    def api_image_request(image_name, url):
        if request.query_string:
            url += '?' + request.query_string.decode('utf-8')

        res = app.do_request(image_name, url=url)
        return Response(json.dumps(res), mimetype='application/json')

    @app.route('/view/<image_name>/<path:url>')
    def view_request(image_name, url):
        if request.query_string:
            url += '?' + request.query_string.decode('utf-8')

        res = app.do_request(image_name, url=url)

        reqid = res.get('reqid')

        if not reqid:
            return app.render_error(res)

        return app.render(reqid)


    @app.route('/attach/<reqid>')
    def attach_request(reqid):
        if not app.shepherd.is_valid_flock(reqid):
            return app.render_error({'error': 'invalid_reqid'})

        return app.render(reqid)


