import gevent
import traceback
from shepherd.network_pool import CachedNetworkPool


# ============================================================================
class LaunchAllPool(object):
    POOL_NAME_LABEL = 'owt.shepherd.pool'
    POOL_KEY = 'p:{id}:i'

    POOL_FLOCKS = 'p:{id}:f'

    POOL_REQ = 'p:{id}:rq:'

    POOL_NETWORK_TEMPL = 'shepherd-net:%s:{0}'

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
                                                  max_size=network_pool_size)

        self.running = True

        gevent.spawn(self.event_loop)

        gevent.spawn(self.expire_loop)

    def request(self, flock_name, req_opts):
        return self.shepherd.request_flock(flock_name, req_opts)

    def _mark_wait_duration(self, reqid, value=1):
        self.redis.set(self.req_key + reqid, value, ex=self.duration)

    def _mark_stopped(self, reqid):
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

    def stop(self, reqid, **kwargs):
        res = self.shepherd.stop_flock(reqid,
                                       network_pool=self.network_pool,
                                       **kwargs)

        if 'error' not in res:
            self.remove_running(reqid)

            self._mark_stopped(reqid)

        return res

    def pause(self, reqid):
        return self.stop(reqid)

    def add_running(self, reqid):
        return self.redis.sadd(self.flocks_key, reqid)

    def is_running(self, reqid):
        return self.redis.sismember(self.flocks_key, reqid)

    def remove_running(self, reqid):
        return self.redis.srem(self.flocks_key, reqid)

    def curr_size(self):
        return self.redis.scard(self.flocks_key)

    def event_loop(self):
        filters = {
                   'label': self.POOL_NAME_LABEL + '=' + self.name,
                   'event': ['die', 'start'],
                   'type': 'container'
                  }

        print('Event Loop Started')

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
                print(e)

    def handle_die_event(self, reqid, event, attrs):
        self._mark_stopped(reqid)

    def handle_start_event(self, reqid, event, attrs):
        pass

    def expire_loop(self):
        print('Expire Loop Started')
        while self.running:
            for reqid in self.redis.smembers(self.flocks_key):
                key = self.req_key + reqid
                if not self.redis.exists(key):
                    print('Expired: ' + reqid)
                    self.pause(reqid)

            gevent.sleep(self.expire_check)

    def shutdown(self):
        self.running = False

        for reqid in self.redis.smembers(self.flocks_key):
            self.stop(reqid)

        if self.network_pool:
            self.network_pool.shutdown()


# ============================================================================
class FixedSizePool(LaunchAllPool):
    WAIT_PING_TTL = 10

    MAX_REMOVE_SWEEP = 10

    NEXT = 'next'

    REQID_WAIT = 'p:{id}:r:'

    REQ_KEY = 'req:'

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
            return super(FixedSizePool, self).start(reqid, environ=environ)

        pos = self.get_queue_pos(reqid)
        if pos >= 0:
            return {'queue': pos}

        res = super(FixedSizePool, self).start(reqid, environ=environ)

        self.remove_queued(reqid)

        return res

    def stop(self, reqid, **kwargs):
        super(FixedSizePool, self).stop(reqid, **kwargs)
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

    def num_avail(self):
        max_size = self.redis.hget(self.pool_key, 'max_size')
        return int(max_size) - self.curr_size()

    def ensure_queued(self, reqid):
        if not self.redis.get(self.reqid_wait + reqid):
            next_number = self.redis.hincrby(self.pool_key, self.NEXT, 1)
            self.redis.zadd(self.q_set, {reqid: next_number})

        self.redis.set(self.reqid_wait + reqid, '1', ex=self.wait_ping_ttl)

        # also extend time of main req:<id> key
        self.redis.expire(self.REQ_KEY + reqid, self.wait_ping_ttl)

    def remove_queued(self, reqid):
        self.redis.zrem(self.q_set, reqid)
        self.redis.delete(self.reqid_wait + reqid)


