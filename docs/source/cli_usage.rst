CLI Reference
=============

The ``schedulomicon`` command-line tool reads a YAML config, applies constraints and
scoring, runs the CP-SAT solver, and writes the resulting schedule. It has two
subcommands:

- ``schedulomicon solve`` — build a schedule from scratch.
- ``schedulomicon swap`` — re-solve an existing schedule under new
  requirements, changing as little as possible (see :ref:`cli-swap-mode`).

Basic Invocation
----------------

.. code-block:: bash

   schedulomicon solve --config config.yml --results results.csv

``--config`` and ``--results`` are the only required flags on ``solve``. All
other flags are optional. Both subcommands accept the same common flags;
``swap`` additionally requires ``--minimize-changes-from``.

.. note::

   Invoking ``schedulomicon`` with flags but no subcommand
   (``schedulomicon --config ...``) is deprecated. It still runs ``solve``,
   printing a deprecation warning to stderr.

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

**Required.** Path where the solution is written. The output format is chosen
by file extension:

- ``.csv`` — human-readable table (blocks × residents; backup assignments are
  marked with a ``+`` suffix). Vacation assignments are not included.
- ``.pkl`` / ``.pickle`` — pickled solution dict, complete but not
  human-readable.
- ``.json`` — sparse machine-readable format containing every grid
  (including the ``vacation`` and ``backup`` cogrids). Accepted by
  ``--hint``.

Any other extension raises an error.

JSON solution format
""""""""""""""""""""

The JSON format is versioned (``format_version: 1``) and sparse: only nonzero
variables are written, and a variable omitted from the file is ``0``. Each
grid records its key field names, the ordered values of each dimension, and
one row per nonzero variable (the key components followed by the value):

.. code-block:: json

    {
      "format_version": 1,
      "grids": {
        "main": {
          "key_fields": ["resident", "block", "rotation"],
          "dimensions": {
            "resident": ["R1", "R2"],
            "block": ["Block 1", "Block 2"],
            "rotation": ["ICU", "Ortho"]
          },
          "variables": [
            ["R1", "Block 1", "ICU", 1],
            ["R1", "Block 2", "Ortho", 1]
          ]
        },
        "backup":   {"key_fields": ["resident", "block"]},
        "vacation": {"key_fields": ["resident", "week", "rotation"]}
      }
    }

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

``-n`` / ``--n_solutions <N>`` / ``--n-solutions <N>``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In ``solve`` mode: the number of solutions to find before stopping. By
default the solver runs until it finds an optimal solution (or proves
infeasibility).

In ``swap`` mode: the number of distinct minimal-change proposals to produce
(default ``1``); see :ref:`cli-swap-multiple-proposals`. It does not limit
the solutions visited within a pass.

``--objective <name>``
^^^^^^^^^^^^^^^^^^^^^^

Objective function name (default: ``rank_sum_objective``).

``--min-individual-rank <N>``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Add a hard constraint requiring every resident's individual score to be at most *N*.
Requires ``--rankings`` to be provided so that individual scores are defined.

``--hint <file>``
^^^^^^^^^^^^^^^^^

Warm-start the solver from a prior solution written by ``--results`` as
``.pkl``/``.pickle`` or ``.json`` (CSV is not supported). The hint is fed to
OR-Tools as a starting point; it does not restrict the search space.

Hints may be partial: grids absent from the hint file are simply left
unhinted. Within a hinted grid, variables absent from a sparse ``.json``
solution are hinted as ``0``.

Extra Constraints
-----------------

``--require 'SUM_EXPR: SELECTOR'``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Add a hard constraint from the command line, without editing the YAML config.
Available on both subcommands and repeatable.

The part before the colon is a sum comparison (``sum == N``, ``sum != N``,
``sum > N``, ``sum >= N``, ``sum < N``, ``sum <= N``); the part after is a
selector expression in the same DSL used by YAML ``sum`` keys (see
:doc:`selections`). The selected cells of the **main grid only** are summed
and constrained — cogrid (vacation/backup) variables cannot be selected.

.. code-block:: bash

   # Resident A must do Cardiology in Block 7
   schedulomicon solve ... --require 'sum == 1: Resident A and Block 7 and Cardiology'

   # Resident B must never be assigned ICU; seniors must cover at least
   # two Emergency or Trauma slots
   schedulomicon swap ... \
       --require 'sum == 0: Resident B and ICU' \
       --require 'sum >= 2: Senior and (Emergency or Trauma)'

.. _cli-swap-mode:

Swap Mode
---------

``schedulomicon swap`` takes a published schedule and new requirements and
finds the smallest set of changes that satisfies them — for example when a
resident leaves or a slot must be covered differently after the schedule was
released. It uses the same config pipeline and flags as ``solve``; the new
requirements are typically given with ``--require``.

.. code-block:: bash

   schedulomicon swap \
       --config config.yml \
       --minimize-changes-from old_results.json \
       --require 'sum == 0: Resident A and Block 7 and Cardiology' \
       --results new_results.json

``--minimize-changes-from <file>``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Required.** The prior solution to stay close to, as written by
``--results`` in ``.pkl``/``.pickle`` or ``.json`` format.

``--freeze 'SELECTOR'``
^^^^^^^^^^^^^^^^^^^^^^^

Pin a region of the schedule to the old solution. Change minimization only
*discourages* touching cells outside the new requirements; ``--freeze`` makes
the selected region **identical** to the old solution — the natural choice
for blocks that have already happened in mid-year rescheduling. Repeatable;
each selector becomes a hard constraint applied in both passes. The selector
uses the same DSL as ``--require`` (see :doc:`selections`), so freezing
residents or rotations works the same way as freezing blocks:

