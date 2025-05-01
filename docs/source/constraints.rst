Constraints
==========

Schedulomicon provides a rich set of constraints that can be configured in YAML to express complex scheduling requirements. This guide covers the most commonly used constraint types and how to configure them.

Basic Constraint Types
---------------------

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

CoolDownConstraint
~~~~~~~~~~~~~~~~~

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

Sequence Constraints
-------------------

PrerequisiteRotationConstraint
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Controls which rotations must follow others.

.. code-block:: yaml

    rotations:
      Pre-Tutorial:
        must_be_followed_by: [Tutorial 1]
      Bigelow CBY:
        must_be_followed_by: [elective, Vacation CBY, MGH ED CBY]

The ``must_be_followed_by`` property takes a list of rotations or rotation groups. The constraint ensures that after the specified rotation, the resident is assigned to one of the listed options.

ConsecutiveRotationCountConstraint
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Enforces rotations that must occur in consecutive blocks.

.. code-block:: yaml

    rotations:
      SICU-E4 CBY:
        always_paired: Yes
      MGH Surgery CBY:
        always_paired: Yes

Setting ``always_paired: Yes`` indicates that this rotation must be assigned in consecutive blocks.

Assignment Constraints
--------------------

TrueSomewhereConstraint
~~~~~~~~~~~~~~~~~~~~~~

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

The ``true_somewhere`` property takes a list of logical expressions that must be satisfied somewhere in the schedule. This is useful for implementing vacation preferences and special rotation requests.

ProhibitedCombinationConstraint
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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

MarkIneligibleConstraint
~~~~~~~~~~~~~~~~~~~~~~

Makes specific rotation-block combinations ineligible.

.. code-block:: yaml

    marked_ineligible:
      - resident: "All"
        rotation: "ICU"
        blocks: [Block 1, Block 2]
      - resident: "Thompson, Robert"
        rotation: "Surgery"
        blocks: [Block 10, Block 11, Block 12]

The ``marked_ineligible`` section defines specific combinations that are not allowed, with:
- ``resident``: The affected resident(s) or "All"
- ``rotation``: The rotation to make ineligible
- ``blocks``: List of blocks where the constraint applies

Group-Based Constraints
---------------------

GroupCoverageConstraint
~~~~~~~~~~~~~~~~~~~~~

Applies coverage constraints to rotation groups.

.. code-block:: yaml

    group_constraints:
      - kind: group_coverage
        group: surgery
        coverage: [2, 4]  # Between 2-4 residents in surgery rotations

ResidentGroupConstraint
~~~~~~~~~~~~~~~~~~~~~

Restricts rotations to eligible residents.

.. code-block:: yaml

    residents:
      Garcia, Carlos:
        groups: [senior, surgery]
      Kim, Olivia:
        groups: [junior, medicine]
        
    rotations:
      Chief Surgery:
        eligible_groups: [senior, surgery]
      Internal Medicine:
        eligible_groups: [medicine]

The ``eligible_groups`` property specifies which resident groups can be assigned to the rotation. Residents must belong to at least one of the listed groups to be eligible.

GroupCountPerResidentPerWindow
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Limits group rotations in a sliding window.

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
-----------------

MinIndividualScoreConstraint
~~~~~~~~~~~~~~~~~~~~~~~~~~

Sets minimum utility score per resident based on preferences.

.. code-block:: yaml

    constraints:
      - kind: min_individual_score
        score: 20  # Each resident must have at least 20 points
        
MinTotalScoreConstraint
~~~~~~~~~~~~~~~~~~~~~

Sets minimum utility score across all residents.

.. code-block:: yaml

    constraints:
      - kind: min_total_score
        score: 500  # Schedule must have at least 500 total points

Scoring constraints work in conjunction with preference files that assign scores to different rotations or vacation periods.

Vacation Constraints
------------------

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
-------------------

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
        true_somewhere:
          - Block 5 and Vacation
        prohibit:
          - Block 3 and ICU