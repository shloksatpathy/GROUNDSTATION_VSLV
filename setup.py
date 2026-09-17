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
    # The modules use flat imports (`from core.config import ...`), so
    # application/ is the package root rather than a package itself.
    package_dir={"": "application"},
    packages=find_packages(where="application"),
    py_modules=["main"],
    install_requires=requirements,
    entry_points={
        'gui_scripts': [
            'ground-station=main:main',
        ],
    },
    include_package_data=True,
    data_files=[
        ('share/vsssic-ground-station/config',
         ['config/config.json', 'config/packet_format.json']),
        ('share/vsssic-ground-station/images',
         ['images/vsssic-logo-1.ico']),
    ],
    python_requires='>=3.8',
)
