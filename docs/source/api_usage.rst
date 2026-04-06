Python API Usage
================

Schedulomicon can be used directly as a Python library. The primary entry points are
``schedulomicon.io``, ``schedulomicon.solve``, ``schedulomicon.score``, and
``schedulomicon.callback``.

Call Sequence
-------------

**Step 1 — Load config**

.. code-block:: python

    import yaml

    with open('config.yml') as f:
        config = yaml.safe_load(f)

The YAML config is the specification file for the schedule model: residents, rotations, blocks,
vacation rules, and all constraint settings. Loading it first makes a raw dict available to
every subsequent step.

**Step 2 — Process config**

.. code-block:: python

    from schedulomicon import io

    residents, blocks, rotations, cogrids, groups_array = io.process_config(config)

``io.process_config`` translates the raw config dict into the typed Python objects that the
solver and constraint builder expect — named lists for dimensions and boolean NumPy arrays
encoding group memberships.

``process_config`` extracts the core scheduling dimensions from the config dict:

- ``residents``, ``blocks``, ``rotations``: lists of names in config order
- ``cogrids``: list of optional grid keys present in the config (``'vacation'``, ``'backup'``)
- ``groups_array``: dict mapping group/resident/block/rotation names to 3-D boolean NumPy
  arrays of shape ``(n_residents, n_blocks, n_rotations)``

**Step 3 — Build constraint list**

.. code-block:: python

    cst_list = io.generate_constraints_from_configs(config, groups_array)

This step converts every constraint entry in the config into a constraint object which will add
low-level constraints to the OR-Tools solver. Coverage constraints that live outside the YAML
(e.g. in a CSV) can be appended to the same list.

Returns a ``list`` of constraint objects ready to pass to `solve`. To append coverage constraints
from a CSV file:

.. code-block:: python

    cst_list += io.coverage_constraints_from_csv('coverage.csv', 'rmin')
    # or 'rmax' for maximum-coverage constraints

**Step 4 — Solve**

.. code-block:: python

    from functools import partial
    from schedulomicon import solve, callback

``solve.solve`` runs the CP-SAT solver against the constraints and (optionally) optimizes a
score objective. The ``soln_printer`` is built with ``partial`` so the solver can instantiate
it internally while you control which residents, blocks, and rotations it tracks.

.. code-block:: python

    soln_printer = partial(
        callback.JugScheduleSolutionPrinter,
        residents=residents,
        blocks=blocks,
        rotations=rotations,
    )

    status, solver, solution_printer, model, wall_runtime_mins = solve.solve(
        residents,
        blocks,
        rotations,
        groups_array,
        cst_list,
        soln_printer,
        cogrids={k: config[k] for k in cogrids},
        score_functions=[],          # see "Scoring / Objective" below
        max_time_in_mins=5,
        n_processes=None,            # auto-detected when None
        hint=None,                   # prior solution dict for warm-start
    )

``status`` is one of ``'OPTIMAL'``, ``'FEASIBLE'``, ``'INFEASIBLE'``, or ``'UNKNOWN'``.

**Step 5 — Extract results**

.. code-block:: python

    solutions = solution_printer._solutions          # list of solution dicts
    scores    = solution_printer._solution_scores   # parallel list of per-resident score DataFrames

``_solutions`` is a list of assignment dicts (one per feasible solution found);
``_solution_scores`` holds the parallel list of per-resident score DataFrames. If no
``score_functions`` were provided, scores will be empty.

.. _api-scoring:

Optional: Scoring / Objective
------------------------------

.. seealso::

   :doc:`scoring` for a full explanation of how the scoring system works,
   CLI flags for providing scores, and CSV format examples.

To optimize for resident preferences, build a score dict and pass it as a ``score_functions``
entry.

``score.score_dict_from_df`` signature:

.. code-block:: python

    scores = score.score_dict_from_df(
        rankings,               # {resident: {rotation: int}}  e.g. rankings_df.fillna(0).T.to_dict()
        residents,
        blocks,
        rotations,
        block_resident_ranking, # (rotation_name, {resident: {block: int}}) or None
    )

Returns ``Dict[(resident, block, rotation), int]``.

Use with ``score.objective_from_score_dict`` as a ``score_functions`` entry:

.. code-block:: python

    from schedulomicon import score

    score_functions = [
        ('main', partial(score.objective_from_score_dict, scores=scores))
    ]

Pass ``score_functions`` to ``solve.solve`` in place of ``[]``.

Full Example
------------

.. code-block:: python

    import yaml
    from functools import partial
    from schedulomicon import io, solve, score, callback

    # 1. Load config
    with open('config.yml') as f:
        config = yaml.safe_load(f)

    # 2. Process config
    residents, blocks, rotations, cogrids, groups_array = io.process_config(config)

    # 3. Build constraints
    cst_list = io.generate_constraints_from_configs(config, groups_array)

    # 4. (Optional) build score objective from a rankings DataFrame
    # rankings_df: index=rotations, columns=residents, values=preference scores
    # scores = score.score_dict_from_df(
    #     rankings_df.fillna(0).T.to_dict(), residents, blocks, rotations, None
    # )
    # score_functions = [('main', partial(score.objective_from_score_dict, scores=scores))]
    score_functions = []

    # 5. Solve
    soln_printer = partial(
        callback.ScheduleSolutionPrinter,
        residents=residents,
        blocks=blocks,
        rotations=rotations,
    )

    status, solver, solution_printer, model, wall_runtime_mins = solve.solve(
        residents,
        blocks,
        rotations,
        groups_array,
        cst_list,
        soln_printer,
        cogrids={k: config[k] for k in cogrids},
        score_functions=score_functions,
        max_time_in_mins=5,
    )

    print(f"Solver status: {status}  ({wall_runtime_mins:.1f} min)")

    if status in ('OPTIMAL', 'FEASIBLE'):
        best = solution_printer._solutions[-1]
        print(best)
