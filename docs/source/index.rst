.. Schedulomicon documentation master file

Welcome to Schedulomicon's documentation!
=========================================

Schedulomicon is a constraint-based scheduling system designed for medical resident rotation assignments.
It uses Google OR-Tools CP-SAT solver to optimize schedules while respecting complex constraints such as
rotation coverage, resident preferences, and vacation requests.

A good starting point is the `examples/ folder on GitHub <https://github.com/justinrporter/schedulomicon/tree/main/examples>`_,
which contains annotated YAML configs covering a standard rotation schedule (``example_config.yml``) and
a more advanced shift-schedule scenario (``ob_example.yml``).

.. toctree::
   :maxdepth: 1
   :caption: Contents:

   configuration_files
   selections
   constraints
   scoring
   api_usage
   API Reference <schedulomicon>



Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
