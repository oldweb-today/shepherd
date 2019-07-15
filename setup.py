#!/usr/bin/env python
# vim: set sw=4 et:

from setuptools import setup, find_packages
from setuptools.command.test import test as TestCommand
import glob

from shepherd import __version__

def load_requirements(filename):
    with open(filename, 'rt') as fh:
        requirements = fh.read().rstrip().split('\n')
    return requirements



class PyTest(TestCommand):
    def finalize_options(self):
        TestCommand.finalize_options(self)
        # should work with setuptools <18, 18 18.5
        self.test_suite = ' '

    def run_tests(self):
        import pytest
        import sys
        import os
        errcode = pytest.main(['--doctest-modules', './shepherd', '--cov', 'shepherd', '-v', 'test/'])
        sys.exit(errcode)




setup(
    name='shepherd',
    version=__version__,
    author='Ilya Kreymer',
    author_email='ikreymer@gmail.com',
    license='Apache 2.0',
    packages=find_packages(exclude=['test']),
    package_data = {'shepherd': ['static_base/*.*',
                                 'templates/*',
                                 '*.yaml']},
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    provides=[
        'shepherd',
        ],
    install_requires=load_requirements('requirements.txt'),
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
        'fakeredis<1.0',
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
