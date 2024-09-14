import datetime
import logging
import csv

import pandas as pd

from ortools.sat.python import cp_model

from . import io

logger = logging.getLogger(__name__)


class BaseSolutionPrinter(cp_model.CpSolverSolutionCallback):

    def __init__(self, grids, solution_limit=None):

        cp_model.CpSolverSolutionCallback.__init__(self)

        self._block_assigned = grids['main']['variables']

        if grids.get('backup', None):
            self._block_backup = grids['backup'].get('variables', None)
        else:
            self._block_backup = None

        if grids.get('vacation', None):
            self._vacation_assigned = grids['vacation']['variables']
        else:
            self._vacation_assigned = None

        self._residents = grids['main']['dimensions']['residents']
        self._blocks = grids['main']['dimensions']['blocks']
        self._rotations = grids['main']['dimensions']['rotations']

        self._solution_limit = solution_limit
        self._solution_count = 0

    def on_solution_callback_initial(self):

        self._solution_count += 1
        print(f"Solution {self._solution_count:02d} at {datetime.datetime.now()} w objective value {self.ObjectiveValue()}")
        logger.info(f"Solution {self._solution_count:02d} at {datetime.datetime.now()} w objective value {self.ObjectiveValue()}")

    def check_for_stop_iterating(self):

        if (self._solution_limit is not Ellipsis) and \
            (self._solution_limit is not None) and \
           (self._solution_count >= self._solution_limit):
            self.StopSearch()

    def solution_count(self):
        return self._solution_count

    def df_from_solution(self):

        rows = []
        for block in self._blocks:
            row = []
            for resident in self._residents:
                for rotation in self._rotations:
                    if self.Value(self._block_assigned[(resident, block, rotation)]):
                        row.append(rotation)
                        if self._block_backup and self.Value(self._block_backup[(resident, block)]):
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

    def vacation_df(self):

        if self._vacation_assigned:
            d = [
                k + (self.Value(v),) for k, v in self._vacation_assigned.items()
            ]

            df = pd.DataFrame.from_records(
                d, columns=['resident', 'week', 'rotation', 'on_vacation'])

            print(df[df['on_vacation'] == 1].sort_values(['week']))

            print(df.groupby('resident')['on_vacation'].sum())
            print(df.groupby('rotation')['on_vacation'].sum())

            return df


class JugScheduleSolutionPrinter(BaseSolutionPrinter):

    def __init__(self, scores, *args, **kwargs):

        super().__init__(*args, **kwargs)

        self._scores = scores

        # _solution count is set in BaseSolutionPrinter
        # self._solution_count = 0
        self._solution_scores = []
        self._solutions = []
        self._vacations = []

    def on_solution_callback(self):

        self.on_solution_callback_initial()

        solution_df = self.df_from_solution()
        self._solutions.append(solution_df)
        self._vacations.append(self.vacation_df())

        if self._scores is not None:

            scores_df = self.df_from_scores()
            self._solution_scores.append(scores_df)

            print("  - worst resident utility:", scores_df.sum(axis=1).max())
            print("  - best resident utility:", scores_df.sum(axis=1).min())
            logger.info("  - worst resident utility:", scores_df.sum(axis=1).max())
            logger.info("  - best resident utility:", scores_df.sum(axis=1).min())

        self.check_for_stop_iterating()


class BlockSchedulePartialSolutionPrinter(BaseSolutionPrinter):

    def __init__(self, grids, outfile, scores, solution_limit=Ellipsis):

        super().__init__(grids, solution_limit=solution_limit)

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

        self.on_solution_callback_initial()

        solution_df = self.df_from_solution()

        solution_df.to_csv(
            self._outfile.replace('npz', 'csv') % self._solution_count
        )

        if self._scores is not None:
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

        self.check_for_stop_iterating()
