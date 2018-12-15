## Shepherd

Shepherd provides a system for configuring and launching clusters (or flocks) of Docker containers.

Feature include:
 - YAML definition of each "flock" including environment, volumes, external networks.
 - API and HTTP API for starting, stopping, pausing and resuming instances of each flock.
 - User overrides, including environment variables and 'descendant' images
 - Multiple pools for managing running flocks/
 - Queuing with fixed pool size and queing (fixed size pool)
 - Persistent pool for time-slicing flock execution.
 
### Comparison to Docker Compose

The flock format is inspired by compose and supports a limited subset of compose spec.
Unlike with Compose, which runs a single docker-compose.yml at a time,
the intent of Shepherd is to manage multiple instances of each available flock,
and to schedule their execution. Each instance is given a unique id which can be used to refer
to the instance.

### Use Cases and Test Suite

This library does not include any specific flocks and is designed to be as generic as possible.

It only uses very small public Docker containers for the test suite, which can be run via:
`python setup.py test` after installing with `python setup.py install`

For an example implementation that uses Shepherd and additional flock definitions, see https://github.com/oldweb-today/browser-shepherd

### Other dependencies

Besides Docker, Shepherd relies on Redis to store internal state (though can be used with an in-memory 'fake' redis as well).
