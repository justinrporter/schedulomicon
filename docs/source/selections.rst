Selections and Field-Sum Syntax
===============================

This feature controls *where* a constraint applies.

The schedule is a 3D grid:

- resident
- block
- rotation

Each cell in that grid is binary. Assigned or not assigned.

A *selection* is a set of cells in that grid.


The Grid
--------

Every possible assignment lives at one coordinate:

.. code-block:: text

    (resident, block, rotation)

Example:

.. code-block:: text

    (Junior A, Day 10, Education Day)

That cell is either 1 or 0.


Groups
------

``groups:`` creates reusable selectors.

You can attach groups to residents, blocks, or rotations.

.. code-block:: yaml

    residents:
      Junior A:
        groups: [jr, education-day]

    blocks:
      Day 01:
        groups: [Early Block]

    rotations:
      Night Shift:
        groups: [night]

Each group marks a slice of the grid.

- A resident group marks all cells for those residents.
- A block group marks all cells in those blocks.
- A rotation group marks all cells on those rotations.

Direct names also work as selectors.

- A resident name selects that resident.
- A block name selects that block.
- A rotation name selects that rotation.

Use groups when the same idea appears more than once.


Composing Selections
--------------------

Use boolean words to build a selection.

- ``and`` narrows the selection.
- ``or`` widens the selection.
- ``not`` excludes cells.
- Parentheses control grouping.

Example:

.. code-block:: text

    jr and Early Block and Night Shift

Plain English: select night-shift cells for junior residents during the early block.

Example:

.. code-block:: text

    Education Day and not Day 10

Plain English: select education-day cells everywhere except Day 10.

Example:

.. code-block:: text

    (Day 01 or Day 02 or Day 03 or Day 04) and ICU

Plain English: select ICU cells in the first four blocks.

``not`` is broad. It flips the whole selection that follows it.

Example:

.. code-block:: text

    not Early Block and Night Shift

Plain English: select night-shift cells outside the early block.

If a name contains spaces, you may quote it.

.. code-block:: text

    "Early Block" and "Night Shift"

Plain English: same selection as above, with quoted names.

Use the word operators ``and``, ``or``, and ``not`` in documentation and configs.


Field Sums
----------

A field sum counts assigned cells inside a selection.

Then it checks that count against a rule.

Supported comparators:

- ``sum == N``: exactly ``N``
- ``sum != N``: anything except ``N``
- ``sum > N``: more than ``N``
- ``sum >= N``: at least ``N``
- ``sum < N``: fewer than ``N``
- ``sum <= N``: no more than ``N``

Common cases:

- ``sum == 0`` means never.
- ``sum > 0`` means at least once.
- ``sum == 1`` means exactly once.

Example:

.. code-block:: yaml

    residents:
      Junior A:
        sum > 0:
          - Day 10 and Education Day
        sum == 0:
          - Education Day and not Day 10

Plain English:

- Junior A must have Education Day at least once on Day 10.
- Junior A must not have Education Day anywhere else.

Each string under a ``sum ...:`` key becomes its own constraint.

This matters:

.. code-block:: yaml

    residents:
      Junior A:
        sum == 0:
          - Night Shift
          - Education Day

Plain English: no night shifts, and no education days.

This is different:

.. code-block:: yaml

    residents:
      Junior A:
        sum == 0:
          - Night Shift or Education Day

Plain English: no assignments from either set. One combined selection.


Scope
-----

Field sums are scoped by where they appear.

Under a resident, the resident is already fixed.

.. code-block:: yaml

    residents:
      Junior A:
        sum == 0:
          - Night Shift and Early Block

Plain English: Junior A cannot work night shift during the early block.

Under a block, the block is already fixed.

.. code-block:: yaml

    blocks:
      Day 10:
        sum == 1:
          - Education Day

Plain English: exactly one resident has Education Day on Day 10.

You usually should not repeat the scope selector inside the expression.


Worked Example
--------------

This is the pattern used in ``examples/ob_example.yml``.

.. code-block:: yaml

    residents:
      Junior A:
        groups: [jr, education-day]
        sum > 0:
          - Day 10 and Education Day
          - Day 01 and AM Shift
        sum == 0:
          - Education Day and not Day 10
          - Night Shift and Early Block

      Junior B:
        groups: [jr, education-day]
        sum > 0:
          - &CA1EducationDay Day 10 and Education Day
        sum == 0:
          - &NoEarlyNights Night Shift and Early Block

      CRNA Junior:
        groups: [crna-jr]
        sum == 0:
          - *NoEarlyNights

    blocks:
      Day 01:
        groups: [Early Block]
      Day 02:
        groups: [Early Block]
      Day 03:
        groups: [Early Block]
      Day 04:
        groups: [Early Block]

Plain English:

- ``Early Block`` tags the first four days.
- ``Night Shift and Early Block`` selects all early-block night-shift cells.
- Under ``Junior A``, that selector only counts Junior A's cells.
- Under ``CRNA Junior``, the same selector only counts CRNA Junior's cells.
- YAML anchors let you reuse a selector string without copying it.


Common Mistakes
---------------

- Undefined names fail to parse. If the name is not a resident, block, rotation, or group, it is wrong.
- ``not`` can select far more cells than you meant. Read it carefully.
- Two list items under the same ``sum`` key are two constraints, not one.
- Groups do not change the schedule by themselves. They only label parts of the grid.
- ``prohibit`` uses the same selector language. It forbids the selected cells for that resident.
