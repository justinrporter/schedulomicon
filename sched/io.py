import csv
import datetime

import numpy as np
import pandas as pd

from ortools.sat.python import cp_model

from . import csts


def process_config(config):

    residents = list(config['residents'].keys())
    blocks = list(config['blocks'].keys())
    rotations = list(config['rotations'].keys())

    groups = []
    for rot, params in config['rotations'].items():
        if not params:
            continue
        groups.extend(params.get('groups', []))
    groups = list(set(groups))

    return residents, blocks, rotations, groups


def generate_resident_constraints(config):

    cst_list = []

    for res, params in config['residents'].items():
        if not params:
            continue

        if 'pin_rotation' in params:
            for pinned_rotation, pinned_blocks in params['pin_rotation'].items():
                cst_list.append(
                    csts.PinnedRotationConstraint(res, pinned_blocks, pinned_rotation)
                )

    return cst_list


def generate_backup_constraints(
    config, n_residents_needed=2, backup_group_name='backup_eligible'):

    constraints = []

    for block, blk_params in config['blocks'].items():
        if blk_params.get('backup_required', True):
            constraints.append(
                csts.BackupRequiredOnBlockBackupConstraint(
                    block=block,
                    n_residents_needed=n_residents_needed
                )
            )

    for rotation, rot_params in config['rotations'].items():
        if 'backup_count' in rot_params:
            ct = int(rot_params['backup_count'])
            constraints.append(
                csts.RotationBackupCountConstraint(rotation, ct)
            )

    backup_eligible = {}
    for rotation, rot_params in config['rotations'].items():
        backup_eligible[rotation] = backup_group_name in rot_params.get('groups', {})
    constraints.append(
        csts.BackupEligibleBlocksBackupConstraint(backup_eligible)
    )

    return constraints


def generate_constraints_from_configs(config):

    constraints = []

    constraints.extend(generate_rotation_constraints(config))

    constraints.extend(generate_resident_constraints(config))

    for cst in config['group_constraints']:
        if cst['kind'] == 'all_group_count_per_resident':
            constraints.append(
                csts.GroupCountPerResidentPerWindow(
                    rotations_in_group=resolve_group(cst['group'], config['rotations']),
                    n_min=cst['count'][0], n_max=cst['count'][1], window_size = len(config['blocks']))
            )
        if cst['kind'] == 'window_group_count_per_resident':
            constraints.append(
                csts.GroupCountPerResidentPerWindow(
                    rotations_in_group=resolve_group(cst['group'], config['rotations']),
                    n_min=cst['count'][0], n_max=cst['count'][1], window_size = cst['window_size'])
            )

        if cst['kind'] == 'time_to_first':
            constraints.append(
                csts.TimeToFirstConstraint(
                    rotations_in_group=resolve_group(cst['group'], config['rotations']),
                    window_size = cst['window_size'])
            )
    return constraints


def handle_count_specification(count_config, n_items):

    if 'min' in count_config and 'max' in count_config:
        rmin = expand_to_length_if_needed(count_config['min'], n_items)
        rmax = expand_to_length_if_needed(count_config['max'], n_items)
    else:
        rmin = expand_to_length_if_needed(count_config[0], n_items)
        rmax = expand_to_length_if_needed(count_config[1], n_items)

    return rmin, rmax


def expand_to_length_if_needed(var, length):

    if not hasattr(var, '__len__'):
        return [var]*length
    else:
        assert len(var) == length
        return var


def resolve_group(group, rotation_config):

    rots = [
        r for r, params in rotation_config.items()
        if params and group in params.get('groups', [])
    ]

    return rots


def add_group_count_per_resident_constraint(
        model, block_assigned, residents, blocks,
        rotations, n_min, n_max):

    for res in residents:
        ct = 0

        for blk in blocks:
            for rot in rotations:
                ct += block_assigned[(res, blk, rot)]

        model.Add(ct >= n_min)
        model.Add(ct <= n_max)


def generate_rotation_constraints(config):

    constraints = []

    for rotation, params in config['rotations'].items():

        if not params:
            continue
        if 'coverage' in params:
            rmin, rmax = handle_count_specification(params['coverage'], len(config['blocks']))
            constraints.append(csts.RotationCoverageConstraint(rotation, rmin=rmin, rmax=rmax))
        if 'must_be_followed_by' in params:
            following_rotations = []
            for key in params['must_be_followed_by']:
                if key in config['rotations']:
                    following_rotations.append(key)
                else:
                    following_rotations.extend(
                        resolve_group(key, config['rotations']))

            constraints.append(csts.MustBeFollowedByRotationConstraint(
                rotation=rotation, following_rotations=following_rotations
            ))

        if 'prerequisite' in params:
            constraints.append(csts.PrerequisiteRotationConstraint(
                rotation=rotation, prerequisites=params['prerequisite']
            ))

        if 'cool_down' in params:
            constraints.append(
                csts.CoolDownConstraint.from_yml_dict(rotation, params)
            )

        if params.get('always_paired', False):
            constraints.append(
                csts.AlwaysPairedRotationConstraint(rotation)
            )

        if 'rot_count' in params:
            rmin, rmax = handle_count_specification(
                params['rot_count'], len(config['residents']))
            constraints.append(
                csts.RotationCountConstraint(rotation, rmin, rmax)
            )

        if 'not_rot_count' in params:
            ct = params['not_rot_count']
            constraints.append(
                csts.RotationCountNotConstraint(rotation, ct)
            )

    return constraints


def compute_score_table(scores, block_assigned, residents, blocks, rotations):

    score_table = []
    for res in residents:
        score_row = [res, ]
        for blk in blocks:
            score_row.append(0)
            for rot in rotations:
                score_row[-1] += (
                    scores[(res, blk, rot)] *
                    block_assigned[(res, blk, rot)]
                )
        score_table.append(score_row)

    return score_table


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
        print(f"Solution {self._solution_count:02d} at {datetime.datetime.now()} w objective value {self.ObjectiveValue()}")

        solution_df = self.df_from_solution()

        scores_df = self.df_from_scores()

        self._solution_scores.append(scores_df)
        self._solutions.append(solution_df)


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

        print(f"Solution {self._solution_count:02d} at {datetime.datetime.now()} w objective value {self.ObjectiveValue()}")

        solution_df = self.df_from_solution()

        solution_df.to_csv(
            self._outfile.replace('npz', 'csv') % self._solution_count
        )

        score_table = compute_score_table(
            self._scores,
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

    for c in ranking_df.columns:
        ranking_df[c] = ranking_df[c].fillna(0)
        ranking_df[c] = ranking_df[c].astype(int)

    return ranking_df.T.to_dict()
