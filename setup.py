from setuptools import setup, find_packages
import sys
import platform


setup(
    name="schedulomicon",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "numpy",
        "pandas",
        "pyyaml",
        "pyparsing",
        "ortools==9.8.3296",
    ],
    description="Constraint-based scheduling optimization",
    author="Justin R. Porter",
    python_requires=">=3.6, <3.11",  # to match available OR-Tools wheels
    entry_points={
        "console_scripts": [
            "schedulomicon=schedulomicon.solver:main",
        ],
    },
)
