"""Setup configuration for Abhaile package."""

from setuptools import setup, find_packages

setup(
    name="abhaile",
    version="0.1.0",
    package_dir={"": "src"},
    packages=find_packages(where="src", include=["abhaile*"]),
    python_requires=">=3.10",
    install_requires=[
        "PyYAML>=6.0",
        "Jinja2>=3.0",
        "jsonschema>=4.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.4.0",
            "pre-commit>=3.5.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "abhaile-render=abhaile.cli:main",
        ],
    },
)
