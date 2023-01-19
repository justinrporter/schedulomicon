import pandas as pd

from . import solve, io, csts


class TestSolnPrinter(io.BaseSolutionPrinter):
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


def alldiff_3x3x3_obj(block_assigned, rankings, residents, blocks, rotations):

    obj = 0
    for i, res in enumerate(residents):
        for j, rot in enumerate(rotations):
            # R1 ranks:  0, -1, -2
            # R2 ranks: -1, -2,  0
            # R3 ranks: -2,  0, -1
            score = -((i + j) % len(residents))
            for blk in blocks:
                obj += score * block_assigned[(res, blk, rot)]

    return obj


def test_small_puzzle():

    rotations = ['Ro1', 'Ro2', 'Ro3']
    
    solver, solution_printer = solve.solve(
        residents=['R1', 'R2', 'R3'],
        blocks=['Bl1', 'Bl2', 'Bl3','Bl4','Bl5','Bl6'],
        rotations=rotations,
        rankings={},
        groups=[],
        cst_list=[
            csts.RotationCoverageConstraint(
                rot, rmin=1, rmax=2
            ) for rot in rotations
        ] + [
            csts.RotationCountConstraint(
                'Ro1', n_min=2, n_max=2
            )
        ] + [
            csts.RotationCountConstraint(
                rot, n_min=1, n_max=2
            ) for rot in rotations if rot != 'Ro1'
        ] + [
            csts.RotationBackupCountConstraint('Ro2', count=0)
        ] + [              
            csts.CoolDownConstraint('Ro1', window_size = 3)
        ],
        soln_printer=TestSolnPrinter,
        objective_fn=alldiff_3x3x3_obj,
        n_processes=1
    )
    soln = solution_printer.solutions[-1]
    print(soln)

    assert all(soln.R1.values == ['Ro2',  'Ro1', 'Ro3+', 'Ro2', 'Ro1+', 'Ro3'])
    assert all(soln.R2.values == ['Ro1+',  'Ro3', 'Ro2', 'Ro1', 'Ro3+', 'Ro2'])
    assert all(soln.R3.values == ['Ro3+',  'Ro2', 'Ro1', 'Ro3+', 'Ro2', 'Ro1'])

    assert solver.ObjectiveValue() == -18
