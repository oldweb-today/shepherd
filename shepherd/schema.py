from marshmallow import Schema, fields, pprint

def string_dict():
    return fields.Dict(keys=fields.String())

class ContainerSchema(Schema):
    name = fields.String()
    image = fields.String()
    ports = fields.Dict(keys=fields.String(), values=fields.Int(), default={})
    environment = string_dict()
    external_network = fields.String()
    set_user_params = fields.Boolean(default=False)
    deferred = fields.Boolean(default=False)

class FlockSpecSchema(Schema):
    name = fields.String()
    containers = fields.Nested(ContainerSchema, many=True)
    volumes = string_dict()
    auto_remove = fields.Boolean()

class AllFlockSchema(Schema):
    flocks = fields.Nested(FlockSpecSchema, many=True)


class InvalidParam(Exception):
    def __init__(self, msg):
        self.msg = msg


# HTTP API
class FlockIdSchema(Schema):
    flock = fields.String(required=True)

class FlockRequestOptsSchema(Schema):
    overrides = string_dict()
    user_params = string_dict()
    environ = string_dict()

class GenericResponseSchema(Schema):
    reqid = fields.String()
    error = fields.String()
    success = fields.Boolean()

class LaunchContainerSchema(Schema):
    ip = fields.String()
    ports = fields.Dict(keys=fields.String(), values=fields.Int())
    id = fields.String()
    deferred = fields.Boolean()
    image = fields.String()

class LaunchResponseSchema(Schema):
    reqid = fields.String()
    queued = fields.Int()
    network = fields.String()
    containers = fields.Dict(keys=fields.String(), values=fields.Nested(LaunchContainerSchema))


