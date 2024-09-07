from functools import partial

import numpy as np
import pandas as pd

from . import solve, io, csts, callback


class TestSolnPrinter(callback.BaseSolutionPrinter):
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
                        if self.Value(self._block_backup[(resident, block)]):
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
            csts.RotationBackupCountConstraint('Ro1', count=0)
        ],
        soln_printer=TestSolnPrinter,
        objective_fn=partial(
            alldiff_3x3x3_obj, residents=residents,
            blocks=blocks, rotations=rotations),
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
            csts.RotationBackupCountConstraint('Ro2', count=0),
            csts.CoolDownConstraint('Ro1', window_size=COOLDOWN_LENGTH, count=[1,1])
        ],
        soln_printer=TestSolnPrinter,
        objective_fn=partial(
            alldiff_3x3x3_obj, residents=residents,
            blocks=blocks, rotations=rotations),
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

    assert solver.ObjectiveValue() == -18