# ============================================================================
class PersistentPool(LaunchAllPool):
    POOL_WAIT_Q = 'p:{id}:q'

    POOL_WAIT_SET = 'p:{id}:s'

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

        self.stop_on_pause = kwargs.get('stop_on_pause', False)

    def handle_die_event(self, reqid, event, attrs):
        super(PersistentPool, self).handle_die_event(reqid, event, attrs)

        # if 'clean exit', then stop entire flock, don't reschedule
        if attrs['exitCode'] == '0' and attrs.get(self.shepherd.SHEP_DEFERRED_LABEL) != '1':
            #print('Persistent Flock Fully Finished: ' + reqid)
            self.stop(reqid)

    def num_avail(self):
        max_size = self.redis.hget(self.pool_key, 'max_size')
        return int(max_size) - self.curr_size()

    def start(self, reqid, environ=None):
        if self.is_running(reqid):
            return super(PersistentPool, self).start(reqid, environ=environ,
                                                     pausable=self.stop_on_pause)

        elif self.redis.sismember(self.pool_wait_set, reqid):
            return {'queue': self._find_wait_pos(reqid)}

        self._add_persist(reqid)

        if self.num_avail() == 0:
            pos = self._push_wait(reqid)
            return {'queue': pos - 1}

        return super(PersistentPool, self).start(reqid, environ=environ,
                                                 pausable=self.stop_on_pause)

    def _is_persist(self, reqid):
        return self.redis.sismember(self.pool_all_set, reqid)

    def _add_persist(self, reqid):
        return self.redis.sadd(self.pool_all_set, reqid)

    def _remove_persist(self, reqid):
        return self.redis.srem(self.pool_all_set, reqid)

    def _push_wait(self, reqid):
        self.redis.sadd(self.pool_wait_set, reqid)
        return self.redis.rpush(self.pool_wait_q, reqid)

    def _pop_wait(self):
        reqid = self.redis.lpop(self.pool_wait_q)
        if reqid:
            self.redis.srem(self.pool_wait_set, reqid)

        return reqid

    def _remove_wait(self, reqid):
        self.redis.lrem(self.pool_wait_q, 1, reqid)
        self.redis.srem(self.pool_wait_set, reqid)

    def _find_wait_pos(self, reqid):
        pool_list = self.redis.lrange(self.pool_wait_q, 0, -1)
        try:
            return pool_list.index(reqid)
        except:
            return -1

    def pause(self, reqid):
        next_reqid = self._pop_wait()

        #if no next key, extend this for same duration
        if next_reqid is None:
            if not self._is_persist(reqid):
                self.remove_running(reqid)

            elif self.is_running(reqid):
                self._mark_wait_duration(reqid)

            return {'success': True}

        else:
            self.remove_running(reqid)

            self._mark_stopped(reqid)

            if not self.stop_on_pause:
                pause_res = self.shepherd.stop_flock(reqid,
                                                     network_pool=self.network_pool,
                                                     keep_reqid=True,
                                                     grace_time=self.grace_time)
            else:
                pause_res = self.shepherd.pause_flock(reqid,
                                                      grace_time=self.grace_time)

            if 'error' not in pause_res and self._is_persist(reqid):
                self._push_wait(reqid)

            self.resume(next_reqid)

            return pause_res

    def resume(self, reqid):
        res = None
        while reqid:
            try:
                assert self._is_persist(reqid)

                if not self.stop_on_pause:
                    res = self.shepherd.start_flock(reqid,
                                                    labels=self.labels,
                                                    network_pool=self.network_pool)

                else:
                    res = self.shepherd.resume_flock(reqid)

                    if res.get('error') == 'not_paused' and res.get('state') == 'new':
                        res = self.shepherd.start_flock(reqid,
                                                        labels=self.labels,
                                                        network_pool=self.network_pool,
                                                        pausable=True)

                assert 'error' not in res

                self.add_running(reqid)

                self._mark_wait_duration(reqid)
                break

            except Exception as e:
                traceback.print_exc()
                self.remove_running(reqid)
                reqid = self._pop_wait()

        return res

    def stop(self, reqid, **kwargs):
        self._remove_persist(reqid)

        removed_res = self.remove_running(reqid)

        # remove from wait list always just in case
        self._remove_wait(reqid)

        # stop
        stop_res = super(PersistentPool, self).stop(reqid, grace_time=self.grace_time)

        # only attempt to resume next if was currently running
        # and stopping succeeded
        if removed_res and 'error' not in stop_res and not kwargs.get('no_replace'):
            self.resume(self._pop_wait())

        return stop_res
