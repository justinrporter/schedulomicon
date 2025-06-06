import csv
import warnings
import yaml
import pickle

import json
import re
from collections import OrderedDict

import numpy as np
import pandas as pd

from . import csts, parser, cogrid_csts, util, exceptions


def deduplicate_ordered(seq):
    """Remove duplicates from a list while preserving order."""
    seen = set()
    return [x for x in seq if not (x in seen or seen.add(x))]


def backup_is_active(config):
    return config.get('backup', False)


def write_solution(fname, solution):

    if fname.endswith('.csv'):
        residents = deduplicate_ordered([k[0] for k in solution['main'].keys()])
        blocks = deduplicate_ordered([k[1] for k in solution['main'].keys()])
        rotations = deduplicate_ordered([k[2] for k in solution['main'].keys()])

        data = {}
        for blk in blocks:
            data[blk] = {}
            for res in residents:
                for rot in rotations:
                    if solution['main'][res, blk, rot] == 1:
                        data[blk][res] = rot

                        if 'backup' in solution:
                            if solution['backup'][res, blk]:
                                data[blk][res] += '+'

                        break  # Each resident has exactly one rotation per block

        pd.DataFrame.from_dict(data, orient='index').T.to_csv(fname)

    elif fname.endswith('.pkl'):
        with open(fname, 'wb') as f:
            pickle.dump(solution, f)


def parse_field_sum_constraint(params, scope_selection, config, groups_array):

    cst_list = []

    for param in params:
        if param.startswith('sum'):
            satisfies_sum_fn = parser.parse_sum_function(param)

            for selector_string in params[param]:
                field = parser.resolve_eligible_field(
                    f"{scope_selection} and ({selector_string})",
                    groups_array,
                    config['residents'].keys(),
                    config['blocks'].keys(),
                    config['rotations'].keys()
                )
                cst_list.append(
                    csts.FieldSumConstraint(
                        satisfies_sum_fn=satisfies_sum_fn,
                        field=field
                    )
                )

    return cst_list


def read_solution(fname):

    if fname.endswith('.csv'):
        raise NotImplementedError("Hints are only supported with pickled solutions")

        hint = pd.read_csv(args.hint, header=0, index_col=0, comment='#')\
            .replace(r'\+', '', regex=True)

    elif fname.endswith('.pkl') or fname.endswith('.pickle'):
        with open(fname, 'rb') as f:
            solution = pickle.load(f)

    else:
        raise exceptions.UnacceptableFileType(
            f"File '{fname}' is not of type .pkl or .csv")

    return solution


def get_group_array(group, config, group_type):
    
    residents = list(config['residents'].keys())
    blocks = list(config['blocks'].keys())
    rotations = list(config['rotations'].keys())

    n_res = len(residents)
    n_blocks = len(blocks)
    n_rots = len(rotations)

    group_array = np.dstack([np.stack([[False]*n_res]*n_blocks).T]*n_rots)

    if group_type == 'residents':
        for res, params in config['residents'].items():
            if not params: continue
            if group in params.get('groups', []):
                group_array[residents.index(res)] = True
    elif group_type == 'blocks':
        for block, params in config['blocks'].items():
            if not params: continue
            if group in params.get('groups', []):
                for i, res in enumerate(group_array):
                    group_array[i][blocks.index(block)] = True
    elif group_type == 'rotations':
        for rotation, params in config['rotations'].items():
            if not params: continue
            if group in params.get('groups', []):
                for i, res in enumerate(group_array):
                    for j, block in enumerate(group_array[i]):
                        group_array[i][j][rotations.index(rotation)] = True

    elif group_type == 'res_name':
        group_array[residents.index(group)] = True
    elif group_type == 'block_name':
        for i,res in enumerate(residents): 
            group_array[i][blocks.index(group)] = True
    elif group_type == 'rotation_name':
        for i, res in enumerate(residents):
            for j, block in enumerate(blocks):
                group_array[i][j][rotations.index(group)] = True

    return group_array

