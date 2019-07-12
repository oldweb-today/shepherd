import gevent
import traceback

from shepherd.flock import FlockRequest
from shepherd.network_pool import CachedNetworkPool

import logging

logger = logging.getLogger('shepherd.pool')


# ============================================================================
class LaunchAllPool(object):
    TYPE = 'all'

    POOL_NAME_LABEL = 'owt.shepherd.pool'
    POOL_KEY = 'p:{id}:i'

    POOL_FLOCKS = 'p:{id}:f'

    POOL_REQ = 'p:{id}:rq:'

    POOL_NETWORK_TEMPL = 'shepherd-net:%s:{0}'

    REQ_TO_POOL = 'reqp:'

    REQ_KEY = 'req:'

    DEFAULT_DURATION = 3600

    EXPIRE_CHECK = 30

    def __init__(self, name, shepherd, redis, duration=None, expire_check=None,
                 network_pool_size=0, **kwargs):
        self.name = name
        self.shepherd = shepherd
        self.redis = redis

        self.duration = int(duration or self.DEFAULT_DURATION)
        self.expire_check = expire_check or self.EXPIRE_CHECK

        self.labels = {self.POOL_NAME_LABEL: self.name}

        self.pool_key = self.POOL_KEY.format(id=self.name)
        self.flocks_key = self.POOL_FLOCKS.format(id=self.name)

        self.req_key = self.POOL_REQ.format(id=self.name)

        self.api = shepherd.docker.api

        self.network_pool = None

        if network_pool_size > 0:
            self.network_pool = CachedNetworkPool(shepherd.docker,
                                                  redis=self.redis,
                                                  network_templ=self.POOL_NETWORK_TEMPL % self.name,
                                                  network_label=shepherd.network_pool.network_label,
                                                  max_size=network_pool_size)

        self.running = True

        gevent.spawn(self.event_loop)

        gevent.spawn(self.expire_loop)

    def request(self, flock_name, req_opts):
        res = self.shepherd.request_flock(flock_name, req_opts)

        if 'reqid' in res:
            self.redis.set(self.REQ_TO_POOL + res['reqid'], self.name,
                           ex=self.shepherd.DEFAULT_REQ_TTL)

        return res

    def _mark_wait_duration(self, reqid, value=1):
        self.redis.set(self.req_key + reqid, value, ex=self.duration)
        self.redis.set(self.REQ_TO_POOL + reqid, self.name)

    def _mark_expired(self, reqid):
        logger.debug('Mark Expired: ' + reqid)
        self.redis.delete(self.req_key + reqid)

    def start_deferred_container(self, reqid, image_name):
        return self.shepherd.start_deferred_container(reqid=reqid,
                                                      image_name=image_name,
                                                      labels=self.labels)

    def start(self, reqid, **kwargs):
        res = self.shepherd.start_flock(reqid,
                                        labels=self.labels,
                                        network_pool=self.network_pool,
                                        **kwargs)

        if 'error' not in res:
            self.add_running(reqid)

            self._mark_wait_duration(reqid)


        return res

    def remove(self, reqid, **kwargs):
        res = self.shepherd.remove_flock(reqid,
                                         network_pool=self.network_pool,
                                         **kwargs)

        if 'error' not in res:
            self.remove_running(reqid)

            self._mark_expired(reqid)

            #self.redis.expire(self.REQ_TO_POOL + reqid, self.duration)
            self.redis.delete(self.REQ_TO_POOL + reqid)

        return res

    def stop(self, reqid):
        logger.info('Expired: ' + reqid)
        return self.remove(reqid)

    def add_running(self, reqid):
        return self.redis.sadd(self.flocks_key, reqid)

    def is_running(self, reqid):
        return self.redis.sismember(self.flocks_key, reqid)

    def remove_running(self, reqid):
        logger.debug('Stop Running: ' + reqid)
        return self.redis.srem(self.flocks_key, reqid)

    def curr_size(self):
        return self.redis.scard(self.flocks_key)

    def num_avail(self):
        max_size = self.redis.hget(self.pool_key, 'max_size')
        return int(max_size) - self.curr_size()

    def event_loop(self):
        filters = {
                   'label': self.POOL_NAME_LABEL + '=' + self.name,
                   'event': ['die', 'start'],
                   'type': 'container'
                  }

        logger.info('Event Loop Started')

        for event in self.api.events(decode=True,
                                     filters=filters):
            try:
                if not self.running:
                    break

                attrs = event['Actor']['Attributes']
                reqid = attrs[self.shepherd.reqid_label]

                if event['status'] == 'die':
                    self.handle_die_event(reqid, event, attrs)

                elif event['status'] == 'start':
                    self.handle_start_event(reqid, event, attrs)

            except Exception as e:
                logger.warn(e)

    def handle_die_event(self, reqid, event, attrs):
        self._mark_expired(reqid)

    def handle_start_event(self, reqid, event, attrs):
        pass

    def expire_loop(self):
        logger.info('Expire Loop Started')
        while self.running:
            try:
                for reqid in self.redis.smembers(self.flocks_key):
                    key = self.req_key + reqid
                    if not self.redis.exists(key):
                        self.stop(reqid)

                gevent.sleep(self.expire_check)

            except:
                traceback.print_exc()

    def shutdown(self):
        self.running = False

        for reqid in self.redis.smembers(self.flocks_key):
            self.remove(reqid)

        if self.network_pool:
            self.network_pool.shutdown()


