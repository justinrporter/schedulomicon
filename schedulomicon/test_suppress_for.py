"""Tests for suppress_for support on PerResidentConstraint subclasses.

These tests are written first (TDD). They fail until the PerResidentConstraint
subtype is defined and each constraint is updated.
"""

import numpy as np
import pandas as pd

from . import solve, csts, callback, cogrid_csts


class SolnPrinter(callback.BaseSolutionPrinter):
    def __init__(self, *args, **kwargs):
        self.solutions = []
        self.solution_count = 0
        super().__init__(*args, **kwargs)

    def on_solution_callback(self):
        self.solution_count += 1
        records = []
        for block in self._blocks:
            record = []
            for resident in self._residents:
                for rotation in self._rotations:
                    if self.Value(self._block_assigned[(resident, block, rotation)]):
                        record.append(rotation)
            records.append(record)
        self.solutions.append(pd.DataFrame.from_records(
            records, index=self._blocks, columns=self._residents
        ))


def _solve(**kwargs):
    defaults = dict(
        groups_array=[],
        soln_printer=SolnPrinter,
        score_functions=[],
        n_processes=1,
        cogrids={},
        max_time_in_mins=5,
        hint=None,
    )
    defaults.update(kwargs)
    return solve.solve(**defaults)


def _rot_counts(soln, resident, rotation):
    return sum(1 for v in soln[resident].values if v == rotation)


def test_rot_count_suppress_for():
    """Suppressed resident can exceed the rotation count limit; others cannot."""
    residents = ['R1', 'R2', 'R3']
    blocks = [f'Bl{i+1}' for i in range(4)]
    rotations = ['Ro1', 'Ro2']

    # R1 is suppressed — the constraint allows R1 to go over limit=1
    # Force R1 into Ro1 more than once by also forcing coverage >= 2 in some blocks
    status, solver, solution_printer, model, wall_runtime = _solve(
        residents=residents,
        blocks=blocks,
        rotations=rotations,
        cst_list=[
            csts.RotationCoverageConstraint('Ro1', rmin=0, rmax=3),
            csts.RotationCoverageConstraint('Ro2', rmin=0, rmax=3),
            # Only R1 does Ro1; R2 and R3 do Ro2. Use rot_count to enforce this.
            csts.RotationCountConstraint('Ro1', {'R1': (3, 3), 'R2': (0, 0), 'R3': (0, 0)}),
            # Without suppress_for, applying [0,1] to all would make R1 infeasible
            # With suppress_for=['R1'], R2 and R3 get [0,1] but R1 is exempt
            csts.RotationCountConstraint(
                'Ro1',
                {'R1': (0, 1), 'R2': (0, 1), 'R3': (0, 1)},
                suppress_for=['R1'],
            ),
        ],
    )

    assert status == 'FEASIBLE' or status == 'OPTIMAL', (
        f"Expected a solution but got {status}"
    )
    soln = solution_printer.solutions[-1]
    assert _rot_counts(soln, 'R1', 'Ro1') == 3
    assert _rot_counts(soln, 'R2', 'Ro1') <= 1
    assert _rot_counts(soln, 'R3', 'Ro1') <= 1


def test_allowed_roots_suppress_for():
    """Suppressed resident can start a sequence outside allowed roots; others cannot.

    We use per-block coverage=0 to forbid Ro1 at the only allowed root (Bl1), so
    without suppress_for the problem is INFEASIBLE. With suppress_for=['R1'], R1 is
    exempt and can land at Bl2 — making it feasible.
    """
    residents = ['R1']
    # Ro1 can only start at Bl1 (the sole allowed root).
    # We also set coverage=0 at Bl1 so nobody can actually be there.
    # => Without suppress_for: INFEASIBLE (only allowed root is blocked).
    # => With suppress_for=['R1']: FEASIBLE (R1 exempt, lands at Bl2).
    blocks = ['Bl1', 'Bl2']
    rotations = ['Ro1', 'Ro2']

    status_no_suppress, *_ = _solve(
        residents=residents,
        blocks=blocks,
        rotations=rotations,
        cst_list=[
            csts.RotationCoverageConstraint('Ro1', blocks=['Bl1'], rmin=0, rmax=0),
            csts.RotationCoverageConstraint('Ro1', blocks=['Bl2'], rmin=0, rmax=1),
            csts.RotationCoverageConstraint('Ro2', rmin=0, rmax=1),
            csts.RotationCountConstraint('Ro1', {'R1': (1, 1)}),
            csts.AllowedRootsConstraint('Ro1', allowed_roots=['Bl1']),
        ],
    )
    assert status_no_suppress == 'INFEASIBLE', (
        f"Expected INFEASIBLE without suppress_for, got {status_no_suppress}"
    )

    status_suppressed, _, sp, *_ = _solve(
        residents=residents,
        blocks=blocks,
        rotations=rotations,
        cst_list=[
            csts.RotationCoverageConstraint('Ro1', blocks=['Bl1'], rmin=0, rmax=0),
            csts.RotationCoverageConstraint('Ro1', blocks=['Bl2'], rmin=0, rmax=1),
            csts.RotationCoverageConstraint('Ro2', rmin=0, rmax=1),
            csts.RotationCountConstraint('Ro1', {'R1': (1, 1)}),
            csts.AllowedRootsConstraint('Ro1', allowed_roots=['Bl1'], suppress_for=['R1']),
        ],
    )
    assert status_suppressed in ('FEASIBLE', 'OPTIMAL'), (
        f"Expected FEASIBLE with suppress_for, got {status_suppressed}"
    )
    soln = sp.solutions[-1]
    assert soln['R1']['Bl2'] == 'Ro1', (
        f"R1 should be at Ro1 in Bl2, got {list(soln['R1'].values)}"
    )


