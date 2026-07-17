from functools import partial

import numpy as np
import pandas as pd

from ortools.sat.python import cp_model

from . import solve, io, csts, callback, cogrid_csts


class SolnPrinterTest(callback.BaseSolutionPrinter):
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
                        if self._block_backup and self.Value(self._block_backup[(resident, block)]):
                            record[-1] += '+'
            records.append(record)

        self.solutions.append(pd.DataFrame.from_records(
            records, index=self._blocks, columns=self._residents
        ))

def alldiff_3x3x3_obj(block_assigned, residents, blocks, rotations):

    obj = 0
    for i, res in enumerate(residents):
        for j, rot in enumerate(rotations):
            #           B1  B2  B3
            # R1 ranks:  0, -1, -2
            # R2 ranks: -1, -2,  0
            # R3 ranks: -2,  0, -1
            score = -((i + j) % len(residents))
            for blk in blocks:
                obj += score * block_assigned[(res, blk, rot)]

    return obj


def test_small_puzzle():

    residents = ['R1', 'R2', 'R3']
    rotations = ['Ro1', 'Ro2', 'Ro3']
    blocks = ['Bl1', 'Bl2', 'Bl3']

    status, solver, solution_printer, model, wall_runtime = solve.solve(
        residents=residents,
        blocks=blocks,
        rotations=rotations,
        groups_array=[],
        cst_list=[
            csts.RotationCoverageConstraint(
                rot, rmin=1, rmax=1
            ) for rot in rotations
        ] + [
            csts.RotationCountConstraint(
                rot, {res: (1, 1) for res in residents}
            ) for rot in rotations
        ] + [
            cogrid_csts.RotationBackupCountConstraint('Ro1', count=0)
        ],
        soln_printer=SolnPrinterTest,
        score_functions=[
            ('main', partial(alldiff_3x3x3_obj, residents=residents,
                             blocks=blocks, rotations=rotations))],
        n_processes=1,
        cogrids={'backup': {'coverage': 2}},
        max_time_in_mins=5,
        hint=None
    )

    soln = solution_printer.solutions[-1]
    print(soln)

    assert all(soln.R1.values == ['Ro3+',  'Ro1', 'Ro2+'])
    assert all(soln.R2.values == ['Ro2+', 'Ro3+',  'Ro1'])
    assert all(soln.R3.values == [ 'Ro1', 'Ro2+', 'Ro3+'])

    assert solver.ObjectiveValue() == -9


def test_cooldown_constraint():

    rotations = ['Ro1', 'Ro2', 'Ro3']
    residents=['R1', 'R2', 'R3']
    blocks=['Bl1', 'Bl2', 'Bl3','Bl4','Bl5','Bl6']

    COOLDOWN_LENGTH = 3

    status, solver, solution_printer, model, wall_runtime = solve.solve(
        residents=residents,
        blocks=blocks,
        rotations=rotations,
        groups_array=[],
        cst_list=[
            csts.RotationCoverageConstraint(
                rot, rmin=1, rmax=2
            ) for rot in rotations
        ] + [
            csts.RotationCountConstraint(
                'Ro1', {res: (2, 2) for res in residents}
            )
        ] + [
            csts.RotationCountConstraint(
                rot, {res: (1, 2) for res in residents}
            ) for rot in rotations if rot != 'Ro1'
        ] + [
            cogrid_csts.RotationBackupCountConstraint('Ro2', count=0),
            csts.CoolDownConstraint('Ro1', window_size=COOLDOWN_LENGTH, count=[1,1])
        ],
        soln_printer=SolnPrinterTest,
        score_functions=[],
        n_processes=1,
        cogrids={'backup': {'coverage': 2}},
        max_time_in_mins=5,
        hint=None
    )
    soln = solution_printer.solutions[-1]
    print(soln)
    print(solution_printer.solutions)

    schedules = [soln.R1, soln.R2, soln.R3]

    for sched in schedules:
        rot1_idx = np.where((sched.values == 'Ro1') |
                             (sched.values == 'Ro1+'))[0]
        assert np.all((rot1_idx[1:] - rot1_idx[:-1]) >= COOLDOWN_LENGTH)


