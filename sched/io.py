import csv
import datetime

import numpy as np
import pandas as pd

from ortools.sat.python import cp_model

from . import csts


class BaseSolutionPrinter(cp_model.CpSolverSolutionCallback):

    def __init__(self, block_assigned, block_backup, residents, blocks, rotations):

        cp_model.CpSolverSolutionCallback.__init__(self)
        self._block_assigned = block_assigned
        self._block_backup = block_backup

        self._residents = residents
        self._blocks = blocks
        self._rotations = rotations


def compute_score_table(rankings, block_assigned, residents, blocks, rotations):

    score_table = []
    for res in residents:
        score_row = [res, ]
        for blk in blocks:
            score_row.append(0)
            for rot in rotations:
                score_row[-1] += (
                    rankings.get(res, {}).get(rot, 0) *
                    block_assigned[(res, blk, rot)]
                )
        score_table.append(score_row)

    return score_table


class BlockSchedulePartialSolutionPrinter(BaseSolutionPrinter):

    def __init__(
            self, block_assigned, block_backup, residents, blocks, rotations, outfile,
            rankings,
            solution_limit=Ellipsis
            ):

        super().__init__(block_assigned, block_backup, residents, blocks, rotations)

        self._outfile = outfile

        self._column_width = max(
            max(len(b) for b in blocks),
            max(len(r) for r in rotations)
        )

        self._solution_count = 0
        self._time_to_first_solution = None
        self._solution_limit = solution_limit
        self._rankings = rankings

    def on_solution_callback(self):
        self._solution_count += 1

        print(f"Solution {self._solution_count:02d} at {datetime.datetime.now()} w objective value {self.ObjectiveValue()}")

        rows = [[''] + self._residents]
        for block in self._blocks:
            row = [block]
            for resident in self._residents:
                for rotation in self._rotations:
                    if self.Value(self._block_assigned[(resident, block, rotation)]):
                        # row.append(self._rotations.index(rotation))
                        row.append(rotation)
                        if self.Value(self._block_backup[(resident, block)]):
                            row[-1] += '+'
            rows.append(row)

        with open(self._outfile.replace('npz', 'csv') % self._solution_count, 'w') as f:
            writer = csv.writer(f, delimiter=',')
            for row in rows:
                writer.writerow(row)

        backup_array = []
        for resident in self._residents:
            backup_array.append(
                [self.Value(self._block_backup[(resident, block)]) for block in self._blocks]
            )
            # print(
            #     ''.join(['+' if self.Value(self._block_backup[(resident, block)]) else '-'
            #              for block in self._blocks])
            #  )

        ll = [r[1:] for r in rows[1:]]
        a = np.array([r[1:] for r in rows[1:]]) #, dtype='int16')
        # print(a.T)

        score_table = compute_score_table(
            self._rankings,
            {k: self.Value(v) for k, v in self._block_assigned.items()},
            self._residents, self._blocks, self._rotations
        )

        with open(self._outfile.replace('.npz', '-scores.csv') % self._solution_count, 'w') as f:
            writer = csv.writer(f, delimiter=',')
            writer.writerow(['']+self._blocks)
            for row in score_table:
                writer.writerow(row)

            print("  - worst resident utility:", max([sum(row[1:]) for row in score_table]))
            print("  - best resident utility:", min([sum(row[1:]) for row in score_table]))

        # for row in score_table:
        #     print('['+','.join([str(i) for i in row])+'],')


        if (self._solution_limit is not Ellipsis) and \
           (self._solution_count >= self._solution_limit):
            self.StopSearch()


    def solution_count(self):
        return self._solution_count


def coverage_constraints_from_csv(fname, rmin_or_rmax):
    coverage_min = pd.read_csv(fname, header=0, index_col=0, comment='#')

    constraints = []
    for block, rot_dict in coverage_min.to_dict().items():
        for rot, ct in rot_dict.items():
            if not np.isnan(ct):
                constraints.append(
                    csts.RotationCoverageConstraint(
                        rotation=rot, blocks=[block], **{rmin_or_rmax: int(ct)})
                )

    return constraints


def pin_constraints_from_csv(fname):

    coverage_pins = pd.read_csv(fname, header=0, index_col=0, comment='#')

    constraints = []
    for block, rot_dict in coverage_pins.to_dict().items():
        for resident, rotation in rot_dict.items():
            if hasattr(rotation, '__len__'):
                # TODO: it sucks this is hard-coded
                if block == "Rotation(s) Somewhere":
                    constraints.append(
                        csts.PinnedRotationConstraint(resident, [], rotation)
                    )
                else:
                    constraints.append(
                        csts.PinnedRotationConstraint(resident, [block], rotation)
                    )

    return constraints


def rankings_from_csv(fname):
    ranking_df = pd.read_csv(fname, header=0, index_col=0, comment='#')

    # TODO: sucks
    del ranking_df['SICU-E4 CBY (additional)']
    del ranking_df['Medical Writing CBY']

    ranking_df[ranking_df == 1] = -2
    ranking_df[ranking_df == 2] = -1
    ranking_df[ranking_df == 3] = 5

    for c in ranking_df.columns:
        ranking_df[c] = ranking_df[c].fillna(0)
        ranking_df[c] = ranking_df[c].astype(int)

    return ranking_df.T.to_dict()