def process_config(config):

    residents = list(config['residents'].keys())
    blocks = list(config['blocks'].keys())
    rotations = list(config['rotations'].keys())
    cogrids = list(
        k for k in config.keys()
        if k in ['vacation', 'backup']
    )

    groups = {
        'residents': [],
        'blocks': [],
        'rotations': [],
    }

    for config_type in ['residents', 'blocks', 'rotations']:
        for item, params in config[config_type].items():
            if not params: continue
            groups[config_type].extend(params.get('groups', []))
        groups[config_type] = list(set(groups[config_type]))

    groups_array = {}
    for group_type in groups:
        for group in groups[group_type]:
            groups_array[group] = get_group_array(group, config, group_type=group_type)
    
    for res in residents:
        groups_array[res] = get_group_array(res,config, group_type="res_name")
    for block in blocks: 
        groups_array[block] = get_group_array(block,config, group_type="block_name")
    for rotation in rotations: 
        groups_array[rotation] = get_group_array(rotation,config, group_type="rotation_name")

    return residents, blocks, rotations, cogrids, groups_array


def generate_resident_constraints(config, groups_array):

    cst_list = []

    for res, params in config['residents'].items():
        if not params:
            continue

        if 'true_somewhere' in params:
            warnings.warn("Declaration 'true_somewhere' is depricated, use 'sum > 0' instead.")
            for selector_string in params['true_somewhere']:
                eligible_field = parser.resolve_eligible_field(
                    f"{res} and ({selector_string})",
                    groups_array,
                    config['residents'].keys(),
                    config['blocks'].keys(),
                    config['rotations'].keys()
                )
                cst_list.append(
                    csts.TrueSomewhereConstraint(eligible_field)
                )
        
        if 'chosen-vacation' in params:
            for week in params['chosen-vacation']:

                cst_list.append(
                    cogrid_csts.ChosenVacationConstraint(res, week)
                )

        cst_list.extend(parse_field_sum_constraint(
            params=params,
            scope_selection=res,
            config=config,
            groups_array=groups_array
        ))

    return cst_list


def generate_block_constraints(config, groups_array):

    cst_list = []

    for blk, params in config['blocks'].items():
        if not params:
            continue

        cst_list.extend(parse_field_sum_constraint(
            params=params,
            scope_selection=blk,
            config=config,
            groups_array=groups_array
        ))

    return cst_list

def generate_backup_constraints(
    config, backup_group_name='backup_eligible'):

    constraints = []

    for block, blk_params in config['blocks'].items():
        # sometimes blk_params can be None, for which .get won't work
        if blk_params and blk_params.get('backup_required', False):
            min_residents = blk_params['backup_required'][0]
            max_residents = blk_params['backup_required'][1]

            constraints.append(
                cogrid_csts.BackupRequiredOnBlockBackupConstraint(
                    block=block,
                    min_residents=min_residents,
                    max_residents=max_residents
                )
            )

    for rotation, rot_params in config['rotations'].items():
        if rot_params and 'backup_count' in rot_params:
            ct = int(rot_params['backup_count'])
            constraints.append(
                cogrid_csts.RotationBackupCountConstraint(rotation, ct)
            )

    for res, res_params in config['residents'].items():
        if not res_params: continue
        if 'no_backup' in res_params: 
            for block in res_params['no_backup']:
                constraints.append(cogrid_csts.BanBackupBlockContraint(res, block))

    if constraints and not config.get('backup', False):
        raise exceptions.YAMLConfigurationMalformedError(
            "The top-level 'backup' directive is false or not present, but backup "
            "parameters for rotations and/or residents have been set:" +
            "\n".join([str(c) for c in constraints])
        )

    backup_eligible = {}
    for rotation, rot_params in config['rotations'].items():
        if rot_params:
            backup_eligible[rotation] = backup_group_name in rot_params.get('groups', {})

    if backup_eligible and backup_is_active(config):
        constraints.append(
            cogrid_csts.BackupEligibleBlocksBackupConstraint(backup_eligible)
        )

    return constraints


def generate_vacation_constraints(config, groups_array):
    constraints = []

    vacation_root_constraints = [
        cogrid_csts.VacationCooldownConstraint,
    ]

    if config.get('vacation', None):

        constraints.append(
            cogrid_csts.VacationMappingConstraint.from_yml_dict(
                params=None, config=config)
        )

        for c in vacation_root_constraints:

            if config['vacation'].get(c.KEY_NAME, False):

                constraints.append(
                    c.from_yml_dict(
                        params=config['vacation'][c.KEY_NAME],
                        config=config,
                        groups_array=groups_array
                    )
                )

    return constraints