def test_consecutive_rotation_with_coverage():

    rotations = [f'Ro{i+1}' for i in range(6)]
    residents=['R1', 'R2', 'R3']
    blocks=['Bl1', 'Bl2', 'Bl3','Bl4','Bl5', 'Bl6']

    status, solver, solution_printer, model, wall_runtime = solve.solve(
        residents=residents,
        blocks=blocks,
        rotations=rotations,
        groups_array=[],
        cst_list=[
            csts.RotationCoverageConstraint(
                rot, rmin=1, rmax=1
            ) for rot in ['Ro1', 'Ro2']
        ] + [
            csts.RotationCoverageConstraint(
                'Ro2', rmin=1, rmax=1
            )
        ] + [
            csts.RotationCountConstraint(
                rot, {res: (0, 1) for res in residents}
            ) for rot in rotations if rot not in ['Ro1', 'Ro2']
        ] + [
            csts.ConsecutiveRotationCountConstraint('Ro1', count=3)
        ] + [
            csts.ConsecutiveRotationCountConstraint('Ro2', count=2)
        ],
        soln_printer=SolnPrinterTest,
        score_functions=[],
        n_processes=1,
        cogrids={'backup': {'coverage': 0}},
        max_time_in_mins=5,
        hint=None
    )

    assert len(solution_printer.solutions)
    soln = solution_printer.solutions[-1]
    print(soln)

    schedules = [soln.R1, soln.R2, soln.R3]
    ro1_allowed_patterns = [
        (1, 1, 1, 0, 0, 0),
        (0, 0, 0, 1, 1, 1),
        (0, 0, 0, 0, 0, 0),
    ]

    ro2_allowed_patterns = [
        (1, 1, 0, 0, 0, 0),
        (0, 0, 0, 0, 1, 1),
        (0, 0, 1, 1, 0, 0),
    ]

    for s in schedules:
        assert tuple((s == 'Ro1')) in ro1_allowed_patterns
        assert tuple((s == 'Ro2')) in ro2_allowed_patterns


def test_consecutive_with_forbidden_roots():

    rotations = [f'Ro{i+1}' for i in range(2)]
    residents=['R1', 'R2']
    blocks=[f'Bl{i+1}' for i in range(6)]

    status, solver, solution_printer, model, wall_runtime = solve.solve(
        residents=residents,
        blocks=blocks,
        rotations=rotations,
        groups_array=[],
        cst_list=[
            csts.RotationCountConstraint(
                "Ro1", {'R1': (4, 4)}
            ),
            csts.ConsecutiveRotationCountConstraint(
                'Ro1', count=4,  forbidden_roots=['Bl1', 'Bl3']
            ),
            csts.RotationCoverageConstraint(
                'Ro1', rmin=0, rmax=1
            )
        ],
        soln_printer=SolnPrinterTest,
        score_functions=[
            ('main', partial(alldiff_3x3x3_obj, residents=residents,
                             blocks=blocks, rotations=rotations))],
        n_processes=1,
        cogrids={'backup': {'coverage': 0}},
        max_time_in_mins=5,
        hint=None
    )

    assert len(solution_printer.solutions)
    soln = solution_printer.solutions[-1]
    print(soln)

    schedules = [soln.R1, soln.R2]

    assert tuple(soln.R1) == ('Ro2', 'Ro1', 'Ro1', 'Ro1', 'Ro1', 'Ro2')
    assert tuple(soln.R2) == ('Ro2', 'Ro2', 'Ro2', 'Ro2', 'Ro2', 'Ro2')


def test_group_count_per_resident_per_window():

    rotations = [f'Ro{i+1}' for i in range(3)]
    residents=['R1', 'R2']
    blocks=[f'Bl{i+1}' for i in range(2)]

    status, solver, solution_printer, model, wall_runtime = solve.solve(
        residents=residents,
        blocks=blocks,
        rotations=rotations,
        groups_array=[],
        cst_list=[
            csts.RotationCountConstraint(
                "Ro1", {'R1': (1, 1), "R2": (2, 2)}
            ),
            csts.GroupCountPerResidentPerWindow(
                rotations_in_group=['Ro1'],
                resident_to_count={'R1': (1, 1), 'R2': (2, 2)},
                window_size=len(blocks),
            )
        ],
        soln_printer=SolnPrinterTest,
        score_functions=[
            ('main', partial(alldiff_3x3x3_obj, residents=residents,
                             blocks=blocks, rotations=rotations))],
        n_processes=1,
        cogrids={'backup': {'coverage': 0}},
        max_time_in_mins=5,
        hint=None
    )

    assert len(solution_printer.solutions)
    soln = solution_printer.solutions[-1]
    print(soln)

    schedules = [soln.R1, soln.R2]

    assert tuple(soln.R1) in (('Ro2', 'Ro1'), ('Ro1', 'Ro2'))
    assert tuple(soln.R2) == ('Ro1', 'Ro1')


