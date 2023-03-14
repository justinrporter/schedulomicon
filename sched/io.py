import csv

import numpy as np
import pandas as pd

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
        if 'vacation_window' in params:
            cst_list.append(csts.RotationWindowConstraint(res, 'Vacation', params['vacation_window'].items()))

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

def resolve_resident_group(group, res_config):

    res = [
        r for r, params in res_config.items()
        if params and group in params.get('resident_group', [])
    ]

    return res

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
            if hasattr(params['prerequisite'], 'keys'):
                # prereq defn is a dictionary
                prereq_counts = {}
                for p, c in params['prerequisite'].items():
                    if p in config['rotations']:
                        prereq_counts[(p,)] = c
                    else:
                        prereq_counts[tuple(resolve_group(p, config['rotations']))] = c

                constraints.append(csts.PrerequisiteRotationConstraint(
                    rotation=rotation,
                    prereq_counts=prereq_counts
                ))
            else:
                # prereq defn is a list
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

        if 'requires_resident_group' in params:
            eligible_residents = []
            for group in params['requires_resident_group']:
                eligible_residents.append(resolve_resident_group(group, config['residents']))
            constraints.append(csts.ResidentGroupConstraint(rotation, eligible_residents))
        
        if 'late_CA2' in params:
            if params['late_CA2'] == True:
                group = resolve_resident_group('CA2', config['residents'])
                constraints.append(csts.EligibleAfterBlockConstraint(rotation,group,'Block 7'))

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
