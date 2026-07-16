import csv
import difflib
import warnings
import yaml
import pickle

import json
import re
from collections import OrderedDict, namedtuple

import numpy as np
import pandas as pd

from . import csts, parser, cogrid_csts, util, exceptions
from .util import _normalize_groups


def deduplicate_ordered(seq):
    """Remove duplicates from a list while preserving order."""
    seen = set()
    return [x for x in seq if not (x in seen or seen.add(x))]


SOLUTION_FORMAT_VERSION = 1

GRID_KEY_FIELDS = {
    'main': ['resident', 'block', 'rotation'],
    'backup': ['resident', 'block'],
    'vacation': ['resident', 'week', 'rotation'],
}


def _key_fields_for_grid(grid_name, arity):
    fields = GRID_KEY_FIELDS.get(grid_name)
    if fields is None or len(fields) != arity:
        return ['key_%d' % i for i in range(arity)]
    return fields


def solution_to_json_dict(solution):
    """Convert a solution dict ({grid: {key_tuple: value}}) to a
    JSON-serializable dict. Only nonzero variables are written; omitted
    variables are implicitly 0."""

    grids = {}
    for grid_name, variables in solution.items():
        keys = list(variables.keys())

        if keys:
            key_fields = _key_fields_for_grid(grid_name, len(keys[0]))
        else:
            key_fields = GRID_KEY_FIELDS.get(grid_name, [])

        grids[grid_name] = {
            'key_fields': key_fields,
            'dimensions': {
                field: deduplicate_ordered([k[i] for k in keys])
                for i, field in enumerate(key_fields)
            },
            'variables': [
                list(k) + [int(v)] for k, v in variables.items() if v != 0
            ],
        }

    return {'format_version': SOLUTION_FORMAT_VERSION, 'grids': grids}


def solution_from_json_dict(json_dict):
    """Rebuild a sparse solution dict ({grid: {key_tuple: value}}) from a
    JSON solution dict. Variables absent from the file are 0."""

    version = json_dict.get('format_version')
    if version != SOLUTION_FORMAT_VERSION:
        raise exceptions.UnacceptableFileType(
            f"Unsupported solution format_version {version!r} "
            f"(expected {SOLUTION_FORMAT_VERSION})")

    solution = {}
    for grid_name, grid in json_dict.get('grids', {}).items():
        n_key_fields = len(grid['key_fields'])
        variables = {}

        for row in grid['variables']:
            if len(row) != n_key_fields + 1:
                raise ValueError(
                    f"Malformed variable row in grid '{grid_name}': {row!r} "
                    f"(expected {n_key_fields} key components plus a value)")

            key = tuple(row[:-1])
            if key in variables:
                warnings.warn(
                    f"Duplicate key {key!r} in grid '{grid_name}'; "
                    "the last value wins")
            variables[key] = row[-1]

        solution[grid_name] = variables

    return solution


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

    elif fname.endswith('.pkl') or fname.endswith('.pickle'):
        with open(fname, 'wb') as f:
            pickle.dump(solution, f)

    elif fname.endswith('.json'):
        with open(fname, 'w') as f:
            json.dump(solution_to_json_dict(solution), f, indent=2)

    else:
        raise exceptions.UnacceptableFileType(
            f"File '{fname}' is not of type .csv, .pkl/.pickle, or .json")


def field_sum_constraint(sum_statement, selector_string, config, groups_array):
    """Build a FieldSumConstraint from a ``sum <op> N`` statement and a
    selector DSL expression (e.g. ``'sum == 1'``, ``'R1 and Block 7'``)."""

    satisfies_sum_fn = parser.parse_sum_function(sum_statement)

    field = parser.resolve_eligible_field(
        selector_string,
        groups_array,
        config['residents'].keys(),
        config['blocks'].keys(),
        config['rotations'].keys()
    )

    return csts.FieldSumConstraint(
        satisfies_sum_fn=satisfies_sum_fn,
        field=field
    )


def parse_cli_constraint(spec, config, groups_array):
    """Parse a CLI constraint spec of the form ``'SUM_EXPR: SELECTOR'``,
    e.g. ``'sum == 1: Resident A and Block 7 and Cardiology'``."""

    sum_statement, sep, selector_string = spec.partition(':')

    if not sep:
        raise exceptions.YAMLParseError(
            f"Constraint spec '{spec}' is missing a ':' between the sum "
            "expression and the selector (expected 'SUM_EXPR: SELECTOR', "
            "e.g. 'sum == 1: Resident A and Block 7 and Cardiology').")

    selector_string = selector_string.strip()
    if not selector_string:
        raise exceptions.YAMLParseError(
            f"Constraint spec '{spec}' has an empty selector after the ':'.")

    return field_sum_constraint(
        sum_statement.strip(), selector_string, config, groups_array)


def parse_field_sum_constraint(params, scope_selection, config, groups_array):

    cst_list = []

    for param in params:
        if param.startswith('sum'):
            for selector_string in params[param]:
                cst_list.append(field_sum_constraint(
                    param,
                    f"{scope_selection} and ({selector_string})",
                    config,
                    groups_array
                ))

    return cst_list


Problem = namedtuple('Problem', [
    'config', 'residents', 'blocks', 'rotations', 'cogrids', 'groups_array',
    'cst_list', 'hint',
])


