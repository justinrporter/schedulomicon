# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information
import os
import sys
sys.path.insert(0, os.path.abspath('..'))

project = 'Schedulomicon'
copyright = '2025, Justin R. Porter, Jessica E. Hawkins, Daniel Saddawi-Konefka'
author = 'Justin R. Porter, Jessica E. Hawkins, Daniel Saddawi-Konefka'
release = '0.1.0'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = extensions = [
    'sphinx.ext.autodoc',  # For automatic documentation from docstrings
    'sphinx.ext.viewcode',  # Add links to source code
    'sphinx.ext.napoleon',  # Support for NumPy and Google style docstrings
    'sphinx_autodoc_typehints'  # Use type hints for documentation
]

templates_path = ['_templates']
exclude_patterns = []


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_rtd_theme'  # ReadTheDocs theme
html_static_path = ['_static']
