import docker
import yaml
import json
import os
import time
import traceback

from redis import StrictRedis

from shepherd.flock import FlockRequest
from shepherd.schema import FlockSpecSchema, InvalidParam
from shepherd.network_pool import NetworkPool

import gevent

import logging

logger = logging.getLogger('shepherd')



# ============================================================================
class Shepherd(object):
    DEFAULT_FLOCKS = 'flocks.yaml'

    USER_PARAMS_KEY = 'up:{0}'
    C_TO_U_KEY = 'cu:{0}'

    SHEP_REQID_LABEL = 'owt.shepherd.reqid'

    SHEP_DEFERRED_LABEL = 'owt.shepherd.deferred'

    DEFAULT_REQ_TTL = 120

    UNTRACKED_CHECK_TIME = 30

    DEFAULT_SHM_SIZE = '1g'

    VOLUME_TEMPL = 'vol-{name}-{reqid}'

    def __init__(self, redis, network_templ=None, volume_templ=None,
                 reqid_label=None, untracked_check_time=None, network_label=None):
        self.flocks = {}
        self.docker = docker.from_env()
        self.redis = redis

        self.network_pool = NetworkPool(self.docker,
                                        network_templ=network_templ,
                                        network_label=network_label)

        self.volume_templ = volume_templ or self.VOLUME_TEMPL

        self.reqid_label = reqid_label or self.SHEP_REQID_LABEL

        self.untracked_check_time = 0
        self.start_cleanup_loop(untracked_check_time)

    def start_cleanup_loop(self, untracked_check_time):
        if self.untracked_check_time > 0:
            # already started
            return

        if untracked_check_time is None:
            untracked_check_time = self.UNTRACKED_CHECK_TIME

        self.untracked_check_time = untracked_check_time

        if untracked_check_time > 0:
            gevent.spawn(self.untracked_check_loop)

    def load_flocks(self, flocks_file_or_dir):
        num_loaded = 0
        if os.path.isfile(flocks_file_or_dir):
            num_loaded += self._load_flocks_file(flocks_file_or_dir)
        elif os.path.isdir(flocks_file_or_dir):
            for path in os.listdir(flocks_file_or_dir):
                if path.endswith(('.yaml', '.yml')):
                    num_loaded += self._load_flocks_file(os.path.join(flocks_file_or_dir, path))

        return num_loaded

    def _load_flocks_file(self, filename):
        num_loaded = 0
        with open(filename, 'rt') as fh:
            contents = fh.read()
            contents = os.path.expandvars(contents)
            all_flocks = yaml.load_all(contents, Loader=yaml.Loader)
            for data in all_flocks:
                flock = FlockSpecSchema().load(data)
                self.flocks[flock['name']] = flock
                num_loaded += 1

        return num_loaded

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
        flock_req.data['num_volumes'] = len(flock.get('volumes', []))
        ttl = ttl or self.DEFAULT_REQ_TTL
        flock_req.save(self.redis, expire=ttl)

        return {'reqid': flock_req.reqid}

    def is_valid_flock(self, reqid, ensure_state=None):
        flock_req = FlockRequest(reqid)
        if not flock_req.load(self.redis):
            return False

        if ensure_state and ensure_state != flock_req.get_state():
            return False

        return True

    def start_flock(self, reqid,
                    labels=None,
                    environ=None,
                    auto_remove=False,
                    network_pool=None):

        flock_req = FlockRequest(reqid)
        state = flock_req.get_state()
        if state == 'stopped':
            return {'error': 'already_done'}

        response = flock_req.load_cached_response(self.redis)
        if response:
            return response

        flock_req.update_env(environ, self.redis, save=False)

        try:
            flock_name = flock_req.data['flock']
            image_list = flock_req.data['image_list']
            flock_spec = self.flocks[flock_name]
        except:
            return {'error': 'invalid_flock',
                    'flock': flock_name}

        req_deferred = flock_req.data.get('deferred', {})

        network = None
        containers = {}

        labels = labels or {}
        labels[self.reqid_label] = flock_req.reqid

        try:
            flock_req.set_state('running', self.redis)

            network_pool = network_pool or self.network_pool
            network = network_pool.create_network()

            flock_req.set_network(network.name)

            flock_req.data['auto_remove'] = auto_remove

            volume_binds, volumes = self.get_volumes(flock_req, flock_spec, labels, create=True)

            for image, spec in zip(image_list, flock_spec['containers']):
                name = spec['name']

                if name in req_deferred:
                    deferred = req_deferred[name]
                else:
                    deferred = spec.get('deferred', False)

                if deferred:
                    info = {'deferred': True, 'image': image}

                else:
                    res = self.run_container(image, spec, flock_req, network,
                                             labels=labels,
                                             volume_binds=volume_binds,
                                             volumes=volumes,
                                             auto_remove=auto_remove)
                    container, info = res

                containers[spec['name']] = info

        except:
            traceback.print_exc()

            try:
                self.remove_flock(reqid)
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

    def short_id(self, container):
        return container.id[:12]

    def get_ip(self, container, network):
        return container.attrs['NetworkSettings']['Networks'][network.name]['IPAddress']

    def get_ports(self, container, port_map):
        ports = {}
        if not port_map:
            return ports

        for port_name, port in port_map.items():
            try:
                pinfo = container.attrs['NetworkSettings']['Ports'][port]
                pinfo = pinfo[0]
                ports[port_name] = int(pinfo['HostPort'])

            except:
                ports[port_name] = -1

        return ports

    def start_deferred_container(self, reqid, image_name, labels=None):
        flock_req = FlockRequest(reqid)
        if not flock_req.load(self.redis):
            return {'error': 'invalid_reqid'}

        state = flock_req.get_state()
        if state != 'running':
            return {'error': 'flock_not_running', 'state': state}

        response = flock_req.get_cached_response()

        try:
            flock_name = flock_req.data['flock']
            flock_spec = self.flocks[flock_name]

            info = response['containers'][image_name]

            # ensure actually a deferred container
            assert(info['deferred'])

            # already started, just return cached response
            if 'id' in info:
                return info

        except:
            traceback.print_exc()
            return {'error': 'invalid_deferred',
                    'flock': flock_name}

        try:
            labels = labels or {}
            labels[self.reqid_label] = flock_req.reqid
            labels[self.SHEP_DEFERRED_LABEL] = '1'

            spec = self.find_spec_for_flock_req(flock_req, image_name)

            try:
                network = self.get_network(flock_req)
            except:
                network = None

            auto_remove = flock_req.data['auto_remove']

            volume_binds, volumes = self.get_volumes(flock_req, flock_spec, labels, create=False)

            res = self.run_container(info['image'], spec, flock_req, network,
                                     labels=labels,
                                     volume_binds=volume_binds,
                                     volumes=volumes,
                                     auto_remove=auto_remove)

            info.update(res[1])

        except:
            traceback.print_exc()
            return {'error': 'error_starting_deferred',
                    'flock': flock_name}

        flock_req.cache_response(response, self.redis)
        return info

    def find_spec_for_flock_req(self, flock_req, image_name):
        try:
            flock_name = flock_req.data['flock']
            flock_spec = self.flocks[flock_name]
            for spec in flock_spec['containers']:
                if spec['name'] == image_name:
                    return spec
        except:
            pass

        return None

    def run_container(self, image, spec, flock_req, network, labels=None,
                      volumes=None,
                      volume_binds=None,
                      auto_remove=False):

        api = self.docker.api

        net_config = api.create_networking_config({
            network.name: api.create_endpoint_config(
                aliases=[spec['name']],
            )
        })

        port_values = []
        port_bindings = {}

        ports = spec.get('ports', {})

        for port_name, port in ports.items():
            if isinstance(port, int) or '/' not in port:
                port = str(port) + '/tcp'
                ports[port_name] = port

            port_bindings[port] = None
            port_values.append(tuple(port.split('/', 1)))

        host_config = api.create_host_config(auto_remove=auto_remove,
                                             cap_add=['ALL'],
                                             shm_size=spec.get('shm_size', self.DEFAULT_SHM_SIZE),
                                             security_opt=['apparmor=unconfined'],
                                             port_bindings=port_bindings,
                                             binds=volume_binds)

        name = spec['name'] + '-' + flock_req.reqid

        environ = spec.get('environment') or {}
        if 'environ' in flock_req.data:
            environ = environ.copy()
            environ.update(flock_req.data['environ'])

        cdata = api.create_container(
            image,
            networking_config=net_config,
            ports=port_values,
            name=name,
            host_config=host_config,
            detach=True,
            hostname=spec['name'],
            environment=environ,
            labels=labels,
            volumes=volumes
        )

        container = self.docker.containers.get(cdata['Id'])

        external_network = spec.get('external_network')
        if external_network:
            external_network = self.docker.networks.get(external_network)
            external_network.connect(container)

        container.start()

        # reload to get updated data
        container.reload()

        info = {}
        info['id'] = self.short_id(container)

        if external_network:
            info['ip'] = self.get_ip(container, external_network)
        else:
            info['ip'] = self.get_ip(container, network)

        info['ports'] = self.get_ports(container, ports)

        if info['ip'] and spec.get('set_user_params'):
            # add reqid to userparams
            flock_req.data['user_params']['reqid'] = flock_req.reqid
            up_key = self.USER_PARAMS_KEY.format(info['ip'])
            self.redis.hmset(up_key, flock_req.data['user_params'])
            self.redis.set(self.C_TO_U_KEY.format(info['id']), up_key)

        info['environ'] = environ

        return container, info

    def get_network(self, flock_req):
        name = flock_req.get_network()
        if not name:
            return None

        return self.docker.networks.get(name)

    def resolve_image_list(self, specs, overrides):
        image_list = []
        for spec in specs:
            image = overrides.get(spec['name'], spec['image'])
            image_list.append(image)
            if image != spec['image']:
                label = spec.get('image_label')
                if not label:
                    raise InvalidParam({'error': 'invalid_image_param',
                                        'details': 'no image_label to allow overrides'})

                if not self.image_has_label(image, label):
                    raise InvalidParam({'error': 'invalid_image_param',
                                        'image_passed': image,
                                        'label_expected': label
                                       })

        return image_list

    def image_has_label(self, image_name, label):
        try:
            image = self.docker.images.get(image_name)
        except docker.errors.ImageNotFound:
            return False

        if '=' in label:
            name, value = label.split('=', 1)
            return image.labels.get(name) == value
        else:
            return image.labels.get(label, '') != ''

    def is_ancestor_of(self, name, ancestor):
        name = self.full_tag(name)
        ancestor = self.full_tag(ancestor)
        try:
            image = self.docker.images.get(name)
            base_image = self.docker.images.get(ancestor)
        except docker.errors.ImageNotFound:
            return False

        base_layers = base_image.attrs['RootFS']['Layers']
        layers = image.attrs['RootFS']['Layers']

        # layers should start with base_layers if base is ancestor
        # of image

        # can't be ancestor if has more layers in base
        if len(base_layers) > len(layers):
            return False

        return layers[:len(base_layers)] == base_layers


    def remove_flock(self, reqid, keep_reqid=False, grace_time=None, network_pool=None):
        flock_req = FlockRequest(reqid)
        if not flock_req.load(self.redis):
            return {'error': 'invalid_reqid'}

        try:
            network = self.get_network(flock_req)
        except:
            network = None

        containers = self.get_flock_containers(flock_req)

        for container in containers:
            if container.labels.get(self.reqid_label) != reqid:
                continue

            try:
                ip = self.get_ip(container, network)
                self.redis.delete(self.USER_PARAMS_KEY.format(ip))
            except:
                pass

            self._remove_container(container, grace_time=grace_time)

        if network:
            try:
                network_pool = network_pool or self.network_pool
                network_pool.remove_network(network)
            except Exception as e:
                logger.error(str(e))

        try:
            self.remove_flock_volumes(flock_req)
        except:
            pass

        # delete flock after docker removal is finished to avoid race condition
        # with 'untracked' container removal
        if not keep_reqid:
            flock_req.delete(self.redis)
        else:
            flock_req.stop(self.redis)

        return {'success': True}

    def _remove_container(self, container, v=False, grace_time=0):
        short_id = self.short_id(container)

        try:
            if grace_time:
                logger.debug('Graceful Stop: ' + short_id)
                self._do_graceful_stop(container, grace_time)
            else:
                logger.debug('Kill Container: ' + short_id)
                container.kill()
        except docker.errors.APIError as e:
            logger.error(str(e))

        try:
            c_to_uparams = self.C_TO_U_KEY.format(short_id)
            res = self.redis.get(c_to_uparams)
            if res:
                self.redis.delete(res)
                self.redis.delete(c_to_uparams)

            container.remove(force=True, v=v)
            return short_id

        except docker.errors.APIError as e:
            logger.error(str(e))
            return None

    def _do_graceful_stop(self, container, grace_time):
        def do_stop():
            try:
                container.stop(timeout=grace_time)
            except docker.errors.APIError as e:
                logger.error(str(e))

        gevent.spawn(do_stop)

    def get_volumes(self, flock_req, flock_spec, labels=None, create=False):
        volume_spec = flock_spec.get('volumes')
        if not volume_spec:
            return None, None

        volumes_list = []
        volume_binds = []

        for n, v in volume_spec.items():
            vol_name = self.volume_templ.format(reqid=flock_req.reqid, name=n)

            if create:
                volume = self.docker.volumes.create(vol_name, labels=labels)

            volumes_list.append(v)

            volume_binds.append(vol_name + ':' + v)

        return volume_binds, volumes_list

    def get_flock_containers(self, flock_req):
        return self.docker.containers.list(all=True,
                                           filters={'label': self.reqid_label + '=' + flock_req.reqid},
                                           ignore_removed=True) or []

    def remove_flock_volumes(self, flock_req):
        num_volumes = flock_req.data.get('num_volumes', 0)

        for x in range(0, 3):
            res = self.docker.volumes.prune(filters={'label': self.reqid_label + '=' + flock_req.reqid})
            num_volumes -= len(res.get('VolumesDeleted', []))

            if num_volumes == 0:
                return True

            # if not all volumes deleted yet, wait and try again
            time.sleep(1.0)

        return num_volumes == 0

    def stop_flock(self, reqid, grace_time=1):
        flock_req = FlockRequest(reqid)
        if not flock_req.load(self.redis):
            return {'error': 'invalid_reqid'}

        state = flock_req.get_state()
        if state != 'running':
            return {'error': 'not_running', 'state': state}

        try:
            containers = self.get_flock_containers(flock_req)

            for container in containers:
                print('Stopping {0} with grace {1}'.format(container.id, grace_time))
                self._do_graceful_stop(container, grace_time)

            flock_req.set_state('stopped', self.redis)

        except:
            traceback.print_exc()

            return {'error': 'stop_failed',
                    'details': traceback.format_exc()
                   }

        return {'success': True}

    def untracked_check_loop(self):
        print('Untracked Container Check Loop Started')

        filters = {'label': self.reqid_label}

        while self.untracked_check_time > 0:
            try:
                all_containers = self.docker.containers.list(all=False,
                                                             filters=filters,
                                                             ignore_removed=True)

                reqids = set()
                network_names = set()

                for container in all_containers:
                    reqid = container.labels.get(self.reqid_label)

                    if self.is_valid_flock(reqid):
                        continue

                    print('Invalid Flock: ' + reqid)

                    reqids.add(reqid)

                    short_id = self._remove_container(container)
                    print('Removed untracked container from flock {0}: {1}'.format(reqid, short_id))

                # remove volumes + reqid
                for reqid in reqids:
                    try:
                        res = self.docker.volumes.prune(filters={'label': self.reqid_label + '=' + reqid})
                        pruned_volumes = len(res.get('VolumesDeleted', []))
                        if pruned_volumes:
                            print('Removed Untracked Volumes: {0}'.format(pruned_volumes))
                    except:
                        pass

                    FlockRequest(reqid).delete(self.redis)

                # remove any networks these containers were connected to
                for network_name in network_names:
                    try:
                        network = self.docker.networks.get(network_name)
                        if len(network.containers) == 0:
                            self.network_pool.remove_network(network)
                            print('Removed untracked network: ' + network_name)
                    except:
                        pass

            except:
                traceback.print_exc()

            time.sleep(self.untracked_check_time)

    @classmethod
    def full_tag(cls, tag):
        return tag + ':latest' if ':' not in tag else tag


# ===========================================================================
if __name__ == '__main__':
    pass
    #shep = Shepherd(StrictRedis('redis://redis/3'))
    #res = shep.request_flock('test', {'foo': 'bar'})

    #print(res['reqid'])



