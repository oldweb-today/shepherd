import gevent


# ============================================================================
class LaunchAllPool(object):
    POOL_NAME_LABEL = 'owt.shepherd.pool'
    POOL_KEY = 'p:{id}:i'

    POOL_FLOCKS = 'p:{id}:f'

    POOL_REQ = 'p:{id}:rq:'

    DEFAULT_DURATION = 3600

    EXPIRE_CHECK = 30

    def __init__(self, name, shepherd, redis, duration=None, expire_check=None, **kwargs):
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

        self.running = True

        gevent.spawn(self.event_loop)

        gevent.spawn(self.expire_loop)

    def request(self, flock_name, req_opts):
        return self.shepherd.request_flock(flock_name, req_opts)

    def start(self, reqid, environ=None, value=1):
        res = self.shepherd.start_flock(reqid, labels=self.labels,
                                        environ=environ)
        if 'error' not in res:
            self.redis.sadd(self.flocks_key, reqid)

            self.redis.set(self.req_key + reqid, value, ex=self.duration)

        return res

    def stop(self, reqid):
        res = self.shepherd.stop_flock(reqid)

        if 'error' not in res:
            self.redis.srem(self.flocks_key, reqid)

            self.redis.delete(self.req_key + reqid)

        return res

    def is_active(self, reqid):
        return self.redis.sismember(self.flocks_key, reqid)

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

                reqid = event['Actor']['Attributes'][self.shepherd.SHEP_REQID_LABEL]
                if event['status'] == 'die':
                    self.handle_die_event(reqid, event)

                elif event['status'] == 'start':
                    self.handle_start_event(reqid, event)

            except Exception as e:
                print(e)

    def handle_die_event(self, reqid, event):
        key = self.req_key + reqid
        self.redis.delete(key)

    def handle_start_event(self, reqid, event):
        pass

    def expire_loop(self):
        print('Expire Loop Started')
        while self.running:
            for reqid in self.redis.smembers(self.flocks_key):
                key = self.req_key + reqid
                if not self.redis.exists(key):
                    print('Stopping: ' + reqid)
                    self.stop(reqid)

            gevent.sleep(self.expire_check)

    def shutdown(self):
        self.running = False

        for reqid in self.redis.smembers(self.flocks_key):
            self.stop(reqid)


# ============================================================================
class FixedSizePool(LaunchAllPool):
    POOL_SLOT = 'p:{id}:s:'

    NOW_SERVING = 'now_serving'

    NUMBER_TTL = 180

    NEXT = 'next'

    REQID_TO_NUMBER = 'p:{id}:r2n:'

    NUMBER_TO_REQID = 'p:{id}:n2r:'

    def __init__(self, *args, **kwargs):
        super(FixedSizePool, self).__init__(*args, **kwargs)

        data = {
                'duration': kwargs['duration'],
                'max_size': kwargs['max_size']
               }

        self.redis.hmset(self.pool_key, data)

        #self.redis.hsetnx(self.pool_key, self.NOW_SERVING, '1')

        self.slot_prefix = self.POOL_SLOT.format(id=self.name)

        self.reqid_to_number = self.REQID_TO_NUMBER.format(id=self.name)
        self.number_to_reqid = self.NUMBER_TO_REQID.format(id=self.name)

        self.number_ttl = kwargs.get('number_ttl', self.NUMBER_TTL)

    def request(self, flock_name, req_opts):
        res = super(FixedSizePool, self).request(flock_name, req_opts)

        if 'reqid' in res:
            number = self.get_number(res['reqid'])

        return res

    def start(self, reqid, environ=None):
        if self.is_active(reqid):
            return super(FixedSizePool, self).start(reqid, environ=environ)

        pos = self.get_queue_pos(reqid)
        if pos >= 0:
            return {'queued': pos}

        res = super(FixedSizePool, self).start(reqid, environ=environ)

        if 'error' in res:
            self.remove_request(reqid)

        return res

    def get_queue_pos(self, reqid):
        number = self.get_number(reqid)
        now_serving = int(self.redis.hget(self.pool_key, self.NOW_SERVING) or 1)

        #print('NUMBER', number)
        #print('NOW_SERVING', now_serving)

        # if missed our number, get new one
        if number < now_serving:
            number = self.get_number(reqid, force_new=True)

        else:
            now_serving = self.incr_now_serving(now_serving, number)

        # pos in the queue
        pos = number - now_serving

        if pos < self.num_avail():
            self.remove_request(reqid, number)
            if pos == 0:
                max_number = int(self.redis.hget(self.pool_key, self.NEXT))
                self.incr_now_serving(now_serving, max_number)

            return -1

        return pos

    def num_avail(self):
        max_size = self.redis.hget(self.pool_key, 'max_size')
        return int(max_size) - self.curr_size()

    def incr_now_serving(self, now_serving, number):
        # if not serving current number, check any expired numbers
        while now_serving < number:
            # if not expired, stop there
            if self.redis.get(self.number_to_reqid + str(now_serving)) is not None:
                break

            now_serving = self.redis.hincrby(self.pool_key, self.NOW_SERVING, 1)

        return now_serving

    def get_number(self, reqid, force_new=False):
        number = None

        if not force_new:
            number = self.redis.get(self.reqid_to_number + reqid)

        if number is None:
            number = self.redis.hincrby(self.pool_key, self.NEXT, 1)
        else:
            number = int(number)

        self.redis.set(self.reqid_to_number + reqid, str(number), ex=self.number_ttl)
        self.redis.set(self.number_to_reqid + str(number), reqid, ex=self.number_ttl)
        return number

    def remove_request(self, reqid, number=None):
        if number is None:
            number = self.redis.get(self.reqid_to_number + reqid)

        self.redis.delete(self.reqid_to_number + reqid)

        if number is not None:
            self.redis.delete(self.number_to_reqid + str(number))

    def find_free(self, reqid):  #pragma: no cover
        found = None
        for slot in range(self.size):
            key = self.slot_prefix + str(slot)
            if self.redis.set(key, '1', nx=True, ex=self.duration):
                found = slot
                break

        if found:
            return
