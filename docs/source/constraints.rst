Constraints
===========

Schedulomicon provides a rich set of constraints that can be configured in YAML to express complex scheduling requirements. This guide covers the most commonly used constraint types and how to configure them.

Rotation Constraints
--------------------

These constraints are written as keys nested under a rotation name in the ``rotations:`` section of your config.

RotationCoverageConstraint
~~~~~~~~~~~~~~~~~~~~~~~~~~

Controls how many residents can be assigned to a rotation in each block.

.. code-block:: yaml

    rotations:
      Emergency:
        coverage: [1, 2]  # min 1, max 2 residents per block
      Surgery:
        coverage: [1, 1]  # exactly 1 resident per block
      Community Outreach:
        coverage:
          allowed_values: [0, 2]  # only 0 or 2 residents allowed (not 1)

The ``coverage`` property can be specified as:

- A list ``[min, max]`` defining minimum and maximum residents
- An ``allowed_values`` list specifying exactly which values are permitted

RotationCountConstraint
~~~~~~~~~~~~~~~~~~~~~~~

Limits how many times a resident can be assigned to a specific rotation.

.. code-block:: yaml

    rotations:
      Bigelow CBY:
        rot_count: [2, 2]  # exactly 2 instances required
      MGH ED CBY:
        rot_count: [1, 3]  # between 1 and 3 instances allowed
      Self-Design CBY:
        rot_count: [0, 2]  # optional, up to 2 instances

The ``rot_count`` property takes a list of ``[min, max]`` values:

- ``[2, 2]`` means exactly 2 rotations are required
- ``[0, 2]`` means up to 2 rotations are allowed but not required
- ``[1, 3]`` means at least 1 but no more than 3 rotations

``rot_count`` also accepts a mapping of resident group names to ``[min, max]`` ranges, so different groups can receive different limits for the same rotation:

.. code-block:: yaml

    rotations:
      Night Shift:
        rot_count:
          sr: [2, 3]    # seniors: 2–3 night shifts
          jr: [1, 2]    # juniors: 1–2 night shifts
          float: [0, 0] # floats: no night shifts

When a resident belongs to multiple groups, the *last* matching entry wins.

CoolDownConstraint
~~~~~~~~~~~~~~~~~~

Enforces minimum separation between assignments to the same rotation.

.. code-block:: yaml

    rotations:
      Vacation CBY:
        cool_down:
          window: 4  # minimum 4 blocks between assignments
          count: 1   # applies after 1 instance
          suppress_for: ["Resident A"]  # exceptions
      MGH Surgery CBY:
        cool_down:
          window: 6  # minimum 6 blocks between assignments
          count: 2   # applies after 2 instances

Parameters:

- ``window``: Minimum number of blocks between assignments
- ``count``: Number of occurrences before cool-down applies
- ``suppress_for``: List of residents exempt from this constraint

PrerequisiteRotationConstraint
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Ensures certain rotations are completed before others.

.. code-block:: yaml

    rotations:
      Tutorial 2:
        prerequisite: [Pre-Tutorial, Tutorial 1]  # simple list
      SICU-E4 CBY:
        prerequisite:
          heavy-rc: 1  # Requires 1 rotation from heavy-rc group
      Peds Surg:
        prerequisite:
          surgery: 1  # Requires 1 rotation from surgery group

The ``prerequisite`` property can be specified as:

- A list of specific rotations that must be completed
- A mapping of group names to counts, requiring a certain number of rotations from a group

MustBeFollowedByRotationConstraint
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Controls which rotations must follow others.

.. code-block:: yaml

    rotations:
      Pre-Tutorial:
        must_be_followed_by: [Tutorial 1]
      PM Shift:
        must_be_followed_by: [Night Shift, Education Day, Day Off]

The ``must_be_followed_by`` property takes a list of rotations or rotation groups. The constraint ensures that after the specified rotation, the resident is assigned to one of the listed options.

ConsecutiveRotationCountConstraint
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Enforces rotations that must occur in consecutive blocks.