def load_problem(config_path, coverage_min=None, coverage_max=None,
                 hint_path=None, require=()):
    """Load a YAML config and assemble everything needed for a solve.

    Args:
        config_path: Path to the YAML schedule configuration.
        coverage_min: Optional path to a CSV of per-block/rotation coverage
            minima (as for the --coverage-min CLI flag).
        coverage_max: Optional path to a CSV of coverage maxima.
        hint_path: Optional path to a .pkl/.json prior solution to use as a
            solver hint.
        require: Iterable of CLI constraint specs ('SUM_EXPR: SELECTOR'),
            each parsed by parse_cli_constraint into a FieldSumConstraint.

    Returns:
        Problem: A namedtuple of (config, residents, blocks, rotations,
        cogrids, groups_array, cst_list, hint). ``cogrids`` maps each cogrid
        name present in the config ('vacation'/'backup') to its config value.
    """

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    residents, blocks, rotations, cogrids_avail, groups_array = process_config(config)

    cst_list = generate_constraints_from_configs(config, groups_array)

    if coverage_min:
        cst_list.extend(
            coverage_constraints_from_csv(coverage_min, 'rmin')
        )
    if coverage_max:
        cst_list.extend(
            coverage_constraints_from_csv(coverage_max, 'rmax')
        )

    cst_list.extend(
        generate_backup_constraints(config)
    )

    for spec in require:
        cst_list.append(parse_cli_constraint(spec, config, groups_array))

    if hint_path is not None:
        hint = read_solution(hint_path)
    else:
        hint = None

    return Problem(
        config=config,
        residents=residents,
        blocks=blocks,
        rotations=rotations,
        cogrids={c: config[c] for c in cogrids_avail},
        groups_array=groups_array,
        cst_list=cst_list,
        hint=hint,
    )


def read_solution(fname):

    if fname.endswith('.csv'):
        raise NotImplementedError(
            "Hints are only supported with .pkl/.pickle or .json solutions")

    elif fname.endswith('.pkl') or fname.endswith('.pickle'):
        with open(fname, 'rb') as f:
            solution = pickle.load(f)

    elif fname.endswith('.json'):
        with open(fname, 'r') as f:
            solution = solution_from_json_dict(json.load(f))

    else:
        raise exceptions.UnacceptableFileType(
            f"File '{fname}' is not of type .pkl, .pickle, or .json")

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
            if group in _normalize_groups(params.get('groups')):
                group_array[residents.index(res)] = True
    elif group_type == 'blocks':
        for block, params in config['blocks'].items():
            if not params: continue
            if group in _normalize_groups(params.get('groups')):
                for i, res in enumerate(group_array):
                    group_array[i][blocks.index(block)] = True
    elif group_type == 'rotations':
        for rotation, params in config['rotations'].items():
            if not params: continue
            if group in _normalize_groups(params.get('groups')):
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
            groups[config_type].extend(_normalize_groups(params.get('groups')))
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

    resident_constraint_types = [
        csts.ProhibitedCombinationConstraint,
    ]
    available_res_csts = {c.KEY_NAME: c for c in resident_constraint_types}
    known_resident_keys = set(available_res_csts) | {
        'groups', 'history', 'true_somewhere', 'chosen-vacation', 'no_backup',
    }

    for res, params in config['residents'].items():
        if not params:
            continue

        for k in params.keys():
            if k not in known_resident_keys and not k.startswith('sum'):
                suggestion = difflib.get_close_matches(k, known_resident_keys, n=1, cutoff=0.7)
                msg = f"Unknown key '{k}' in resident '{res}'."
                if suggestion:
                    msg += f" Did you mean '{suggestion[0]}'?"
                raise ValueError(msg)

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

        for k in params.keys():
            if k in available_res_csts:
                cst_list.append(available_res_csts[k].from_yml_dict(res, params, config, groups_array))

        cst_list.extend(parse_field_sum_constraint(
            params=params,
            scope_selection=res,
            config=config,
            groups_array=groups_array
        ))

    return cst_list


def generate_block_constraints(config, groups_array):

    cst_list = []
    known_block_keys = {'groups', 'backup_required'}

    for blk, params in config['blocks'].items():
        if not params:
            continue

        for k in params.keys():
            if k not in known_block_keys and not k.startswith('sum'):
                suggestion = difflib.get_close_matches(k, known_block_keys, n=1, cutoff=0.7)
                msg = f"Unknown key '{k}' in block '{blk}'."
                if suggestion:
                    msg += f" Did you mean '{suggestion[0]}'?"
                raise ValueError(msg)

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
            backup_eligible[rotation] = backup_group_name in _normalize_groups(rot_params.get('groups'))

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
        csts.AllowedRootsConstraint,
        csts.MaxActiveBlocksConstraint,
    ]

    available_csts = {c.KEY_NAME: c for c in active_constraint_types}
    known_rotation_keys = set(available_csts) | {
        'groups', 'must_be_followed_by', 'must_be_preceded_by',
        'always_paired', 'not_rot_count', 'backup_count',
    }

    constraints = []
    for rotation, params in config['rotations'].items():
        if not params:
            continue

        for k in params.keys():
            if k not in known_rotation_keys:
                suggestion = difflib.get_close_matches(k, known_rotation_keys, n=1, cutoff=0.7)
                msg = f"Unknown key '{k}' in rotation '{rotation}'."
                if suggestion:
                    msg += f" Did you mean '{suggestion[0]}'?"
                raise ValueError(msg)

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

        if 'must_be_preceded_by' in params:
            preceding_rotations = []
            for key in params['must_be_preceded_by']:
                if key in config['rotations']:
                    preceding_rotations.append(key)
                else:
                    preceding_rotations.extend(
                        util.resolve_group(key, config['rotations']))

            constraints.append(csts.MustBePrecededByRotationConstraint(
                rotation=rotation, preceding_rotations=preceding_rotations
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
