import datetime
import logging
import csv

import pandas as pd

from ortools.sat.python import cp_model

from . import io

logger = logging.getLogger(__name__)


class BaseSolutionPrinter(cp_model.CpSolverSolutionCallback):

    def __init__(self, block_assigned, block_backup, residents, blocks, rotations):

        cp_model.CpSolverSolutionCallback.__init__(self)
        self._block_assigned = block_assigned
        self._block_backup = block_backup

        self._residents = residents
        self._blocks = blocks
        self._rotations = rotations

    def df_from_solution(self):

        rows = []
        for block in self._blocks:
            row = []
            for resident in self._residents:
                for rotation in self._rotations:
                    if self.Value(self._block_assigned[(resident, block, rotation)]):
                        row.append(rotation)
                        if self.Value(self._block_backup[(resident, block)]):
                            row[-1] += '+'
            rows.append(row)

        df = pd.DataFrame.from_records(
            rows,
            columns=self._residents,
            index=self._blocks
        )

        return df

    def df_from_scores(self):

        block_assigned = {k: self.Value(v) for k, v in self._block_assigned.items()}

        score_table = []
        for res in self._residents:
            score_row = []
            for blk in self._blocks:
                score_row.append(0)
                for rot in self._rotations:
                    assert (res, blk, rot) in self._scores, f'{(res, blk, rot)} not in in self._scores'
                    score_row[-1] += (
                        self._scores[(res, blk, rot)] *
                        block_assigned[(res, blk, rot)]
                    )
            score_table.append(score_row)

        df = pd.DataFrame.from_records(
            score_table,
            columns=self._blocks,
            index=self._residents
        )

        return df

class JugScheduleSolutionPrinter(BaseSolutionPrinter):

    def __init__(
            self, block_assigned, block_backup, residents, blocks, rotations,
            scores, solution_limit=Ellipsis
            ):

        super().__init__(block_assigned, block_backup, residents, blocks, rotations)

        self._scores = scores

        self._solution_count = 0
        self._solution_scores = []
        self._solutions = []

    def on_solution_callback(self):
        self._solution_count += 1
        logger.info(f"Solution {self._solution_count:02d} at {datetime.datetime.now()} w objective value {self.ObjectiveValue()}")

        solution_df = self.df_from_solution()

        scores_df = self.df_from_scores()

        self._solution_scores.append(scores_df)
        self._solutions.append(solution_df)

        logger.info("  - worst resident utility:", scores_df.sum(axis=1).max())
        logger.info("  - best resident utility:", scores_df.sum(axis=1).min())


class BlockSchedulePartialSolutionPrinter(BaseSolutionPrinter):

    def __init__(
            self, block_assigned, block_backup, residents, blocks, rotations, outfile,
            scores, solution_limit=Ellipsis
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
        self._scores = scores

    def on_solution_callback(self):
        self._solution_count += 1

        logger.info(f"Solution {self._solution_count:02d} at {datetime.datetime.now()} w objective value {self.ObjectiveValue()}")

        solution_df = self.df_from_solution()

        solution_df.to_csv(
            self._outfile.replace('npz', 'csv') % self._solution_count
        )

        score_table = io.compute_score_table(
            self._scores,
            {k: self.Value(v) for k, v in self._block_assigned.items()},
            self._residents, self._blocks, self._rotations
        )

        with open(self._outfile.replace('.npz', '-scores.csv') % self._solution_count, 'w') as f:
            writer = csv.writer(f, delimiter=',')
            writer.writerow(['']+self._blocks)
            for row in score_table:
                writer.writerow(row)

            logger.info("  - worst resident utility:", max([sum(row[1:]) for row in score_table]))
            logger.info("  - best resident utility:", min([sum(row[1:]) for row in score_table]))

        # for row in score_table:
        #     print('['+','.join([str(i) for i in row])+'],')

        if (self._solution_limit is not Ellipsis) and \
           (self._solution_count >= self._solution_limit):
            self.StopSearch()


    def solution_count(self):
        return self._solution_count

