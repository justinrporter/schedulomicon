# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands
- Run tests: `pytest schedulomicon/test_*.py`
- Run single test: `pytest schedulomicon/test_solve.py::test_small_puzzle`
- Run solver: `python -m schedulomicon.solver --config config.yml --results results.csv`

## Code Style
- **Imports**: Standard Python imports at top, grouped by stdlib → third-party → local
- **Type annotations**: No strict type annotations
- **Naming**: snake_case for variables/functions, CamelCase for classes
- **Error handling**: Custom exceptions defined in exceptions.py
- **Frameworks**: Uses Google OR-Tools CP-SAT solver for constraint programming

## Configuration Structure
- **residents**: List of residents with optional properties
- **rotations**: Defined with groups and coverage requirements [min, max]
- **blocks**: Time periods (e.g., seasons, weeks) for scheduling
- **vacation**: Rules for time-off including:
  - n_vacations_per_resident: Number of allowed vacations
  - blocks: Available vacation periods
  - pools: Rotation groups with vacation restrictions
- **backup**: Optional coverage configuration (Yes/No)

## Constraints
- **RotationCoverageConstraint**: Controls resident count per rotation (min/max or allowed values)
- **GroupCoverageConstraint**: Applies coverage constraints to rotation groups
- **RotationCountConstraint**: Limits total instances of rotation per resident
- **RotationCountConstraintWithHistory**: Includes historical assignments in rotation counts
- **RotationCountNotConstraint**: Prevents exactly N instances of a rotation
- **ConsecutiveRotationCountConstraint**: Enforces rotations occur in consecutive blocks
- **AllowedRootsConstraint**: Restricts where consecutive sequences can begin
- **PrerequisiteRotationConstraint**: Ensures prerequisites are completed first
- **IneligibleAfterConstraint**: Makes rotations ineligible after criteria met
- **MustBeFollowedByRotationConstraint**: Controls which rotations follow others
- **CoolDownConstraint**: Enforces minimum gaps between rotation assignments
- **TrueSomewhereConstraint**: Ensures at least one assignment from eligible set
- **ProhibitedCombinationConstraint**: Prevents certain assignment combinations
- **MarkIneligibleConstraint**: Makes specific assignments ineligible
- **RotationWindowConstraint**: Ensures rotation within specific block window
- **ResidentGroupConstraint**: Restricts rotations to eligible residents
- **EligibleAfterBlockConstraint**: Makes residents eligible only after specified block
- **TimeToFirstConstraint**: Ensures early assignment from rotation group
- **MinIndividualScoreConstraint**: Sets minimum utility score per resident
- **MinTotalScoreConstraint**: Sets minimum utility score across all residents
- **GroupCountPerResidentPerWindow**: Limits group rotations in sliding window

This package provides constraint-based scheduling optimization primarily for medical resident rotation assignments.

## Adding New Constraints

New constraints must implement parsing logic themselves via a `from_yml_dict` classmethod — **do not add constraint-specific parsing logic to io.py**.

- **Rotation-scoped constraints**: set a `KEY_NAME` class variable (matching the YAML key) and implement:
  ```python
  @classmethod
  def from_yml_dict(cls, rotation, params, config): ...
  ```
  Then add the class to the `active_constraint_types` list in `generate_rotation_constraints()` in io.py — that's the only io.py change needed.

- **Group/global constraints**: implement:
  ```python
  @classmethod
  def from_yml_dict(cls, params, config): ...
  ```
  and register via `KEY_NAME` in the appropriate dispatch dict in io.py, not via a new `if/elif` branch.

The `from_yml_dict` method is responsible for all YAML-to-Python translation. io.py should remain a generic dispatcher.