def test_ineligible_after_constraint():

    rotations = ['Ro1', 'Ro2']
    residents=['R1', 'R2']
    blocks=['Bl1', 'Bl2', 'Bl3']

    def max_ro1_count(variables):
        obj = 0
        for res in residents:
            for blk in blocks:
                obj -= variables[res, blk, 'Ro1']
        return obj

    status, solver, solution_printer, model, wall_runtime = solve.solve(
        residents=residents, blocks=blocks, rotations=rotations,
        groups_array=[],
        cst_list=[
            csts.IneligibleAfterConstraint(
                "Ro1", {('Ro1',): 1}
            ),
            csts.RotationCoverageConstraint(
                'Ro1', rmin=0, rmax=0, blocks=['Bl3']
            )
        ],
        soln_printer=SolnPrinterTest,
        score_functions=[('main', max_ro1_count)],
        n_processes=1,
        cogrids={'backup': {'coverage': 0}},
        max_time_in_mins=5,
        hint=None
    )

    assert len(solution_printer.solutions)
    soln = solution_printer.solutions[-1]
    print(soln)

    schedules = [soln.R1, soln.R2]

    assert tuple(soln.R1) in [('Ro1', 'Ro2', 'Ro2'),
                              ('Ro2', 'Ro1', 'Ro2')]
    assert tuple(soln.R2) in [('Ro1', 'Ro2', 'Ro2'),
                              ('Ro2', 'Ro1', 'Ro2')]


def test_must_be_preceded_by_feasible():
    """Target in block 2 requires Prep in block 1 immediately before it."""
    residents = ['R1']
    rotations = ['Prep', 'Target', 'Other']
    blocks = ['Bl1', 'Bl2', 'Bl3']

    status, solver, solution_printer, model, wall_runtime = solve.solve(
        residents=residents,
        blocks=blocks,
        rotations=rotations,
        groups_array=[],
        cst_list=[
            csts.MustBePrecededByRotationConstraint('Target', ['Prep']),
            csts.RotationCoverageConstraint('Target', rmin=1, rmax=1, blocks=['Bl2']),
            csts.RotationCoverageConstraint('Prep', rmin=0, rmax=1),
            csts.RotationCoverageConstraint('Other', rmin=0, rmax=3),
        ],
        soln_printer=SolnPrinterTest,
        score_functions=[],
        n_processes=1,
        cogrids={'backup': {'coverage': 0}},
        max_time_in_mins=1,
        hint=None
    )

    assert len(solution_printer.solutions)
    soln = solution_printer.solutions[-1]
    schedule = tuple(soln.R1)
    assert schedule[1] == 'Target'
    assert schedule[0] == 'Prep'


def test_must_be_preceded_by_infeasible():
    """Target in block 1 (first block, no predecessor) must be INFEASIBLE."""
    residents = ['R1']
    rotations = ['Prep', 'Target', 'Other']
    blocks = ['Bl1', 'Bl2', 'Bl3']

    status, solver, solution_printer, model, wall_runtime = solve.solve(
        residents=residents,
        blocks=blocks,
        rotations=rotations,
        groups_array=[],
        cst_list=[
            csts.MustBePrecededByRotationConstraint('Target', ['Prep']),
            csts.RotationCoverageConstraint('Target', rmin=1, rmax=1, blocks=['Bl1']),
            csts.RotationCoverageConstraint('Prep', rmin=0, rmax=1),
            csts.RotationCoverageConstraint('Other', rmin=0, rmax=3),
        ],
        soln_printer=SolnPrinterTest,
        score_functions=[],
        n_processes=1,
        cogrids={'backup': {'coverage': 0}},
        max_time_in_mins=1,
        hint=None
    )

    assert status == 'INFEASIBLE'


def test_consecutive_rotation_constraint_with_allowed_roots():
    residents = ['R1']
    blocks = [f'Bl{i+1}' for i in range(6)]
    rotations = ['Ro1', 'Ro2']

    status, solver, solution_printer, model, wall_runtime = solve.solve(
        residents=residents,
        blocks=blocks,
        rotations=rotations,
        groups_array=[],
        cst_list=[
            csts.RotationCountConstraint('Ro1', {'R1': (2, 2)}),
            csts.RotationCoverageConstraint('Ro1', rmin=0, rmax=1),
            csts.ConsecutiveRotationCountConstraint(
                'Ro1', count=2, allowed_roots=['Bl1', 'Bl3', 'Bl5']
            ),
        ],
        soln_printer=SolnPrinterTest,
        score_functions=[],
        n_processes=1,
        cogrids={},
        max_time_in_mins=5,
        hint=None,
    )

    assert len(solution_printer.solutions)
    soln = solution_printer.solutions[-1]
    ro1 = tuple(soln.R1)
    for i, rot in enumerate(ro1):
        if rot == 'Ro1' and (i == 0 or ro1[i-1] != 'Ro1'):
            assert blocks[i] in ('Bl1', 'Bl3', 'Bl5'), \
                f"Ro1 sequence started at {blocks[i]}, not an allowed root"


