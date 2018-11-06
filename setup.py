#!/usr/bin/env python
# vim: set sw=4 et:

from setuptools import setup, find_packages
from setuptools.command.test import test as TestCommand
import glob

from shepherd import __version__

class PyTest(TestCommand):
    def finalize_options(self):
        TestCommand.finalize_options(self)
        # should work with setuptools <18, 18 18.5
        self.test_suite = ' '

    def run_tests(self):
        import pytest
        import sys
        import os
        errcode = pytest.main(['--doctest-module', './shepherd', '--cov', 'shepherd', '-v', 'test/'])
        sys.exit(errcode)




setup(
    name='shepherd',
    version=__version__,
    author='Ilya Kreymer',
    author_email='ikreymer@gmail.com',
    license='Apache 2.0',
    packages=find_packages(exclude=['test']),
    #long_description=open('README.rst').read(),
    provides=[
        'shepherd',
        ],
    install_requires=[
        'six',
        'docker',
        'marshmallow>=3.0.0b',
        'redis',
        'apispec<1.0',
        'flask',
        'gevent',
        'pyyaml',
        ],
    zip_safe=True,
    entry_points="""
        [console_scripts]
    """,
    cmdclass={'test': PyTest},
    test_suite='',
    tests_require=[
        'pytest',
        'pytest-cov',
        'pytest-flask',
        'fakeredis',
    ],
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Web Environment',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: Utilities',
    ]
)