# ============================================================================
class FixedSizePool(LaunchAllPool):
    TYPE = 'fixed'

    WAIT_PING_TTL = 10

    MAX_REMOVE_SWEEP = 10

    NEXT = 'next'

    REQID_WAIT = 'p:{id}:r:'

    Q_SET = 'p:{id}:q'

    def __init__(self, *args, **kwargs):
        super(FixedSizePool, self).__init__(*args, **kwargs)

        data = {
                'duration': kwargs['duration'],
                'max_size': kwargs['max_size']
               }

        self.redis.hmset(self.pool_key, data)

        self.reqid_wait = self.REQID_WAIT.format(id=self.name)

        self.q_set = self.Q_SET.format(id=self.name)

        self.wait_ping_ttl = int(kwargs.get('wait_ping_ttl', self.WAIT_PING_TTL))

    def request(self, flock_name, req_opts):
        res = super(FixedSizePool, self).request(flock_name, req_opts)

        if 'reqid' in res:
            self.ensure_queued(res['reqid'])

        return res

    def start(self, reqid, environ=None):
        if self.is_running(reqid):
            return FlockRequest(reqid).load_cached_response(self.redis, required=True)

        pos = self.get_queue_pos(reqid)
        if pos >= 0:
            if environ:
                FlockRequest(reqid).update_env(environ, self.redis, save=True, expire=self.wait_ping_ttl)

            return {'queue': pos}

        res = super(FixedSizePool, self).start(reqid, environ=environ)

        self.remove_queued(reqid)

        return res

    def remove(self, reqid, **kwargs):
        super(FixedSizePool, self).remove(reqid, **kwargs)
        self.remove_queued(reqid)

    def get_queue_pos(self, reqid):
        self.ensure_queued(reqid)
        pos = self.redis.zrank(self.q_set, reqid)
        num_avail = self.num_avail()

        # limit removal to MAX_REMOVE_SWEEP to limit processing
        if pos >= num_avail and pos > 1:
            max_remove = min(self.MAX_REMOVE_SWEEP, pos)
            reqids = self.redis.zrange(self.q_set, 0, max_remove)
            qn_keys = self.redis.mget([self.reqid_wait + rq for rq in reqids])
            rem_keys = [rq for res, rq in zip(qn_keys, reqids)
                        if not res]

            # keys to remove from zset queue
            if rem_keys:
                res = self.redis.zrem(self.q_set, *rem_keys)
                pos = self.redis.zrank(self.q_set, reqid)

        if pos < num_avail:
            return -1

        return pos

    def ensure_queued(self, reqid):
        if not self.redis.get(self.reqid_wait + reqid):
            next_number = self.redis.hincrby(self.pool_key, self.NEXT, 1)
            self.redis.zadd(self.q_set, next_number, reqid)

        self.redis.set(self.reqid_wait + reqid, '1', ex=self.wait_ping_ttl)

        # also extend time of main req:<id> key
        self.redis.expire(self.REQ_KEY + reqid, self.wait_ping_ttl)

    def remove_queued(self, reqid):
        self.redis.zrem(self.q_set, reqid)
        self.redis.delete(self.reqid_wait + reqid)