.. code-block:: yaml

    rotations:
      SICU-E4 CBY:
        always_paired: Yes
      MGH Surgery CBY:
        always_paired: Yes

Setting ``always_paired: Yes`` indicates that this rotation must be assigned in consecutive blocks.

Resident Constraints
--------------------

These constraints are written as keys nested under a resident name in the ``residents:`` section of your config.

Field-Sum Constraints
~~~~~~~~~~~~~~~~~~~~~

Field-sum constraints let you enforce lower or upper bounds on how many times a selector expression is true for a given resident. The selector is a boolean expression over resident, block, and rotation groups (parsed by the same DSL used elsewhere in the config).

Supported operators:

- ``sum > N`` — at least N+1 matching assignments (strictly greater than N)
- ``sum == N`` — exactly N matching assignments
- ``sum <= N`` — at most N matching assignments

Each key maps to a list of selector strings; every string in the list generates its own constraint.

.. code-block:: yaml

    residents:
      Junior A:
        sum > 0:
          - Day 10 and Education Day   # must have at least 1 Education Day on Day 10
          - Day 01 and AM Shift        # must start on AM Shift
        sum == 0:
          - Education Day and not Day 10   # no Education Day except on Day 10
          - Night Shift and Early Block    # no night shifts during the Early Block

      Float Senior:
        sum == 0:
          - Education Day              # floats never take Education Day
        sum > 6:
          - Day Off                    # floats are off for more than 6 out of 10 days

YAML anchors (``&name`` / ``*name``) are useful for sharing an expression across multiple residents without duplication:

.. code-block:: yaml

    residents:
      Junior A:
        sum > 0:
          - &CA1EducationDay Day 10 and Education Day
      Junior B:
        sum > 0:
          - *CA1EducationDay   # reuses the same selector string

ProhibitedCombinationConstraint
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Prevents certain assignment combinations.

.. code-block:: yaml

    residents:
      Wilson, Michael:
        prohibit:
          - Blood Bank CBY
      Rodriguez, Sofia:
        prohibit:
          - Block 3 and ICU
          - Block 4 and ICU

The ``prohibit`` property takes a list of assignments that should not be assigned to the resident. This can be specific rotations or combinations of blocks and rotations.

TrueSomewhereConstraint
~~~~~~~~~~~~~~~~~~~~~~~

.. deprecated::
   ``true_somewhere`` is superseded by ``sum > 0``, which is more general and uses the same selector DSL. Prefer ``sum > 0`` for new configs.

Ensures specific assignments occur for certain residents.

.. code-block:: yaml

    residents:
      Rivera, Jessica:
        true_somewhere:
          - Block 12 and Vacation CBY
      Chen, David:
        true_somewhere:
          - Block 12 and Vacation CBY
          - Block 23 and Vacation CBY
          - Block 21 and Self-Design CBY
      Patel, Aisha:
        true_somewhere:
          - not PRIME CBY
          - Block 13 and Vacation CBY
          - (Block 1 or Block 2 or Block 3 or Block 4) and NWH MICU CBY

Block Constraints
-----------------

These constraints are written as keys nested under a block name in the ``blocks:`` section of your config. They use the same field-sum mechanism as resident constraints, but the selector expression is evaluated in the context of that block: the constraint counts how many assignments matching the selector occur *during that block*.

Field-Sum Constraints
~~~~~~~~~~~~~~~~~~~~~

Supported operators are the same as for resident constraints (``sum > N``, ``sum == N``, ``sum <= N``). This is useful for capping the total number of residents in a particular rotation group during a specific block, or for enforcing minimum staffing on certain days.

.. code-block:: yaml

    blocks:
      Day 01:
        groups: [Early Block]
        sum <= 1:
          - Night Shift   # at most 1 night-shift assignment on Day 01

      Day 10:
        sum == 1:
          - Education Day   # exactly 1 resident takes Education Day on Day 10

      ICU Week:
        sum <= 3:
          - icu            # at most 3 residents in the icu group during ICU Week