def generate_constraints_from_configs(config, groups_array):

    constraints = []

    constraints.extend(generate_rotation_constraints(config, groups_array))

    constraints.extend(generate_resident_constraints(config, groups_array))

    constraints.extend(generate_vacation_constraints(config, groups_array))

    constraints.extend(generate_block_constraints(config, groups_array))

    for cst in config.get('group_constraints', []):

        if 'kind' not in cst:
            raise exceptions.YAMLParseError(
                "All group_constraint definitions require a value for 'kind'. "
                "Constraint looked like: " + str(cst)
            )

        if cst['kind'] == 'all_group_count_per_resident':
            constraints.append(
                csts.GroupCountPerResidentPerWindow.from_yml_dict(cst, config)
            )

        elif cst['kind'] == 'window_group_count_per_resident':
            constraints.append(
                csts.GroupCountPerResidentPerWindow.from_yml_dict(cst, config)
            )

        elif cst['kind'] == 'group_coverage_constraint':
           constraints.append(
                csts.GroupCoverageConstraint.from_yml_dict(
                    cst, config
            ))
        elif cst['kind'] == 'time_to_first':
            constraints.append(
                csts.TimeToFirstConstraint(
                    rotations_in_group=util.resolve_group(cst['group'], config['rotations']),
                    window_size = cst['window_size'])
            )

    return constraints


def handle_count_specification(count_config, n_items):

    if 'min' in count_config and 'max' in count_config:
        rmin = expand_to_length_if_needed(count_config['min'], n_items)
        rmax = expand_to_length_if_needed(count_config['max'], n_items)
    else:
        try:
            rmin = expand_to_length_if_needed(count_config[0], n_items)
            rmax = expand_to_length_if_needed(count_config[1], n_items)
        except:
            print("Failed to parse count spec:", count_config)
            raise

    return rmin, rmax


def expand_to_length_if_needed(var, length):

    if not hasattr(var, '__len__'):
        return [var]*length
    else:
        assert len(var) == length
        return var


def generate_rotation_constraints(config, groups_array):

    # for constraints that know how to parse their own YAML, the KEY_NAME
    # member variable is used to determine when to activate the constraint's
    # from_yml_dict function
    active_constraint_types = [
        csts.RotationCoverageConstraint,
        csts.CoolDownConstraint,
        csts.RotationCountConstraint,
        csts.RotationCountConstraintWithHistory,
        csts.PrerequisiteRotationConstraint,
        csts.IneligibleAfterConstraint,
        csts.ConsecutiveRotationCountConstraint,
        csts.AllowedRootsConstraint
    ]

    available_csts = {c.KEY_NAME: c for c in active_constraint_types}

    constraints = []
    for rotation, params in config['rotations'].items():
        if not params:
            continue

        for k in params.keys():
            if k in available_csts:
                constraints.append(
                    available_csts[k].from_yml_dict(
                        rotation, params, config))

        if 'must_be_followed_by' in params: 
            following_rotations = []
            for key in params['must_be_followed_by']:
                if key in config['rotations']:
                    following_rotations.append(key)
                else:
                    following_rotations.extend(
                        util.resolve_group(key, config['rotations']))

            constraints.append(csts.MustBeFollowedByRotationConstraint(
                rotation=rotation, following_rotations=following_rotations
            ))

        if params.get('always_paired', False):
            constraints.append(csts.ConsecutiveRotationCountConstraint(rotation, count=2))

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

def coverage_constraints_from_csv(fname, rmin_or_rmax):
    coverage_min = pd.read_csv(fname, header=0, index_col=0, comment='#')

    constraints = []
    for block, rot_dict in coverage_min.to_dict().items():
        for rot, ct in rot_dict.items():
            if not np.isnan(ct):
                constraints.append(
                    csts.RotationCoverageConstraint(
                        rotation_or_rotations=rot,
                        blocks=[block], **{rmin_or_rmax: int(ct)})
                )

    return constraints


def rankings_from_csv(fname):
    ranking_df = pd.read_csv(fname, header=0, index_col=0, comment='#')
    
    for c in ranking_df.columns:
        ranking_df[c] = ranking_df[c].fillna(0)
        ranking_df[c] = ranking_df[c].astype(int)

    return ranking_df.T.to_dict()
