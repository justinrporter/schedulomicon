import csv
import datetime
import numpy as np

from ortools.sat.python import cp_model


class BaseSolutionPrinter(cp_model.CpSolverSolutionCallback):

    def __init__(self, block_assigned, block_backup, residents, blocks, rotations):

        cp_model.CpSolverSolutionCallback.__init__(self)
        self._block_assigned = block_assigned
        self._block_backup = block_backup

        self._residents = residents
        self._blocks = blocks
        self._rotations = rotations


class BlockSchedulePartialSolutionPrinter(BaseSolutionPrinter):

    def __init__(
            self, block_assigned, block_backup, residents, blocks, rotations, outfile,
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

    def on_solution_callback(self):
        self._solution_count += 1

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
            print(
                ''.join(['+' if self.Value(self._block_backup[(resident, block)]) else '-'
                         for block in self._blocks])
             )
        print(np.array(backup_array).shape)
        print(np.array(backup_array).sum(axis=1))
        print(np.array(backup_array).sum(axis=0))

        ll = [r[1:] for r in rows[1:]]
        a = np.array([r[1:] for r in rows[1:]]) #, dtype='int16')
        print(a.T)

        print("Anesthesia CBY+", np.count_nonzero(a == "Anesthesia CBY+"))

        # fname = self._outfile.replace('csv', 'npz') % 0

        # if self._solution_count == 1:
        #     a_full = a
        # else:
        #     a_full = np.load(fname)['a']
        #     a_full = np.dstack([a_full, a])

        # np.savez(fname, a=a_full)

        print(f"Solution {self._solution_count:02d} at {datetime.datetime.now()} w objective value {self.ObjectiveValue()}")

        if (self._solution_limit is not Ellipsis) and \
           (self._solution_count >= self._solution_limit):
            self.StopSearch()


    def solution_count(self):
        return self._solution_count