The selector strings follow the same boolean-expression DSL as resident field-sum constraints. Because the constraint is already scoped to the block, you typically only need rotation or resident group names in the selector.

Global / Group Constraints
--------------------------

These constraints are written under the top-level ``group_constraints:`` key and apply across all residents, blocks, and rotations (or a specified subset).

GroupCoverageConstraint
~~~~~~~~~~~~~~~~~~~~~~~

Applies coverage constraints to rotation groups.

.. code-block:: yaml

    group_constraints:
      - kind: group_coverage_constraint
        group: am-team
        min: 2
        max: 4   # between 2–4 residents on the AM team per block
      - kind: group_coverage_constraint
        group: pm-team
        min: 1
        max: 2

GroupCountPerResidentPerWindow
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Limits group rotations in a sliding window or over the entire schedule.

.. code-block:: yaml

    group_constraints:
      - kind: window_group_count_per_resident
        group: tough
        count: [0, 2]
        window_size: 3  # max 2 tough rotations in any 3-block window
      - kind: all_group_count_per_resident
        group: medicine
        count: [6, 12]  # between 6-12 medicine rotations per resident
      - kind: time_to_first
        group: medicine
        window_size: 8  # first medicine rotation must occur within first 8 blocks
      - kind: all_group_count_per_resident
        group: pediatrics
        count: [0,2]
        apply_to_residents: ["Nguyen, James"]  # constraint for specific resident

Group constraints come in several varieties:

- ``window_group_count_per_resident``: Limits group rotations in a sliding window
- ``all_group_count_per_resident``: Controls total rotations from a group per resident
- ``time_to_first``: Ensures early assignment from a rotation group
- The optional ``apply_to_residents`` parameter can limit a constraint to specific residents

Scoring Constraints
-------------------

MinIndividualScoreConstraint
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Sets minimum utility score per resident based on preferences.

.. code-block:: yaml

    constraints:
      - kind: min_individual_score
        score: 20  # Each resident must have at least 20 points

MinTotalScoreConstraint
~~~~~~~~~~~~~~~~~~~~~~~

Sets minimum utility score across all residents.

.. code-block:: yaml

    constraints:
      - kind: min_total_score
        score: 500  # Schedule must have at least 500 total points

Scoring constraints work in conjunction with preference files that assign scores to different rotations or vacation periods.

Vacation Constraints
--------------------

Vacation is handled through a dedicated section that controls when and how time off can be scheduled.

.. code-block:: yaml

    vacation:
      n_vacations_per_resident: 4  # Each resident gets 4 vacations
      blocks:
        Week 1: {rotation: Spring}
        Week 2: {rotation: Spring}
      pools:
        gs:
          rotations: [Gen Surg]
          max_vacation_per_week: 1  # Max 1 resident on vacation from Gen Surg per week
          max_total_vacation: 8     # Max 8 total vacation instances from Gen Surg
        critical:
          rotations: [ICU, Trauma]
          max_vacation_per_week: 0  # No vacations allowed during critical rotations

The vacation system is highly configurable:

- ``n_vacations_per_resident``: Sets how many vacation blocks each resident receives
- ``blocks``: Defines when vacations can be taken
- ``pools``: Groups rotations and sets vacation limits per pool

Combining Constraints
---------------------

Complex scheduling rules often require combining multiple constraints. For example:

.. code-block:: yaml

    # Require 4 blocks of Surgery, with at least 1 in first half of the year
    rotations:
      Surgery:
        rot_count: [4, 4]  # exactly 4 blocks required
        groups: surgery

    group_constraints:
      - kind: time_to_first
        group: surgery
        window_size: 13  # first surgery rotation must be in first 13 blocks

      # Ensure residents don't have too many difficult rotations in a row
      - kind: window_group_count_per_resident
        group: difficult
        count: [0, 2]
        window_size: 4  # max 2 difficult rotations in any 4-block window

    # Make specific assignments for specific residents
    residents:
      Sharma, Priya:
        sum > 0:
          - Block 5 and Vacation
        prohibit:
          - Block 3 and ICU
