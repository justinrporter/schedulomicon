Configuration Files
==================

This guide walks through creating a Schedulomicon configuration file step-by-step, building from basic elements to a complete scheduling solution.

Basic Structure
--------------

Schedulomicon configuration files use YAML format with several main sections that define your scheduling problem.

Step 1: Defining Basic Elements
------------------------------

Let's start with the three fundamental components of any schedule:

1. **Residents** - The people being scheduled
2. **Rotations** - The assignments they can receive
3. **Blocks** - The time periods for scheduling

Here's a minimal configuration with just these elements:

.. code-block:: yaml

    # Define residents
    residents:
      Resident A: {}
      Resident B: {}
      Resident C: {}
      Resident D: {}

    # Define rotations
    rotations:
      Emergency: {}
      Surgery: {}
      ICU: {}
      Clinic: {}

    # Define time blocks
    blocks:
      Spring: {}
      Summer: {}
      Fall: {}
      Winter: {}

This defines four residents, four rotations, and four time blocks, but without any constraints or requirements.

Step 2: Adding Rotation Coverage Requirements
--------------------------------------------

The next step is to add requirements for how many residents each rotation needs:

.. code-block:: yaml

    rotations:
      Emergency:
        coverage: [1, 2]  # min 1, max 2 residents per block
      Surgery:
        coverage: [1, 1]  # exactly 1 resident per block
      ICU:
        coverage: [1, 1]
      Clinic:
        coverage: [1, 2]

The ``coverage`` property takes a list of ``[min, max]`` values:
- The first number is the minimum required residents
- The second number is the maximum allowed residents

For example, ``[1, 1]`` means exactly one resident must be assigned, while ``[1, 2]`` allows one or two residents.

Step 3: Organizing Rotations with Groups
---------------------------------------

Rotations can be organized into groups, which will be useful for constraints later:

.. code-block:: yaml

    rotations:
      Emergency:
        groups: hospital
        coverage: [1, 2]
      Surgery:
        groups: hospital
        coverage: [1, 1]
      ICU:
        groups: critical
        coverage: [1, 1]
      Clinic:
        groups: outpatient
        coverage: [1, 2]
      Research:
        groups: elective
        coverage: [0, 1]  # optional rotation

The ``groups`` property assigns each rotation to a category. Rotations can share groups (like Emergency and Surgery both being "hospital" rotations).

Step 4: Adding Vacation Rules
---------------------------

Next, let's add vacation rules to allow time off:

.. code-block:: yaml

    # Define vacation rules
    vacation:
      n_vacations_per_resident: 1  # Each resident gets 1 vacation
      blocks:
        Week 1: {rotation: Spring}
        Week 2: {rotation: Summer}
        Week 3: {rotation: Fall}
        Week 4: {rotation: Winter}

This defines:
- How many vacations each resident is allowed
- When vacations can be taken (tied to specific blocks)

Step 5: Vacation Restrictions by Rotation Group
---------------------------------------------

We can add more complex vacation rules based on rotation groups:

.. code-block:: yaml

    vacation:
      n_vacations_per_resident: 1
      blocks:
        Week 1: {rotation: Spring}
        Week 2: {rotation: Summer}
        Week 3: {rotation: Fall}
        Week 4: {rotation: Winter}
      pools:
        hospital:
          rotations: [Emergency, Surgery]
          max_vacation_per_week: 1
          max_total_vacation: 4
        critical:
          rotations: [ICU]
          max_vacation_per_week: 0  # No vacations during ICU rotations
        outpatient:
          rotations: [Clinic]
          max_vacation_per_week: 1

The ``pools`` section:
- Groups rotations (using the groups we defined earlier)
- Sets ``max_vacation_per_week``: Maximum concurrent vacations allowed
- Sets ``max_total_vacation``: Maximum total vacations allowed in this pool

Note how critical rotations (ICU) are set to allow zero vacations, while hospital rotations allow one vacation per week.

Step 6: Adding Backup Coverage (Optional)
---------------------------------------

Finally, we can specify whether backup coverage is required:

.. code-block:: yaml

    # Backup coverage configuration
    backup: No

Setting ``backup: Yes`` would enable backup coverage constraints if your scheduling needs require it.

Complete Example
--------------

Putting it all together, here's a complete configuration:

.. code-block:: yaml

    # Define residents
    residents:
      Resident A: {}
      Resident B: {}
      Resident C: {}
      Resident D: {}

    # Define rotations with their properties
    rotations:
      Emergency:
        groups: hospital
        coverage: [1, 2]
      Surgery:
        groups: hospital
        coverage: [1, 1]
      ICU:
        groups: critical
        coverage: [1, 1]
      Clinic:
        groups: outpatient
        coverage: [1, 2]
      Research:
        groups: elective
        coverage: [0, 1]

    # Define time blocks
    blocks:
      Spring: {}
      Summer: {}
      Fall: {}
      Winter: {}

    # Define vacation rules
    vacation:
      n_vacations_per_resident: 1
      blocks:
        Week 1: {rotation: Spring}
        Week 2: {rotation: Summer}
        Week 3: {rotation: Fall}
        Week 4: {rotation: Winter}
      pools:
        hospital:
          rotations: [Emergency, Surgery]
          max_vacation_per_week: 1
          max_total_vacation: 4
        critical:
          rotations: [ICU]
          max_vacation_per_week: 0
        outpatient:
          rotations: [Clinic]
          max_vacation_per_week: 1
        elective:
          rotations: [Research]
          max_vacation_per_week: 1

    # Backup coverage configuration
    backup: No

Advanced Features
---------------

For more complex scheduling needs, the system supports additional constraints like:

- Resident-specific rotation requirements
- Consecutive rotation limits
- Cooldown periods between rotations
- Weighted rotation preferences

These advanced features will be covered in separate documentation.