.. code-block:: bash

   schedulomicon swap \
       --config config.yml \
       --minimize-changes-from old_results.json \
       --freeze 'Block 1 or Block 2 or Block 3' \
       --require 'sum == 0: Resident A and Block 7 and Cardiology' \
       --results new_results.json

Every selected main-grid cell is pinned to its old value. Cogrid variables
freeze where the selection determines them completely:

- a **backup** ``(resident, block)`` assignment is pinned when the selection
  covers *all* rotations for that pair (e.g. a whole-block freeze);
- a **vacation** ``(resident, week, rotation)`` assignment is pinned when
  *every* block the week maps to is selected for that resident and rotation.
  A week whose config lists no blocks is never frozen.

If the frozen region touches a ``(resident, block)`` pair with no valid
assignment in the old solution — a resident added mid-year, or a pair whose
old rotation was removed or renamed from the config — the command fails
immediately with a ``FreezeError`` rather than silently guessing. The remedy
is to narrow the selector, e.g.
``--freeze '(Block 1 or Block 2) and not New Resident'``. The same hard
error applies when the selection projects onto a backup or vacation grid
that the model has but the old solution file lacks. (Sparse ``.json``
solutions are fine: a missing key in a present grid is a determined ``0``.)

A ``--require`` that contradicts a frozen cell makes the model infeasible;
the solver reports ``INFEASIBLE`` just as with any over-constrained config.

Two-pass semantics
^^^^^^^^^^^^^^^^^^

Swap mode solves lexicographically, in up to two passes:

1. **Pass 1** minimizes the number of changes from the old schedule, subject
   to all constraints (YAML, coverage CSVs, and ``--require``). The old
   solution seeds the search as a solver hint (an explicit ``--hint``
   overrides this).
2. **Pass 2** runs only when a score objective is given (``--rankings`` /
   ``--score-list`` / ``--block-resident-ranking``). It re-solves with the
   pass-1 change count imposed as a hard bound and optimizes the normal
   score objective, so among all minimal-change schedules you get the
   best-scoring one.

.. _cli-swap-multiple-proposals:

Multiple proposals
^^^^^^^^^^^^^^^^^^

``--n-solutions <N>`` asks swap mode for *N* distinct proposals instead of
one. Proposals are produced in **strict lexicographic order**: fewest
variable flips from the old schedule first, and among schedules with equal
flip counts, best score first (when a score objective is given). After each
proposal the exact solution is excluded and the two-pass solve is repeated,
so once every schedule at the minimal flip count has been produced, later
proposals move to the next-larger flip count.

With ``N > 1``, ``--results new.json`` writes numbered files ``new-1.json``,
``new-2.json``, … — each a normal single-solution ``format_version: 1`` file,
so any of them can be fed back to ``--hint`` or ``--minimize-changes-from``.
Each proposal is printed with its own header and diff report. With ``N = 1``
(or the flag omitted) the output is exactly as before: one solution at the
``--results`` path as given.

If fewer than *N* distinct feasible schedules exist, the loop stops early
and reports how many it found.

.. code-block:: bash

   schedulomicon swap \
       --config config.yml \
       --minimize-changes-from old_results.json \
       --require 'sum == 0: Resident A and Block 7 and Cardiology' \
       --rankings rankings.csv \
       --n-solutions 3 \
       --results new_results.json

.. code-block:: text

   === Proposal 1/3: 2 variable flip(s) from old schedule (score: 11) ===
   Solution written to new_results-1.json
   Changes from old schedule: 1 (main: 1)

   main:
     Resident A, Block 7: Cardiology -> ICU

   === Proposal 2/3: 4 variable flip(s) from old schedule (score: 9) ===
   Solution written to new_results-2.json
   ...

   Found 2 of 3 requested proposals; no further distinct feasible solutions exist.

A pass 1 that stops at a time limit with a ``FEASIBLE`` (not ``OPTIMAL``)
solution makes that proposal's flip count an upper bound rather than the
minimum, which weakens the strict lexicographic ordering guarantee (the
usual pass-1 warning is printed when this happens).

Change metric
^^^^^^^^^^^^^

Changes are counted as variable flips across **all grids** present in both
the old solution and the current model (``main``, ``backup``, ``vacation``).
Reassigning one resident's block is two flips (their old rotation turns off,
the new one turns on); adding or dropping a backup or vacation assignment is
one flip each.

Old assignments that reference residents, blocks, weeks, or rotations no
longer present in the config are reported in a warning (with counts and
sample keys) and ignored. Grids in the old file that the current model lacks
are skipped with a warning; model grids missing from the old file simply
contribute no change cost.

Diff report
^^^^^^^^^^^

After a successful swap, the minimal flip count and a per-grid diff report
are printed:

.. code-block:: text

   Minimal changes (variable flips) from old schedule: 6
   ...
   Changes from old schedule: 4 (main: 2, vacation: 2)

   main:
     Resident A, Spring: Clinic -> ICU
     Resident C, Spring: ICU -> Clinic

   vacation:
     + Resident A, Week 4, Emergency
     - Resident A, Week 1, Clinic

Main-grid changes are shown one line per reassigned (resident, block);
backup and vacation changes are listed as added (``+``) and dropped (``-``)
assignments. Old assignments that could no longer be compared are tallied in
a footer.
