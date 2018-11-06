import docker
import yaml
import json
import base64
import os
import time
import traceback

from redis import StrictRedis

from shepherd.schema import AllFlockSchema, InvalidParam


# ============================================================================
class Shepherd(object):
    DEFAULT_FLOCKS = 'flocks.yaml'

    NETWORK_NAME = 'shepherd.net-{0}'

    USER_PARAMS_KEY = 'up:{0}'

    SHEP_REQID_LABEL = 'owt.shepherd.reqid'

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

    def request_flock(self, flock_name, req_opts=None, ttl=None):
        req_opts = req_opts or {}
        try:
            flock = self.flocks[flock_name]
        except:
            return {'error': 'invalid_flock',
                    'flock': flock_name}

        flock_req = FlockRequest().init_new(flock_name, req_opts)

        overrides = flock_req.get_overrides()

        try:
            image_list = self.resolve_image_list(flock['containers'], overrides)
        except InvalidParam as ip:
            return ip.msg

        flock_req.data['image_list'] = image_list
        flock_req.save(self.redis, expire=ttl)

        return {'reqid': flock_req.reqid}

    def start_flock(self, reqid, labels=None):
        flock_req = FlockRequest(reqid)
        if not flock_req.load(self.redis):
            return {'error': 'invalid_reqid'}

        response = flock_req.get_cached_response()
        if response:
            return response

        try:
            flock_name = flock_req.data['flock']
            image_list = flock_req.data['image_list']
            flock = self.flocks[flock_name]
        except:
            return {'error': 'invalid_flock',
                    'flock': flock_name}

        network = None
        containers = {}

        try:
            network = self.create_flock_network(flock_req)

            links = flock.get('links', [])
            for link in links:
                self.link_external_container(network, link)

            for image, spec in zip(image_list, flock['containers']):
                container, info = self.run_container(image, spec, flock_req, network, labels=labels)
                containers[spec['name']] = info

        except:
            traceback.print_exc()

            try:
                self.stop_flock(reqid)
            except:
                pass

            return {'error': 'start_error',
                    'details': traceback.format_exc()
                   }

        response = {'containers': containers,
                    'network': network.name
                   }

        flock_req.cache_response(response, self.redis)
        return response

    def link_external_container(self, network, link):
        if ':' in link:
            name, alias = link.split(':', 1)
        else:
            name = link
            alias = link

        res = network.connect(name, aliases=[alias])

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

    def run_container(self, image, spec, flock_req, network, labels=None):
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

        labels = labels or {}
        labels[self.SHEP_REQID_LABEL] = flock_req.reqid

        cdata = api.create_container(
            image,
            networking_config=net_config,
            ports=port_values,
            name=name,
            host_config=host_config,
            detach=True,
            hostname=spec['name'],
            environment=env,
            labels=labels
        )

        container = self.docker.containers.get(cdata['Id'])
        container.start()

        external_network = spec.get('external_network')
        if external_network:
            external_network = self.docker.networks.get(external_network)
            external_network.connect(container)

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
        flock_req.delete(self.redis)

        try:
            network = self.docker.networks.get(self.NETWORK_NAME.format(reqid))
            containers = network.containers
        except:
            network = None
            containers = self.docker.containers.list(filters={'label': self.SHEP_REQID_LABEL + '=' + reqid})

        for container in containers:
            if container.labels.get(self.SHEP_REQID_LABEL) != reqid:
                try:
                    network.disconnect(container)
                except:
                    pass

                continue

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

        try:
            network.remove()
        except:
            pass

        return {'success': True}

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
        self.key = self.REQ_KEY.format(self.reqid)

    def _make_reqid(self):
        return base64.b32encode(os.urandom(15)).decode('utf-8')

    def init_new(self, flock_name, req_opts):
        self.data = {'id': self.reqid,
                     'flock': flock_name,
                     'overrides': req_opts.get('overrides', {}),
                     'user_params': req_opts.get('user_params', {}),
                     'environment': req_opts.get('environment', {}),
                    }
        return self

    def get_overrides(self):
        return self.data.get('overrides') or {}

    def load(self, redis):
        data = redis.get(self.key)
        self.data = json.loads(data) if data else {}
        return self.data != {}

    def save(self, redis, expire=None):
        if expire is None:
            expire = self.REQ_TTL
        elif expire == -1:
            expire = None

        redis.set(self.key, json.dumps(self.data), ex=expire)

    def get_cached_response(self):
        return self.data.get('resp')

    def cache_response(self, resp, redis):
        resp['running'] = '1'
        self.data['resp'] = resp
        self.save(redis, expire=None)
        redis.persist(self.key)

    def delete(self, redis):
        redis.delete(self.key)


# ===========================================================================
if __name__ == '__main__':
    pass
    #shep = Shepherd(StrictRedis('redis://redis/3'))
    #res = shep.request_flock('test', {'foo': 'bar'})

    #print(res['reqid'])