def test_consecutive_count_suppress_for():
    """Suppressed resident can violate consecutive limit; others cannot."""
    residents = ['R1', 'R2']
    blocks = [f'Bl{i+1}' for i in range(6)]
    rotations = ['Ro1', 'Ro2']

    # ConsecutiveRotationCountConstraint requires Ro1 in groups of exactly 2.
    # R1 is suppressed so can do a single Ro1 (not consecutive).
    # Force R1 to exactly 1 Ro1 (which would violate consecutive=2 for R2).
    status, solver, solution_printer, model, wall_runtime = _solve(
        residents=residents,
        blocks=blocks,
        rotations=rotations,
        cst_list=[
            csts.RotationCoverageConstraint('Ro1', rmin=0, rmax=2),
            csts.RotationCoverageConstraint('Ro2', rmin=0, rmax=2),
            csts.RotationCountConstraint('Ro1', {'R1': (1, 1), 'R2': (2, 2)}),
            csts.ConsecutiveRotationCountConstraint('Ro1', count=2, suppress_for=['R1']),
        ],
    )

    assert status == 'FEASIBLE' or status == 'OPTIMAL', (
        f"Expected a solution but got {status}: R1 should be exempt from consecutive=2"
    )
    soln = solution_printer.solutions[-1]
    r1 = list(soln['R1'].values)
    assert r1.count('Ro1') == 1


def test_prerequisite_suppress_for():
    """Suppressed resident can be assigned without completing the prerequisite."""
    residents = ['R1', 'R2']
    blocks = ['Bl1', 'Bl2', 'Bl3']
    rotations = ['Ro1', 'Ro2', 'Ro3']

    # Ro3 requires Ro2 as prerequisite.
    # R1 is suppressed — they can do Ro3 at Bl1 (before any Ro2).
    # R2 must satisfy the prerequisite.
    status, solver, solution_printer, model, wall_runtime = _solve(
        residents=residents,
        blocks=blocks,
        rotations=rotations,
        cst_list=[
            csts.RotationCoverageConstraint('Ro1', rmin=0, rmax=2),
            csts.RotationCoverageConstraint('Ro2', rmin=0, rmax=2),
            csts.RotationCoverageConstraint('Ro3', rmin=0, rmax=2),
            # Force R1 to Ro3 at Bl1 (no Ro2 precedes it)
            csts.RotationCountConstraint('Ro1', {'R1': (0, 1), 'R2': (0, 1)}),
            csts.RotationCountConstraint('Ro2', {'R1': (0, 1), 'R2': (1, 1)}),
            csts.RotationCountConstraint('Ro3', {'R1': (1, 1), 'R2': (1, 1)}),
            csts.PrerequisiteRotationConstraint(
                rotation='Ro3',
                prereq_counts={('Ro2',): 1},
                prior_counts={'Ro2': {'R1': 0, 'R2': 0}},
                suppress_for=['R1'],
            ),
        ],
    )

    assert status == 'FEASIBLE' or status == 'OPTIMAL', (
        f"Expected a solution but got {status}"
    )
    soln = solution_printer.solutions[-1]
    r1 = list(soln['R1'].values)
    r2 = list(soln['R2'].values)
    # R1 can be in Ro3 at Bl1 (no Ro2 before it)
    assert 'Ro3' in r1
    # R2 must have Ro2 before any Ro3
    if 'Ro3' in r2:
        ro3_idx = r2.index('Ro3')
        assert 'Ro2' in r2[:ro3_idx], (
            f"R2 reached Ro3 at position {ro3_idx} without Ro2 prior: {r2}"
        )


def test_cooldown_suppress_for_regression():
    """CoolDownConstraint with suppress_for continues to work after refactor."""
    rotations = ['Ro1', 'Ro2', 'Ro3']
    residents = ['R1', 'R2', 'R3']
    blocks = ['Bl1', 'Bl2', 'Bl3', 'Bl4', 'Bl5', 'Bl6']

    COOLDOWN_LENGTH = 3

    status, solver, solution_printer, model, wall_runtime = _solve(
        residents=residents,
        blocks=blocks,
        rotations=rotations,
        cogrids={'backup': {'coverage': 2}},
        cst_list=[
            csts.RotationCoverageConstraint('Ro1', rmin=1, rmax=2),
            csts.RotationCoverageConstraint('Ro2', rmin=1, rmax=2),
            csts.RotationCoverageConstraint('Ro3', rmin=1, rmax=2),
            csts.RotationCountConstraint('Ro1', {res: (2, 2) for res in residents}),
            csts.RotationCountConstraint('Ro2', {res: (1, 2) for res in residents}),
            csts.RotationCountConstraint('Ro3', {res: (1, 2) for res in residents}),
            cogrid_csts.RotationBackupCountConstraint('Ro2', count=0),
            # R1 is suppressed — they can violate the cooldown
            csts.CoolDownConstraint(
                'Ro1',
                window_size=COOLDOWN_LENGTH,
                count=[1, 1],
                suppress_for=['R1'],
            ),
        ],
    )

    soln = solution_printer.solutions[-1]
    # R2 and R3 must respect the cooldown; R1 is exempt
    for res in ['R2', 'R3']:
        sched = soln[res]
        rot1_idx = np.where(sched.values == 'Ro1')[0]
        if len(rot1_idx) > 1:
            assert np.all((rot1_idx[1:] - rot1_idx[:-1]) >= COOLDOWN_LENGTH), (
                f"{res} violated cooldown: {list(sched.values)}"
            )
