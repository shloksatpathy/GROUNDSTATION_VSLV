#!/usr/bin/env python3
"""
Setup configuration for VSSSIC Ground Station V3
"""
from setuptools import setup, find_packages

with open("requirements.txt") as f:
    requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]

setup(
    name="VSSSIC-Ground-Station",
    version="3.0.0",
    description="Modular Ground Station Application for VSSSIC",
    author="VSSSIC Team",
    packages=find_packages(),
    install_requires=requirements,
    entry_points={
        'console_scripts': [
            'ground-station=application.main:main',
        ],
    },
    include_package_data=True,
    package_data={
        '': ['images/vsssic-logo-1.ico'],
    },
    python_requires='>=3.8',
)
