from shepherd.shepherd import Shepherd
import pytest
import fakeredis
import os
import docker
import glob


NETWORKS_NAME = 'test-shepherd.net:{0}'

TEST_DIR = os.path.join(os.path.dirname(__file__), 'data')

TEST_FLOCKS = os.path.join(TEST_DIR, 'test_flocks.yaml')


@pytest.fixture(scope='module')
def redis():
    return fakeredis.FakeStrictRedis(db=2, decode_responses=True)


@pytest.fixture(scope='module')
def shepherd(redis):
    shep = Shepherd(redis, NETWORKS_NAME)
    shep.load_flocks(TEST_FLOCKS)
    return shep


@pytest.fixture(scope='session')
def docker_client():
    docker_cli = docker.from_env()

    for filename in glob.glob(os.path.join(TEST_DIR, 'Dockerfile.*')):
        path, dockerfile = os.path.split(filename)
        name = dockerfile.rsplit('.', 1)[1]
        docker_cli.images.build(path=path,
                                   dockerfile=dockerfile,
                                   tag='test-shepherd/' + name,
                                   rm=True)

    yield docker_cli

    for image in docker_cli.images.list('test-shepherd/*'):
        docker_cli.images.remove(image.tags[0], force=True)




