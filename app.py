from gevent.monkey import patch_all; patch_all()

import logging
from redis import StrictRedis
from shepherd.shepherd import Shepherd
import os

from shepherd.wsgi import create_app

NETWORK_NAME = 'shep-browsers:{0}'
FLOCKS = 'flocks'

CONFIG_FILE = os.environ.get('CONFIG_FILE', 'config.yaml')

REDIS_URL = os.environ.get('REDIS_BROWSER_URL', 'redis://redis/0')


# ============================================================================
def main():
    logging.basicConfig(format='%(asctime)s: [%(levelname)s]: %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S',
                        level=logging.INFO)

    logging.getLogger('shepherd').setLevel(logging.DEBUG)
    logging.getLogger('shepherd.pool').setLevel(logging.DEBUG)

    redis = StrictRedis.from_url(REDIS_URL, decode_responses=True)

    shepherd = Shepherd(redis, NETWORK_NAME)
    shepherd.load_flocks(FLOCKS)

    return create_app(shepherd,  CONFIG_FILE)


application = main()


# ============================================================================
if __name__ == '__main__':
    from gevent.pywsgi import WSGIServer
    WSGIServer(('0.0.0.0', 9020), application).serve_forever()