# ============================================================================
class PersistentPool(LaunchAllPool):
    TYPE = 'persist'

    POOL_WAIT_Q = 'p:{id}:wq'

    POOL_WAIT_SET = 'p:{id}:ws'

    POOL_ALL_SET = 'p:{id}:a'

    def __init__(self, *args, **kwargs):
        super(PersistentPool, self).__init__(*args, **kwargs)

        data = {
                'duration': kwargs['duration'],
                'max_size': kwargs['max_size']
               }

        self.redis.hmset(self.pool_key, data)

        self.pool_wait_q = self.POOL_WAIT_Q.format(id=self.name)

        self.pool_wait_set = self.POOL_WAIT_SET.format(id=self.name)

        self.pool_all_set = self.POOL_ALL_SET.format(id=self.name)

        self.grace_time = int(kwargs.get('grace_time', 0))

    def handle_die_event(self, reqid, event, attrs):
        super(PersistentPool, self).handle_die_event(reqid, event, attrs)

        # if 'clean exit', then stop entire flock, don't reschedule
        if attrs['exitCode'] == '0' and attrs.get(self.shepherd.SHEP_DEFERRED_LABEL) != '1':
            logger.debug('Flock Finished Successfully: ' +  reqid)
            self.remove(reqid, stop=True)

    def start(self, reqid, environ=None):
        if self.is_running(reqid):
            return FlockRequest(reqid).load_cached_response(self.redis, required=True)

        elif self.redis.sismember(self.pool_wait_set, reqid):
            return {'queue': self._find_wait_pos(reqid)}

        self._add_persist(reqid)

        if self.num_avail() == 0:
            if environ:
                FlockRequest(reqid).update_env(environ, self.redis, save=True)

            pos = self._push_wait(reqid)
            return {'queue': pos - 1}

        res = super(PersistentPool, self).start(reqid, environ=environ)

        self.redis.persist(self.REQ_TO_POOL + reqid)

        return res

    def _is_persist(self, reqid):
        return self.redis.sismember(self.pool_all_set, reqid)

    def _add_persist(self, reqid):
        logger.debug('Persist flock: ' + reqid)
        self.redis.persist(self.REQ_KEY + reqid)
        return self.redis.sadd(self.pool_all_set, reqid)

    def _remove_persist(self, reqid):
        logger.debug('Unpersist flock: ' + reqid)
        return self.redis.srem(self.pool_all_set, reqid)

    def _push_wait(self, reqid):
        logger.debug('Adding to Wait Queue: ' + reqid)
        if self.redis.sadd(self.pool_wait_set, reqid):
            res = self.redis.rpush(self.pool_wait_q, reqid)
            logger.debug('Queued at pos: ' + str(res))
            return res
        else:
            logger.debug('Already waiting: ' + reqid)
            return -1

    def _pop_wait(self):
        reqid = self.redis.lpop(self.pool_wait_q)
        if reqid:
            self.redis.srem(self.pool_wait_set, reqid)

        logger.debug('Got Next Flock: ' + str(reqid))
        return reqid

    def _remove_wait(self, reqid):
        self.redis.lrem(self.pool_wait_q, 1, reqid)
        self.redis.srem(self.pool_wait_set, reqid)
        logger.debug('Remove from wait queue: ' + reqid)

    def _find_wait_pos(self, reqid):
        pool_list = self.redis.lrange(self.pool_wait_q, 0, -1)
        try:
            return pool_list.index(reqid)
        except:
            return -1

    def stop(self, reqid):
        logger.info('Stopping: ' + reqid)
        next_reqid = self._pop_wait()

        #if no next key, extend this for same duration
        if next_reqid is None and (self.num_avail() >= 0):
            if not self._is_persist(reqid):
                self.remove_running(reqid)

            elif self.is_running(reqid):
                logger.debug('Continue Running: ' + reqid)
                self._mark_wait_duration(reqid)

            return {'success': True}

        else:
            self.remove_running(reqid)

            self._mark_expired(reqid)

            logger.debug('Removing Flock: {0} with Grace Time {1}'.format(reqid, self.grace_time))
            rem_res = self.shepherd.remove_flock(reqid,
                                                 network_pool=self.network_pool,
                                                 keep_reqid=True,
                                                 grace_time=self.grace_time)

            if 'error' not in rem_res and self._is_persist(reqid):
                self._push_wait(reqid)

            if 'error' in  rem_res:
                logger.debug('Error: ' +  str(rem_res))

            self.restart(next_reqid)

            return rem_res

    def restart(self, reqid):
        res = None
        while reqid:
            try:
                logger.debug('Restarting')
                assert self._is_persist(reqid)

                res = self.shepherd.start_flock(reqid,
                                                labels=self.labels,
                                                network_pool=self.network_pool)

                assert 'error' not in res, res

                self.add_running(reqid)

                self._mark_wait_duration(reqid)
                break

            except Exception as e:
                traceback.print_exc()
                self.remove_running(reqid)
                reqid = self._pop_wait()

        return res

    def remove(self, reqid, **kwargs):
        self._remove_persist(reqid)

        num_removed = self.remove_running(reqid)

        self._mark_expired(reqid)

        # remove from wait list always just in case
        self._remove_wait(reqid)

        # stop or remove
        if kwargs.get('stop'):
            res = self.shepherd.stop_flock(reqid)
        else:
            res = super(PersistentPool, self).remove(reqid, grace_time=self.grace_time)

        # only attempt to restart next if was currently running
        # and stopping succeeded
        if num_removed and 'error' not in res and not kwargs.get('no_replace'):
            self.restart(self._pop_wait())

        return res


# ============================================================================
def get_pool_types():
    return [LaunchAllPool, FixedSizePool, PersistentPool]


# ============================================================================
def create_pool(shepherd, redis, pool_data):
    all_pool_cls = get_pool_types()

    the_cls = None

    for pool_cls in all_pool_cls:
        if pool_cls.TYPE == pool_data['type']:
            the_cls = pool_cls
            break

    if not the_cls:
        raise Exception('Unknown Pool for Type: ' + pool_data['type'])

    name = pool_data.pop('name')
    return the_cls(name, shepherd, redis, **pool_data)