def _hint_grids(model):
    """A main grid (2 vars) and a backup grid (1 var) on a bare model."""
    grids = {
        'main': {
            'variables': {
                ('R1', 'Bl1', 'Ro1'): model.NewBoolVar('m0'),
                ('R1', 'Bl1', 'Ro2'): model.NewBoolVar('m1'),
            }
        },
        'backup': {
            'variables': {
                ('R1', 'Bl1'): model.NewBoolVar('b0'),
            }
        },
    }
    return grids


def _hints_by_var_index(model):
    proto = model.Proto().solution_hint
    return dict(zip(proto.vars, proto.values))


def test_add_result_as_hint_dense():
    model = cp_model.CpModel()
    grids = _hint_grids(model)

    hint = {
        'main': {
            ('R1', 'Bl1', 'Ro1'): 1,
            ('R1', 'Bl1', 'Ro2'): 0,
        },
        'backup': {
            ('R1', 'Bl1'): 1,
        },
    }
    solve.add_result_as_hint(model, grids, hint)

    hints = _hints_by_var_index(model)
    assert hints[grids['main']['variables'][('R1', 'Bl1', 'Ro1')].Index()] == 1
    assert hints[grids['main']['variables'][('R1', 'Bl1', 'Ro2')].Index()] == 0
    assert hints[grids['backup']['variables'][('R1', 'Bl1')].Index()] == 1
    assert len(hints) == 3


def test_add_result_as_hint_sparse_zero_fill():
    # A sparse hint (only nonzero entries) must still hint every model
    # variable of a present grid, with absent keys hinted as 0.
    model = cp_model.CpModel()
    grids = _hint_grids(model)

    hint = {
        'main': {('R1', 'Bl1', 'Ro1'): 1},
        'backup': {},
    }
    solve.add_result_as_hint(model, grids, hint)

    hints = _hints_by_var_index(model)
    assert hints[grids['main']['variables'][('R1', 'Bl1', 'Ro1')].Index()] == 1
    assert hints[grids['main']['variables'][('R1', 'Bl1', 'Ro2')].Index()] == 0
    assert hints[grids['backup']['variables'][('R1', 'Bl1')].Index()] == 0
    assert len(hints) == 3


def test_add_result_as_hint_skips_absent_grids():
    # A main-only hint applied to a model with cogrids must not raise;
    # only the main grid's variables get hinted.
    model = cp_model.CpModel()
    grids = _hint_grids(model)

    hint = {'main': {('R1', 'Bl1', 'Ro1'): 1}}
    solve.add_result_as_hint(model, grids, hint)

    hints = _hints_by_var_index(model)
    main_vars = grids['main']['variables']
    assert set(hints) == {v.Index() for v in main_vars.values()}
    assert hints[main_vars[('R1', 'Bl1', 'Ro1')].Index()] == 1
    assert hints[main_vars[('R1', 'Bl1', 'Ro2')].Index()] == 0


def test_max_active_blocks_constraint():
    # 3 residents over 4 blocks; Ro1 is attractive enough that without a cap
    # it would appear in all 4 blocks. With max_active_blocks=2 it must be
    # active in at most 2 blocks.
    residents = ['R1', 'R2', 'R3']
    blocks = [f'Bl{i+1}' for i in range(4)]
    rotations = ['Ro1', 'Ro2']

    status, solver, solution_printer, model, wall_runtime = solve.solve(
        residents=residents,
        blocks=blocks,
        rotations=rotations,
        groups_array=[],
        cst_list=[
            csts.RotationCoverageConstraint('Ro1', rmin=0, rmax=3),
            csts.RotationCoverageConstraint('Ro2', rmin=0, rmax=3),
            csts.MaxActiveBlocksConstraint('Ro1', max_blocks=2),
        ],
        soln_printer=SolnPrinterTest,
        score_functions=[],
        n_processes=1,
        cogrids={},
        max_time_in_mins=5,
        hint=None,
    )

    assert len(solution_printer.solutions)
    soln = solution_printer.solutions[-1]

    active_blocks = sum(
        1 for b in blocks
        if any(soln.loc[b, res] == 'Ro1' for res in residents)
    )
    assert active_blocks <= 2, \
        f"Ro1 was active in {active_blocks} blocks, expected at most 2"
