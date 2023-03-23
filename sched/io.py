import csv

import numpy as np
import pandas as pd
import pyparsing as pp

from . import csts


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
    
    groups = {
        'residents': [],
        'blocks': [],
        'rotations': []
    }

    for config_type in ['residents', 'blocks', 'rotations']:
        for item, params in config[config_type].items():
            if not params: continue
            groups[config_type].extend(params.get('groups', []))
        groups[config_type] = list(set(groups[config_type]))

    groups_array = {}
    for group_type in groups:
        for group in groups[group_type]:
            groups_array[group] = get_group_array(group, config, group_type = group_type)
    
    for res in residents:
        groups_array[res] = get_group_array(res,config, group_type = "res_name")
    for block in blocks: 
        groups_array[block] = get_group_array(block,config, group_type = "block_name")
    for rotation in rotations: 
        groups_array[rotation] = get_group_array(rotation,config, group_type = "rotation_name")
    
    return residents, blocks, rotations, groups_array

# def process_config(config):

#     residents = list(config['residents'].keys())
#     blocks = list(config['blocks'].keys())
#     rotations = list(config['rotations'].keys())

#     groups = []
#     for rot, params in config['rotations'].items():
#         if not params:
#             continue
#         groups.extend(params.get('groups', []))
#     groups = list(set(groups))

#     return residents, blocks, rotations, groups


def generate_resident_constraints(config, groups_array):

    cst_list = []

    for res, params in config['residents'].items():
        if not params:
            continue

        if 'true_somewhere' in params:
            for true_somewhere in params['true_somewhere']:
                eligible_field = resolve_pinned_constraint(res+' ('+true_somewhere+")", groups_array, config['residents'].keys(), config['blocks'].keys(), config['rotations'].keys())
                cst_list.append(
                    csts.PinnedRotationConstraint(eligible_field)
                )
                #TODO - can you send a sector of all residents at once?
        # if 'vacation_window' in params:
        #     cst_list.append(csts.RotationWindowConstraint(res, 'Vacation', params['vacation_window']))

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


def generate_constraints_from_configs(config, groups_array):

    constraints = []

    constraints.extend(generate_rotation_constraints(config))

    constraints.extend(generate_resident_constraints(config, groups_array))

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

def resolve_pinned_constraint(true_somewhere, groups_array, residents, blocks, rotations):
   
    group = pp.Combine(pp.Word(pp.alphanums+"_-") + pp.White(' ',max=1) + pp.Word(pp.alphanums), adjacent=False)
    block = pp.Combine(pp.Keyword("Block") + pp.White(' ',max=1) + pp.Word(pp.nums), adjacent=False)
    name = pp.QuotedString("'")
    rotation = pp.Combine(pp.alphas + pp.Optional(pp.White(' ', max=1)) + pp.alphas)

    #@group.set_parse_action
    def resolve_identifier(gramm: pp.ParseResults):
            if gramm[0] in groups_array.keys():
                return groups_array[gramm[0]]
            else: print('not found:', gramm[0])

    group.setParseAction(resolve_identifier)
    block.setParseAction(resolve_identifier)
    name.setParseAction(resolve_identifier)
    rotation.setParseAction(resolve_identifier)
        
    def notParseAction(object):
        set = object[0][1]
        return ~set

    def andParseAction(object):
        set = object[0][0] & object[0][2]
        return set

    def orParseAction(object):
        set = object[0][0] | object[0][2]
        return set
        
    gramm = pp.infixNotation(
        name | block | group,
        [
            (pp.oneOf("not !"), 1, pp.opAssoc.RIGHT, notParseAction),
            (pp.oneOf("and &"), 2, pp.opAssoc.LEFT, andParseAction), 
            (pp.oneOf("or |"), 2, pp.opAssoc.LEFT, orParseAction),   
        ]
    )
    
    eligible_field = gramm.parse_string(true_somewhere)

    return eligible_field

def resolve_pinned_group(group_logic, groups_array, residents, blocks, rotations):

    group = pp.Word(pp.alphanums+"_-" + "''")

    #@group.set_parse_action
    def resolve_identifier(gramm: pp.ParseResults):
        if gramm[0] in groups_array.keys():
            return groups_array[gramm[0]]
        elif gramm[0] in rotations:
            print(groups_array.keys())
            rot_array = np.zeros_like(groups_array['medicine']).astype(bool)
            for i, res in enumerate(rot_array):
                for j, block in enumerate(rot_array[i]):
                   rot_array[i][j][list(rotations).index(gramm[0])] = True
            return rot_array

    group.setParseAction(resolve_identifier)
        
    def notParseAction(object):
        set = object[0][1]
        return ~set

    def andParseAction(object):
        set = object[0][0] & object[0][2]
        return set

    def orParseAction(object):
        set = object[0][0] | object[0][2]
        return set
        
    gramm = pp.infixNotation(
        group,
        [
            (pp.oneOf("not !"), 1, pp.opAssoc.RIGHT, notParseAction),
            (pp.oneOf("and &"), 2, pp.opAssoc.LEFT, andParseAction), 
            (pp.oneOf("or |"), 2, pp.opAssoc.LEFT, orParseAction)   
        ]
    )
    
    eligible_sector = gramm.parse_string(group_logic)
    return eligible_sector

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


# def pin_constraints_from_csv(fname):

#     coverage_pins = pd.read_csv(fname, header=0, index_col=0, comment='#')

#     constraints = []
#     for block, rot_dict in coverage_pins.to_dict().items():
#         for resident, rotation in rot_dict.items():
#             if hasattr(rotation, '__len__'):
#                 # TODO: it sucks this is hard-coded
#                 if block == "Rotation(s) Somewhere":
#                     constraints.append(
#                         csts.PinnedRotationConstraint(resident, [], rotation)
#                     )
#                 else:
#                     constraints.append(
#                         csts.PinnedRotationConstraint(resident, [block], rotation)
#                     )

#     return constraints


def rankings_from_csv(fname):
    ranking_df = pd.read_csv(fname, header=0, index_col=0, comment='#')

    for c in ranking_df.columns:
        ranking_df[c] = ranking_df[c].fillna(0)
        ranking_df[c] = ranking_df[c].astype(int)

    return ranking_df.T.to_dict()
