from shepherd.schema import FlockIdSchema, FlockRequestOptsSchema, GenericResponseSchema
from shepherd.schema import LaunchResponseSchema, LaunchContainerSchema, FlockRequestDataSchema
from shepherd.shepherd import FlockRequest

from flask import Response, request


# ============================================================================
def init_routes(app):
    @app.route('/api/request_flock/<flock>', methods=['POST'], endpoint='request_flock',
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


    @app.route('/api/start_flock/<reqid>', methods=['POST'],
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

    @app.route('/api/stop_flock/<reqid>', methods=['POST'],
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


    @app.route('/api/start_deferred/<reqid>/<name>', methods=['POST'],
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

    @app.route(['/api/flock/<reqid>', '/api/<pool>/flock/<reqid>'],
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

    @app.route('/api', methods=['GET'])
    def print_api():
        return Response(app.apispec.to_yaml(), mimetype='text/yaml')

