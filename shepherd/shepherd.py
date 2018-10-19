import docker
import yaml
import json
import base64
import os
import time

from redis import StrictRedis

from shepherd.schema import AllFlockSchema, InvalidParam


# ============================================================================
class Shepherd(object):
    DEFAULT_FLOCKS = 'flocks.yaml'

    NETWORK_NAME = 'shepherd.net-{0}'

    USER_PARAMS_KEY = 'up:{0}'

    def __init__(self, redis, networks_templ):
        self.flocks = {}
        self.docker = docker.from_env()
        self.redis = redis
        self.networks_templ = networks_templ

    def load_flocks(self, flocks_file):
        with open(flocks_file) as fh:
            data = yaml.load(fh.read())
            flocks = AllFlockSchema().load(data)
            for flock in flocks['flocks']:
                self.flocks[flock['name']] = flock

    def request_flock(self, flock_name, **kwargs):
        if flock_name not in self.flocks:
            return {'error': 'invalid_flock',
                    'flock': flock_name}

        flock_req = FlockRequest().init_new(flock_name, **kwargs)
        flock_req.save(self.redis)
        return {'reqid': flock_req.reqid}

    def start_flock(self, reqid):
        flock_req = FlockRequest(reqid)
        if not flock_req.load(self.redis):
            return {'error': 'invalid_req'}

        try:
            flock_name = flock_req.data['flock']
            flock = self.flocks[flock_name]
        except:
            return {'error': 'invalid_flock',
                    'flock': flock_name}

        overrides = flock_req.get_overrides()

        try:
            image_list = self.resolve_image_list(flock['containers'], overrides)
        except InvalidParam as ip:
            return ip.msg

        network = self.create_flock_network(flock_req)
        containers = {}

        for image, spec in zip(image_list, flock['containers']):
            container, info = self.run_container(image, spec, flock_req, network)
            containers[spec['name']] = info

        return {
                'containers': containers,
                'network': network.name
               }

    def short_id(self, container):
        return container.id[:12]

    def get_ip(self, container, network):
        return container.attrs['NetworkSettings']['Networks'][network.name]['IPAddress']

    def get_ports(self, container, port_map):
        ports = {}
        if not port_map:
            return ports

        for port_name in port_map:
            try:
                port = port_map[port_name]
                pinfo = container.attrs['NetworkSettings']['Ports'][str(port) + '/tcp']
                pinfo = pinfo[0]
                ports[port_name] = int(pinfo['HostPort'])

            except:
                ports[port_name] = -1

        return ports

    def run_container(self, image, spec, flock_req, network):
        api = self.docker.api

        net_config = api.create_networking_config({
            network.name: api.create_endpoint_config(
                aliases=[spec['name']],
            )
        })

        ports = spec.get('ports')
        if ports:
            port_values = list(ports.values())
            port_bindings = {int(port): None for port in port_values}
        else:
            port_values = None
            port_bindings = None

        host_config = api.create_host_config(auto_remove=True,
                                             cap_add=['ALL'],
                                             port_bindings=port_bindings)

        name = spec['name'] + '-' + flock_req.reqid

        env = spec.get('environment') or {}
        env.update(flock_req.data['environment'])

        cdata = api.create_container(
            image,
            networking_config=net_config,
            ports=port_values,
            name=name,
            host_config=host_config,
            detach=True,
            hostname=spec['name'],
            environment=env,
        )

        container = self.docker.containers.get(cdata['Id'])
        container.start()

        # reload to get updated data
        container.reload()

        info = {}
        info['id'] = self.short_id(container)
        info['ip'] = self.get_ip(container, network)
        info['ports'] = self.get_ports(container, ports)

        if info['ip'] and flock_req.data['user_params'] and spec.get('set_user_params'):
            self.redis.hmset(self.USER_PARAMS_KEY.format(info['ip']), flock_req.data['user_params'])

        return container, info

    def create_flock_network(self, flock_req):
        network = self.docker.networks.create(self.NETWORK_NAME.format(flock_req.reqid))
        return network

    def resolve_image_list(self, specs, overrides):
        image_list = []
        for spec in specs:
            image = overrides.get(spec['name'], spec['image'])
            image_list.append(image)
            if image != spec['image']:
                if not self.is_ancestor_of(image, spec['image']):
                    raise InvalidParam({'error': 'invalid_image_param',
                                        'image_passed': image,
                                        'image_expected': spec['image']
                                       })

        return image_list

    def is_ancestor_of(self, name, ancestor):
        name = self.full_tag(name)
        ancestor = self.full_tag(ancestor)
        try:
            image = self.docker.images.get(name)
        except docker.errors.ImageNotFound:
            return False

        history = image.history()
        for entry in history:
            if entry.get('Tags') and ancestor in entry['Tags']:
                return True

        return False

    def stop_flock(self, reqid):
        flock_req = FlockRequest(reqid)
        network = self.docker.networks.get(self.NETWORK_NAME.format(reqid))

        for container in network.containers:
            try:
                ip = self.get_ip(container, network)
                self.redis.delete(self.USER_PARAMS_KEY.format(ip))
            except:
                pass

            try:
                container.kill()
                container.remove(v=True, link=True, force=True)
            except docker.errors.APIError:
                pass

        network.remove()
        flock_req.delete(self.redis)

    @classmethod
    def full_tag(cls, tag):
        return tag + ':latest' if ':' not in tag else tag


# ===========================================================================
class FlockRequest(object):
    REQ_KEY = 'req:{0}'
    REQ_TTL = 120

    def __init__(self, reqid=None):
        if not reqid:
            reqid = self._make_reqid()
        self.reqid = reqid

    def _make_reqid(self):
        return base64.b32encode(os.urandom(15)).decode('utf-8')

    def init_new(self, flock_name, overrides, environment=None, user_params=None):
        overrides = overrides or {}
        environment = environment or {}
        user_params = user_params or {}
        self.data = {'id': self.reqid,
                     'overrides': overrides,
                     'flock': flock_name,
                     'user_params': user_params,
                     'environment': environment,
                    }
        return self

    def get_overrides(self):
        return self.data.get('overrides') or {}

    def load(self, redis):
        key = self.REQ_KEY.format(self.reqid)
        self.data = json.loads(redis.get(key))
        return self.data != {}

    def save(self, redis):
        key = self.REQ_KEY.format(self.reqid)
        redis.set(key, json.dumps(self.data), ex=self.REQ_TTL)

    def delete(self, redis):
        key = self.REQ_KEY.format(self.reqid)
        redis.delete(key)



# ===========================================================================
if __name__ == '__main__':
    pass
    #shep = Shepherd(StrictRedis('redis://redis/3'))
    #res = shep.request_flock('test', {'foo': 'bar'})

    #print(res['reqid'])



