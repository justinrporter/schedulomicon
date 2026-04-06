Scoring & Preferences
=====================

Schedulomicon separates schedule construction into two layers:

1. **Hard constraints** — rules that *must* be satisfied (coverage requirements,
   rotation limits, prerequisites, etc.). If the solver cannot satisfy all hard
   constraints simultaneously, no schedule is produced. There is no built-in
   penalty for "almost" satisfying a constraint — it either holds or it doesn't.

2. **Score objective** — a numeric preference signal that the solver *minimizes*
   among all feasible (constraint-satisfying) schedules. Scores let you express
   soft preferences like "Resident A prefers Surgery" or "everyone prefers
   vacation in Block 5."

If no scores are provided, every feasible schedule is equally acceptable and the
solver returns the first one it finds.


How Scoring Works
-----------------

The objective is a linear sum over every ``(resident, block, rotation)`` triple:

.. math::

   \text{Total Score} = \sum_{r,\, b,\, rot} \text{score}[r, b, rot] \times \text{assigned}[r, b, rot]

where ``assigned[r, b, rot]`` is 1 when resident *r* is assigned to rotation
*rot* in block *b*, and 0 otherwise. The solver **minimizes** this sum, so
**lower (more negative) scores are preferred**.

Only assigned combinations contribute to the total. Unassigned triples multiply
by zero and drop out.

.. tip::

   Use negative scores for desirable assignments and positive scores (or zero)
   for undesirable ones. For example, if Resident A ranks Surgery as their #1
   choice, give that pair a score of ``-10``; a last-choice rotation might get
   ``0`` or a positive value.


Providing Scores via CLI
------------------------

The ``schedulomicon`` CLI accepts three flags for injecting scores. All sources
are **additive** — when both ``--rankings`` and ``--block-resident-ranking`` are
provided, their scores accumulate into the same score dictionary before the
solver sees them.

``--rankings rankings.csv``
^^^^^^^^^^^^^^^^^^^^^^^^^^^

A CSV where **rotations are rows** (first column is the index) and **residents
are columns**. Each cell is the score for that (resident, rotation) pair, applied
uniformly across every block.

.. code-block:: text

   ,Resident_A,Resident_B,Resident_C
   Surgery,-10,-2,0
   Medicine,-5,-8,-3
   ICU,0,-1,-7

In this example Resident A strongly prefers Surgery (``-10``) while Resident C
strongly prefers ICU (``-7``).

``--block-resident-ranking <Rotation> prefs.csv``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A CSV where **residents are rows** (first column is the index) and **blocks are
columns**. Each cell is an additional score for the named rotation in that
(resident, block) pair. This is useful for block-specific preferences such as
vacation timing.

.. code-block:: text

   ,Block1,Block2,Block3,Block4
   Resident_A,0,0,-5,0
   Resident_B,0,-5,0,0

Here Resident A prefers the named rotation in Block 3, while Resident B prefers
Block 2.

Because scores are additive, ``--rankings`` provides the baseline rotation
preferences and ``--block-resident-ranking`` layers on block-specific
adjustments.

``--score-list <GRID> scores.csv``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A CSV with four columns: three key columns followed by a score column. The first
three columns identify a ``(key1, key2, key3)`` triple on the named grid
(``main``, ``vacation``, or ``backup``). This flag can be repeated to add scores
on multiple grids.

.. code-block:: text

   resident,block,rotation,score
   Resident_A,Block1,Vacation,-10
   Resident_B,Block3,Vacation,-8

Usage:

.. code-block:: bash

   schedulomicon --config config.yml --results out.csv \
       --score-list vacation vacation_scores.csv


Score Constraints
-----------------

Two constraints turn the soft objective into hard floors:

- ``--min-individual-rank <N>`` — Every resident's individual score must be at
  most *N*. (Since the solver minimizes, this sets an upper bound on how "bad"
  any single resident's assignment can be.)
- :class:`~schedulomicon.csts.MinTotalScoreConstraint` — The total schedule
  score must be at most *N*.

These are added via CLI flags or programmatically, not through the YAML config.
See :doc:`constraints` for the full constraint reference.


Python API
----------

For programmatic usage of the scoring system, see the
:ref:`scoring section of the API guide <api-scoring>`.
The key functions are:

- :func:`~schedulomicon.score.score_dict_from_df` — build a score dictionary
  from rankings data
- :func:`~schedulomicon.score.objective_from_score_dict` — convert a score
  dictionary into a CP-SAT objective expression
- :func:`~schedulomicon.score.aggregate_score_functions` — combine multiple
  scoring functions across grids
