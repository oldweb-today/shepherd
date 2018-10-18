from marshmallow import Schema, fields, pprint


class ContainerSchema(Schema):
    name = fields.String()
    image = fields.String()
    ports = fields.List(fields.Int())

class FlockSchema(Schema):
    name = fields.String()
    containers = fields.Nested(ContainerSchema, many=True)

class AllFlockSchema(Schema):
    flocks = fields.Nested(FlockSchema, many=True)


class InvalidParam(Exception):
    def __init__(self, msg):
        self.msg = msg
