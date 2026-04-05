# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Schedulomicon is a constraint-based scheduling optimizer for medical resident rotation assignments, built on Google OR-Tools CP-SAT. A YAML config describes residents, blocks, rotations, and constraints; the solver produces an assignment (optionally optimized against a ranking/score objective).

## Commands

- Install (editable): `pip install -e .`
- Run solver (CLI entry point from `setup.py`): `schedulomicon --config config.yml --results results.csv`
  - Equivalent to `python -m schedulomicon.solver ...`
- Run all tests: `pytest schedulomicon/test_*.py`
- Run a single test: `pytest schedulomicon/test_solve.py::test_small_puzzle`

Note: `setup.py` pins `ortools==9.8.3296` and requires Python `>=3.6, <3.11` to match available OR-Tools wheels.

## Architecture

The solving pipeline flows config → constraints → CP-SAT model → solution, split across these modules:

- **`solver.py`** — CLI entry point (`main`). Parses args, loads YAML, wires rankings/coverage CSVs into score functions and extra constraints, then calls `solve.solve`.
- **`io.py`** — YAML/CSV I/O plus **constraint dispatch**. `process_config` builds `groups_array` (boolean masks over residents×blocks×rotations for every named group and every individual entity). `generate_constraints_from_configs` walks the YAML and invokes each constraint class's `from_yml_dict`. See "Adding constraints" below — io.py is meant to stay a generic dispatcher.
- **`model.py`** — Builds the raw CP-SAT variables. `generate_model` creates the main `block_assigned[resident, block, rotation]` BoolVars and the "each resident does exactly one rotation per block" base constraint. `generate_vacation` and `generate_backup` build cogrid variables.
- **`solve.py`** — Orchestrates a solve: builds the model, assembles `grids` (a dict of `main`/`backup`/`vacation` cogrids, each with `dimensions` and `variables`), calls `cst.apply(...)` for each constraint, optionally adds a hint and score objective, then runs `run_optimizer` or `run_enumerator`.
- **`csts.py`** — Concrete `Constraint` subclasses (rotation, resident, group/global). Each inherits from the `Constraint` base and implements `apply(model, block_assigned, residents, blocks, rotations, grids)`. Many also implement `from_yml_dict` + a `KEY_NAME` class attribute for YAML dispatch.
- **`cogrid_csts.py`** — Constraints that act on the auxiliary `vacation` and `backup` grids rather than the main grid.
- **`parser.py`** — `pyparsing`-based DSL used inside YAML selector strings. `resolve_eligible_field` parses boolean expressions like `"Senior and (Emergency or ICU)"` against `groups_array` to produce a boolean mask. `parse_sum_function` parses comparators like `"sum > 0"` used by `FieldSumConstraint`.
- **`score.py`** — Builds the linear objective from per-(resident, block, rotation) score dictionaries.
- **`callback.py`** — `CpSolverSolutionCallback` subclasses that capture solutions during search.

### The `grids` abstraction

Constraints receive a `grids` dict that lets them operate uniformly over cogrids. The main rotation assignment lives in `grids['main']['variables']` keyed by `(resident, block, rotation)`. Optional cogrids `grids['backup']` and `grids['vacation']` exist when the YAML opts in via top-level `backup:` or `vacation:` keys. When writing a new constraint that touches vacation or backup, pull variables from `grids[<name>]['variables']`, not from `block_assigned`.

### The `groups_array` abstraction

`groups_array` is a `{name: np.ndarray[residents, blocks, rotations]}` dict of boolean masks built once by `io.process_config`. Every named group (from `groups:` lists under residents/blocks/rotations) and every individual resident/block/rotation gets an entry. The parser DSL composes these masks with `and`/`or`/`not` to produce an "eligible field" that constraints like `TrueSomewhereConstraint`, `FieldSumConstraint`, and `ProhibitedCombinationConstraint` iterate over.

## Config structure (YAML)

Top-level keys: `residents`, `rotations`, `blocks`, plus optional `vacation`, `backup`, `group_constraints`, `rotation_windows`, `resident_groups`, `eligible_after`. Residents, blocks, and rotations are maps whose values may carry a `groups:` list and per-entity constraints nested by `KEY_NAME`.

## Constraint scopes

Constraints live in YAML under the scope they apply to. The code that dispatches each scope is in `io.py`:

- **Rotation-scoped** (nested under a rotation): `RotationCoverageConstraint` (`coverage`), `CoolDownConstraint`, `RotationCountConstraint`, `RotationCountConstraintWithHistory`, `PrerequisiteRotationConstraint`, `IneligibleAfterConstraint`, `ConsecutiveRotationCountConstraint`, `AllowedRootsConstraint`, plus special cases `must_be_followed_by`, `always_paired`, `not_rot_count`.
- **Per-resident** (nested under a resident): `ProhibitedCombinationConstraint`, `TrueSomewhereConstraint` (deprecated — prefer `sum > 0`), plus any `sum <op> N` field-sum constraints via `parse_field_sum_constraint`, plus `chosen-vacation`.
- **Per-block** (nested under a block): field-sum constraints.
- **Group/global** (under `group_constraints:`): `GroupCoverageConstraint`, `TimeToFirstConstraint`, `GroupCountPerResidentPerWindow` (keys `all_group_count_per_resident` / `window_group_count_per_resident`).
- **Cogrid**: vacation and backup constraints live in `cogrid_csts.py` and are generated by `generate_vacation_constraints` / `generate_backup_constraints`.
- **CLI-only**: `MinIndividualScoreConstraint` / `MinTotalScoreConstraint` are added from solver flags, not YAML.

## Adding new constraints

New constraints must own their YAML parsing. **Do not add constraint-specific branches to io.py.**

- Rotation-scoped: set a `KEY_NAME` class attribute matching the YAML key and implement `@classmethod from_yml_dict(cls, rotation, params, config)`. Register by appending the class to `active_constraint_types` in `generate_rotation_constraints` in `io.py` — that is the only io.py change needed.
- Resident-scoped: same pattern with `@classmethod from_yml_dict(cls, res, params, config, groups_array)`, registered in `resident_constraint_types` in `generate_resident_constraints`.
- Group/global: implement `@classmethod from_yml_dict(cls, params, config)` (or the variant matching the dispatcher) and register in the appropriate dispatch in `generate_constraints_from_configs`.

`from_yml_dict` is responsible for all YAML→Python translation. Keep `io.py` a generic dispatcher.
