CLI Reference
=============

The ``schedulomicon`` command-line tool reads a YAML config, applies constraints and
scoring, runs the CP-SAT solver, and writes the resulting schedule to a CSV file.

Basic Invocation
----------------

.. code-block:: bash

   schedulomicon --config config.yml --results results.csv

``--config`` and ``--results`` are the only required flags. All other flags are
optional.

.. _cli-coverage-csv:

Coverage CSV Flags
------------------

``--coverage-min <file>``
^^^^^^^^^^^^^^^^^^^^^^^^^

Load per-block, per-rotation **minimum** coverage bounds from a CSV file.
Constraints are applied on top of (or instead of) ``coverage:`` entries in the YAML.

``--coverage-max <file>``
^^^^^^^^^^^^^^^^^^^^^^^^^

Load per-block, per-rotation **maximum** coverage bounds from a CSV file.
Both flags can be supplied simultaneously to provide independent min and max files.

CSV format
""""""""""

- **Row index** — rotation names, one per row. Must exactly match rotation names in the YAML config.
- **Column headers** — block names, one per column. Must exactly match block names in the YAML config.
- **Cell values** — a non-negative integer: the number of residents who must be assigned to that rotation during that block. For ``--coverage-min`` this becomes a lower bound; for ``--coverage-max`` an upper bound.
- **Empty / NaN cells** — skipped; only non-empty cells generate constraints. You do not need to provide a full matrix.
- **Lines starting with** ``#`` — ignored (use for comments).

Example — a 2×13 grid where TICU requires 2 residents in blocks 1A and 4A, 1 in most others, and 0 in block 8A and 13A:

.. code-block:: text

   ,1A,2A,3A,4A,5A,6A,7A,8A,9A,10A,11A,12A,13A
   TICU,2,1,1,2,1,1,1,0,1,1,1,1,0
   MICU,1,1,2,1,1,2,1,1,2,1,1,2,1

The file has **rotations as rows** and **blocks as columns**. There is no requirement that every rotation or block appear in the file — omitted rows and columns generate no constraints for those rotations or blocks.

This format is convenient when coverage data lives in a spreadsheet maintained
outside the YAML (for example, a department-supplied staffing grid). You can
leave cells blank for rotations or blocks where no constraint is needed.

.. seealso::

   :doc:`constraints` — the ``RotationCoverageConstraint`` section documents the
   equivalent per-block inline syntax using nested lists inside the ``coverage:`` key.

Preference / Scoring Flags
--------------------------

See :doc:`scoring` for full detail on how scores are combined and minimized.

``--rankings <file>``
^^^^^^^^^^^^^^^^^^^^^

Per-rotation, per-resident preference scores applied uniformly across all blocks.
CSV format: rotations as rows, residents as columns.

``--block-resident-ranking <ROTATION> <file>``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Block-specific score adjustments for one rotation.
CSV format: residents as rows, blocks as columns.
This flag can be repeated for multiple rotations.

``--score-list <GRID> <file>``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Arbitrary ``(key1, key2, key3, score)`` CSV applied to the named grid
(``main``, ``vacation``, or ``backup``). This flag can be repeated.

Output Flags
------------

``--results <file>``
^^^^^^^^^^^^^^^^^^^^

**Required.** Path where the solution schedule is written as a CSV.

``--vacation <file>``
^^^^^^^^^^^^^^^^^^^^^

Write vacation assignments to the specified file. Produces an error if the config
does not contain a ``vacation:`` section.

``--dump-model <file>``
^^^^^^^^^^^^^^^^^^^^^^^

Write the OR-Tools CP-SAT model to a file immediately before solving. Useful for
debugging — the model file can be inspected or replayed outside of schedulomicon.

Solver Control Flags
--------------------

``-p`` / ``--n_processes <N>``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Number of OR-Tools search workers (default: ``1``). Increasing this can speed up
solving on multi-core machines.

``-n`` / ``--n_solutions <N>``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Number of solutions to find before stopping. By default the solver runs until it
finds an optimal solution (or proves infeasibility).

``--objective <name>``
^^^^^^^^^^^^^^^^^^^^^^

Objective function name (default: ``rank_sum_objective``).

``--min-individual-rank <N>``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Add a hard constraint requiring every resident's individual score to be at most *N*.
Requires ``--rankings`` to be provided so that individual scores are defined.

``--hint <file>``
^^^^^^^^^^^^^^^^^

Warm-start the solver from a prior solution CSV. The hint is fed to OR-Tools as a
starting point; it does not restrict the search space.
