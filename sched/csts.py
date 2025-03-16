import itertools
import numbers
import logging
import numpy as np

from . import exceptions
from .exceptions import YAMLParseError
from .util import resolve_group, accumulate_prior_counts


logger = logging.getLogger(__name__)


class Constraint:

    def apply(self, model, block_assigned, residents, blocks, rotations, grids):
        raise NotImplementedError("Constraint %s failed to implement apply" % self)

    @classmethod
    def _check_yaml_params(cls, root_entity, cst_params):
        for key in cst_params:
            if key not in cls.ALLOWED_YAML_OPTIONS:
                raise YAMLParseError(
                    f'On {root_entity}, option {key} not allowed (allowed '
                    f'options are {cls.xf_YAML_OPTIONS}).'
                )


class BackupRequiredOnBlockBackupConstraint(Constraint):

    def __init__(self, block, min_residents, max_residents):
        self.block = block
        self.min_residents = min_residents
        self.max_residents = max_residents

    def apply(self, model, block_assigned, residents, blocks, rotations, grids):

        block_backup = grids['backup']['variables']

        ct = 0
        for resident in residents:
            ct += block_backup[(resident, self.block)]

        model.Add(ct >= self.min_residents)
        model.Add(ct <= self.max_residents)


class RotationBackupCountConstraint(Constraint):

    def __init__(self, rotation, count):
        self.rotation = rotation
        self.count = count

    def apply(self, model, block_assigned, residents, blocks, rotations, grids):

        block_backup = grids['backup']['variables']

        backup_vars = {}
        for resident in residents:
            for block in blocks:
                backup_vars[(resident, block)] = model.NewBoolVar(
                    'backup_r%s_b%s_%s' % (resident, block, self.rotation))

        for resident in residents:
            for block in blocks:
                model.AddImplication(
                    block_backup[(resident, block)],
                    backup_vars[(resident, block)]
                ).OnlyEnforceIf(block_assigned[(resident, block, self.rotation)])

                model.AddImplication(
                    block_assigned[(resident, block, self.rotation)],
                    backup_vars[(resident, block)]
                ).OnlyEnforceIf(block_backup[(resident, block)])

                model.AddImplication(
                    block_assigned[(resident, block, self.rotation)].Not(),
                    backup_vars[(resident, block)].Not()
                )

                model.AddImplication(
                    block_backup[(resident, block)].Not(),
                    backup_vars[(resident, block)].Not()
                )

        ct = 0
        for block in blocks:
            for resident in residents:
                ct += backup_vars[(resident, block)]
        model.Add(ct <= self.count)


class BanBackupBlockContraint(Constraint):
    def __init__(self, resident, block):
        self.block = block
        self.resident = resident

    def apply(self, model, block_assigned, residents, blocks, rotations, grids):

        block_backup = grids['backup']['variables']

        model.Add(block_backup[(self.resident, self.block)] == 0)


class BackupEligibleBlocksBackupConstraint(Constraint):

    def __init__(self, backup_eligible):
        self.backup_eligible = {k: 1 if v else 0 for k, v in backup_eligible.items()}

        if not any(v for v in self.backup_eligible.values()):
            s = (
                "WARNING: No blocks are backup eligible, but "
                "BackupEligibleBlocksBackupConstraint is present."
            )
            logger.warning(s)

    def apply(self, model, block_assigned, residents, blocks, rotations, grids):
        block_backup = grids['backup']['variables']

        for resident in residents:
            for block in blocks:
                for rotation in rotations:
                    # if a resident is assigned to a rotation on a block
                    # backup_eligible must be 1 for block_backup to be 1

                    block_is_assigned = block_assigned[(resident, block, rotation)]

                    model.Add(
                        self.backup_eligible[rotation] >= block_backup[(resident, block)]) \
                            .OnlyEnforceIf(block_is_assigned)


class BanRotationBlockConstraint(Constraint):

    def __init__(self, block, rotation):
        self.block = block
        self.rotation = rotation

    def apply(self, model, block_assigned, residents, blocks, rotations, grids):

        for resident in residents:
            model.Add(block_assigned[(resident, self.block, self.rotation)] == 0)


class RotationCoverageConstraint(Constraint):

    ALLOWED_YAML_OPTIONS = ['allowed_values', 'rmin', 'rmax']
    KEY_NAME = 'coverage'

    @classmethod
    def from_yml_dict(cls, rotation, params, config):

        assert cls.KEY_NAME in params

        # options are 1) coverage: [rmin, rmax]
        # or 2) coverage: allowed_values: [v1, v2, ...]
        if 'allowed_values' in params[cls.KEY_NAME]:
            allowed_vals = params[cls.KEY_NAME]['allowed_values']
            cst = cls(rotation, allowed_vals=allowed_vals)

        else:  # specifying rmin, rmax directly
            rmin, rmax = params[cls.KEY_NAME]
            cst = cls(rotation, rmin=rmin, rmax=rmax)

        return cst

    def __repr__(self):
        return "RotationCoverageConstraint(%s,%s,%s,%s)" % (
             self.rotations, self.blocks, self.rmin, self.rmax)

    def __init__(self, rotation_or_rotations, blocks=Ellipsis, rmin=None, rmax=None, allowed_vals=None):

        if isinstance(rotation_or_rotations, str):
            self.rotations = [rotation_or_rotations]
        else:
            self.rotations = rotation_or_rotations

        self.blocks = blocks

        if allowed_vals is not None:
            assert rmin is None
            assert rmax is None
            self.allowed_vals = allowed_vals
            self.rmin = None
            self.rmax = None
        else:
            assert rmin is not None or rmax is not None
            if rmin is not None and rmax is not None:
                assert rmin <= rmax
            self.allowed_vals = None
            self.rmin = rmin
            self.rmax = rmax


    def apply(self, model, block_assigned, residents, blocks, rotations, grids):

        # ellipsis just means all blocks
        if self.blocks is Ellipsis:
            apply_to_blocks = blocks
        else:
            apply_to_blocks = self.blocks

        if not hasattr(self.rmin, '__len__'):
            rmin_list = [self.rmin]*len(apply_to_blocks)
        else:
            rmin_list = self.rmin

        if not hasattr(self.rmax, '__len__'):
            rmax_list = [self.rmax]*len(apply_to_blocks)
        else:
            rmax_list = self.rmax

        for block, rmin, rmax in zip(apply_to_blocks, rmin_list, rmax_list):

            if None not in [rmin, rmax]:
                assert rmin <= rmax, f"For rotations '{self.rotations}' block '{block}', rmin {rmin} > rmax {rmax}"

            # r_tot is the total number of residents on this rotation for this block
            # need to make a new IntVar for r_tot, since AddAllowedAssignments takes
            # an OR-Tools IntVar
            r_tot = 0
            for rot in self.rotations:
                for res in residents:
                    r_tot += block_assigned[(res, block, rot)]

            r_tot_var = model.NewIntVar(
                0, len(residents), "r_tot_" + '_'.join(self.rotations) + f"_{block}")

            # OR-Tools requires a separate variable to constrain (below)
            # via AddAllowedAssignments, so we name it separately and make it
            # equivalent to the r_tot accumulated value
            model.Add(r_tot_var == r_tot)

            if rmin is not None:
                model.Add(r_tot_var >= rmin)
            if rmax is not None:
                model.Add(r_tot_var <= rmax)
            if self.allowed_vals is not None:
                assert not any(v is None for v in self.allowed_vals)
                allowed_vals = [[value] for value in self.allowed_vals]
                model.AddAllowedAssignments([r_tot_var], allowed_vals)


class GroupCoverageConstraint(RotationCoverageConstraint):

    KEY_NAME = 'group_coverage_constraint'

    @classmethod
    def from_yml_dict(cls, params, config):

        assert params['kind'] == cls.KEY_NAME, params

        # run through the config's rotations to identify the rotations
        # in the group
        rotations = resolve_group(params['group'], config['rotations'])

        # allowed formats:
        # 1) {min: 1, max: 2}
        # 2) {allowed_coverage: [1, 3, 5]}
        # 3) {count: [0, 3]}
        coverage_spec = {}
        if 'min' in params:
            coverage_spec['rmin'] = params['min']
            assert 'allowed_coverage' not in params
            assert 'count' not in params
        if 'max' in params:
            coverage_spec['rmax'] = params['max']
            assert 'allowed_coverage' not in params
            assert 'count' not in params

        if 'count' in params:
            coverage_spec['rmin'] = params['count'][0]
            coverage_spec['rmax'] = params['count'][1]
            assert 'min' not in params
            assert 'max' not in params
            assert 'allowed_coverage' not in params
        if 'allowed_coverage' in params:
            return cls(
                rotations,
                blocks=params.get('blocks', Ellipsis),
                allowed_vals=params['allowed_coverage']
            )
            assert 'min' not in params
            assert 'max' not in params
            assert 'count' not in params

        return cls(
            rotations,
            blocks=params.get('blocks', Ellipsis),
            **coverage_spec
        )

class PrerequisiteRotationConstraint(Constraint):

    KEY_NAME = 'prerequisite'

    @classmethod
    def from_yml_dict(cls, rotation, params, config):

        assert cls.KEY_NAME in params, f"{cls.KEY_NAME} not in {params}"

        if hasattr(params[cls.KEY_NAME], 'keys'):
            # prereq defn is a dictionary
            prereq_counts = {}
            for p, c in params[cls.KEY_NAME].items():
                if p in config['rotations']:
                    prereq_counts[(p,)] = c
                else:
                    prereq_counts[
                        tuple(resolve_group(p, config['rotations']))
                    ] = c

            prior_counts = {}
            for rot_grp in prereq_counts.keys():
                # each rotation accumulates counts from every rotation in
                # the group
                for rot in rot_grp:
                    prior_counts[rot] = accumulate_prior_counts(
                        [rot], config['residents']
                    )

            cst = cls(
                rotation=rotation,
                prereq_counts=prereq_counts,
                prior_counts=prior_counts
            )
        else:
            prior_counts = {
                rot: accumulate_prior_counts([rot], config['residents'])
                for rot in params[cls.KEY_NAME]
            }

            # prereq defn is a list
            cst = cls(
                rotation=rotation,
                prereq_counts={(p,): 1 for p in params[cls.KEY_NAME]},
                prior_counts=prior_counts
            )

        return cst


    def __init__(self, rotation, prereq_counts, prior_counts=None):
        self.rotation = rotation
        self.prerequisites = prereq_counts

        # has format:
        # {
        #     "rotation1": {"resident1": count_res1_rot1, "resident2": count_res1_rot2},
        #     "rotation2": {"resident1": count_res2_rot1, "resident2": count_res2_rot2}
        # }
        self.prior_counts = prior_counts

        logger.debug('Rotation %s prerequisites %s', rotation, self.prerequisites)


    def apply(self, model, block_assigned, residents, blocks, rotations, grids):

        for resident in residents:
            for i in range(len(blocks)):
                rot_is_assigned = block_assigned[(resident, blocks[i], self.rotation)]

                cst_spec_list = []

                for prereq_grp, req_ct in self.prerequisites.items():
                    # n_prepreq_instances is initialized at zero
                    n_prereq_instances = 0
                    for prereq in prereq_grp:
                        # for each rotation in the prereq group, add in first
                        # historical instances of that rotation (from prior_counts)
                        if self.prior_counts is not None:
                            n_prereq_instances += self.prior_counts.get(prereq).get(resident)

                        # then iterate over instances in the solution space
                        for j in range(0, i):
                            n_prereq_instances += block_assigned[(resident, blocks[j], prereq)]

                    cst_spec_list.append(
                        (n_prereq_instances, req_ct)
                    )

                self._apply_csts(model, prereq_grp, rot_is_assigned, cst_spec_list)

    def _apply_csts(self, model, prereq_grp, rot_is_assigned, cst_spec_list):

        for n_prereq_instances, req_ct in cst_spec_list:
            model.Add(n_prereq_instances >= req_ct).OnlyEnforceIf(rot_is_assigned)

class IneligibleAfterConstraint(PrerequisiteRotationConstraint):

    KEY_NAME = 'ineligible_after'

    def _apply_csts(self, model, prereq_grp, rot_is_assigned, cst_spec_list):
        # the only difference between this and PrerequisiteRotationConstraint
        # is that here, whenever rot is assigned, we have to ensure that
        # SOME prereq is UNsatisfied.

        # that is, the ineligibility list functions like an AND constraint,
        # only being satisfied if all constraints are met

        prereqs_unsatisfied = []
        for n_prereq_instances, req_ct in cst_spec_list:
            prereq_unsatisfied = model.NewBoolVar(f'prereq-{rot_is_assigned}-{prereq_grp}')
            prereqs_unsatisfied.append(prereq_unsatisfied)

            model.Add(n_prereq_instances < req_ct).OnlyEnforceIf(prereq_unsatisfied)
            model.Add(n_prereq_instances >= req_ct).OnlyEnforceIf(prereq_unsatisfied.Not())

        model.Add(sum(prereqs_unsatisfied) >= 1).OnlyEnforceIf(rot_is_assigned)


class AllowedRootsConstraint(Constraint):
    
    KEY_NAME = 'allowed_roots'

    @classmethod
    def from_yml_dict(cls, rotation, params, config):

        assert cls.KEY_NAME in params, f"{cls.KEY_NAME} not in {params}"
        # cls._check_yaml_params(rotation, params[cls.KEY_NAME])

        if hasattr(params['allowed_roots']):

            allowed_roots = []

            for root in params['allowed_roots']:
                if root in config['blocks']:
                    allowed_roots.append(root)
                else:
                    allowed_roots.extend(resolve_group(root, config['blocks']))

        return cls(
            rotation=rotation,
            allowed_roots=allowed_roots
        )
    
    def __init__(self, rotation, allowed_roots=None):
        self.rotation = rotation
        self.allowed_roots = allowed_roots if allowed_roots is not None else []

    def apply(self, model, block_assigned, residents, blocks, rotations, grids):

        for root in self.allowed_roots:
            if root not in blocks:
                raise exceptions.NameNotFound(
                    f"In {self}, unable to find allowed root named '{root}'",
                    name=root
                )

        for res in residents:
            # scan through all blocks
            for i in range(len(blocks)):
                is_root = model.NewBoolVar(
                    f'{blocks[i]}_root_of_consec_{self.rotation}_{res}')

                if blocks[i] in self.allowed_roots:
                    model.Add(is_root == 1)
                else: model.Add(is_root == 0)

class ConsecutiveRotationCountConstraint(Constraint):

    KEY_NAME = 'consecutive_count'

    @classmethod
    def from_yml_dict(cls, rotation, params, config):

        assert cls.KEY_NAME in params, f"{cls.KEY_NAME} not in {params}"
        # cls._check_yaml_params(rotation, params[cls.KEY_NAME])

        # Expected formats:
        # consecutive_count: {count: 2, forbidden_roots: [Block 1, Block 3], allowed_roots: [Block 5A, Block 10A]}
        if hasattr(params['consecutive_count'], 'keys'):

            forbidden_roots = []
            allowed_roots = []

            for r in params['consecutive_count']['forbidden_roots']:
                if r in config['blocks']:
                    forbidden_roots.append(r)
                else:
                    forbidden_roots.extend(resolve_group(r, config['blocks']))

            if 'allowed_roots' in params['consecutive_count']:
                for r in params['consecutive_count']['allowed_roots']:
                    if r in config['blocks']:
                        allowed_roots.append(r)
                    else:
                        allowed_roots.extend(resolve_group(r, config['blocks']))

            try:
                ct = params['consecutive_count']['count']
            except KeyError as e:
                raise KeyError(
                    f"On {rotation} 'consecutive count': missing parameter {e}"
                ) from e

            return cls(
                rotation=rotation,
                count=ct,
                forbidden_roots=forbidden_roots,
                allowed_roots=allowed_roots
            )
        else:
            return cls(
                rotation=rotation,
                count=params['consecutive_count'],
                forbidden_roots=[],
                allowed_roots=[]
            )

    def __repr__(self):
        return "ConsecutiveRotationCountConstraint(%s, n=%s)" % (
             self.rotation, self.count)

    def __init__(self, rotation, count, forbidden_roots=None, allowed_roots=None):
        self.rotation = rotation
        self.count = count
        self.forbidden_roots = forbidden_roots if forbidden_roots is not None else []
        self.allowed_roots = allowed_roots if allowed_roots is not None else []

    def apply(self, model, block_assigned, residents, blocks, rotations, grids):

        for root in self.forbidden_roots:
            if root not in blocks:
                raise exceptions.NameNotFound(
                    f"In {self}, unable to find forbidden root named '{root}'",
                    name=root
                )
        #print(self.rotation, 'allowed roots: ', self.allowed_roots)

        if len(self.allowed_roots) > 0:
            for root in self.allowed_roots:
                if root not in blocks:
                    raise exceptions.NameNotFound(
                        f"In {self}, unable to find allowed root named '{root}'",
                        name=root
                    )

        for res in residents:

            # scan through all blocks that could be the start of a self.count
            # length stretch of instances of this rotation
            for i in range(len(blocks)):
                is_root = model.NewBoolVar(
                    f'{blocks[i]}_root_of_consec_{self.rotation}_{res}')

                if blocks[i] in self.forbidden_roots:
                    model.Add(is_root == False)

                if self.allowed_roots is not False:
                    if blocks[i] not in self.forbidden_roots and blocks[i] in self.allowed_roots:
                        model.Add(is_root == True)

                if i == 0:
                    model.Add(
                        block_assigned[(res, blocks[0], self.rotation)] ==
                        is_root
                    )
                else:

                    model.AddBoolAnd(
                        block_assigned[(res, blocks[i-1], self.rotation)].Not(),
                        block_assigned[(res, blocks[i],   self.rotation)],
                    ).OnlyEnforceIf(is_root)
                    model.AddBoolOr(
                        block_assigned[(res, blocks[i-1], self.rotation)],
                        block_assigned[(res, blocks[i],   self.rotation)].Not(),
                    ).OnlyEnforceIf(is_root.Not())

                if i > len(blocks) - self.count:
                    model.Add(is_root == 0)
                else:
                    # rest_of_window is the rest of the length of rotation
                    # after the root (indices 1+), along with one past the
                    # end of where the rotation should be with a not
                    rest_of_window = []

                    for j in range(1, self.count):
                        rest_of_window.append(
                            block_assigned[(res, blocks[i+j], self.rotation)]
                        )

                    if i+j < len(blocks)-1:
                        rest_of_window.append(
                            block_assigned[(res, blocks[i+j+1], self.rotation)].Not()
                        )

                    model.AddBoolAnd(rest_of_window).OnlyEnforceIf(is_root)

            last_normal_block = i
            last_normal_block_is_rot = block_assigned[(res, blocks[last_normal_block], self.rotation)]
            for i in range(last_normal_block, len(blocks)):
                blk = blocks[i]
                model.AddImplication(
                    last_normal_block_is_rot,
                    block_assigned[(res, blocks[i], self.rotation)]
                )


class MustBeFollowedByRotationConstraint(Constraint):

    def __repr__(self):
        return "RotationMustBeFollowedByConstraint(%s,%s)" % (
             self.rotation, self.following_rotations)

    def __init__(self, rotation, following_rotations):
        self.rotation = rotation
        self.following_rotations = following_rotations

    def apply(self, model, block_assigned, residents, blocks, rotations, grids):

        add_must_be_followed_by_constraint(
            model, block_assigned, residents, blocks,
            rotation=self.rotation,
            following_rotations=self.following_rotations
        )


class CoolDownConstraint(Constraint):

    KEY_NAME = 'cool_down'
    ALLOWED_YAML_OPTIONS = ['window', 'count', 'suppress_for']

    @classmethod
    def from_yml_dict(cls, rotation, params, config):

        assert cls.KEY_NAME in params
        cls._check_yaml_params(rotation, params[cls.KEY_NAME])

        # Expected format:
        # cool_down:
        #   window: 2
        #   count: 1
        #   exclude_for: ["Yi, Yangtian"]

        window_size = params['cool_down'].get('window')
        count = params['cool_down'].get('count', 1)
        suppress_for = params['cool_down'].get('suppress_for', [])

        if params.get('consecutive_count', False):
            raise exceptions.IncompatibleConstraintsException(
                f"CoolDownConstraint (on rotation {rotation}) can't be used "
                f"with ConsecutiveRotationCountConstraint yet."
            )

        return cls(
            rotation,
            window_size=window_size,
            count=[0, count],
            suppress_for=suppress_for
        )

    def __repr__(self):
        return "CoolDownConstraint(%s,%s,%s)" % (
             self.rotation, self.window_size, self.count)

    def __init__(self, rotation, window_size, count, suppress_for=[]):
        self.rotation = rotation
        self.window_size = window_size
        self.count = count
        self.n_min = count[0]
        self.n_max = count[1]
        self.suppress_for = suppress_for

    def apply(self, model, block_assigned, residents, blocks, rotations, grids):

        residents = [res for res in residents if res not in self.suppress_for]
        
        add_window_count_constraint(
            model, block_assigned, residents, blocks,
            rotations=[self.rotation],
            window_size=self.window_size,
            n_min = self.n_min,
            n_max = self.n_max
        )


class RotationCountConstraint(Constraint):

    KEY_NAME = 'rot_count'

    def __init__(self, rotation, count_map, prior_counts=None):
        self.rotation = rotation
        self.count_map = count_map

        if prior_counts is None:
            self.prior_counts = {}
        else:
            self.prior_counts = prior_counts

        for v in count_map.values():
            assert len(v) == 2
            int(v[0])
            int(v[1])

    @classmethod
    def from_yml_dict(cls, rotation, params, config, include_history=False):

        assert cls.KEY_NAME in params

        # options are:
        # 1) rot_count: {CA1: [0, 1], CA2: [0, 1], CA3: 1}
        # 2) rot_count: [0, 10]
        # 3) rot_count: 2

        options = params[cls.KEY_NAME]

        if include_history:
            prior_counts = {rotation: accumulate_prior_counts(
                [rotation], config['residents'])}
        else:
            prior_counts = None

        if hasattr(options, 'keys'):
            count_map = {}
            for res_or_res_group, min_and_max in options.items():

                if hasattr(min_and_max, '__len__'):
                    assert len(min_and_max) == 2
                    n_min, n_max = min_and_max
                else:
                    n_min = n_max = int(min_and_max)
                    # assert False, (
                    #     "Unrecognized format for RotationCountConstraint %s, "
                    #     "specifically count for group %s" % (params, res_or_res_group)
                    # )

                assert int(n_min) <= int(n_max)

                if res_or_res_group in config['residents'].keys():
                    count_map[res_or_res_group] = (n_min, n_max)
                else:
                    residents = resolve_group(res_or_res_group, config['residents'])
                    assert len(residents)
                    for resident in residents:
                        count_map[resident] = (int(n_min), int(n_max))

            cst = cls(rotation, count_map, prior_counts)
        elif len(options) == 2:
            n_min, n_max = int(options[0]), int(options[1])
            cst = cls(
                rotation,
                {
                 resident: (n_min, n_max) for resident in
                 config['residents'].keys()
                },
                prior_counts
            )
        elif len(options) == 1:
            n_rot = int(options[0])
            cst = cls(
                rotation,
                {
                 resident: (n_rot, n_rot) for resident in
                 config['residents'].keys()
                },
                prior_counts
            )
        else:
            assert False, (
                "Unrecognized format for RotationCountConstraint %s" % params
            )

        return cst

    def apply(self, model, block_assigned, residents, blocks, rotations, grids):

        for resident, (nmin, nmax) in self.count_map.items():
            r_tot = sum(block_assigned[(resident, block, self.rotation)] for block in blocks)
            assert nmin is not None
            assert nmax is not None

            prior_count = self.prior_counts.get(self.rotation, {}).get(resident, 0)

            # raise an error if the given prior_counts create an infeasible
            # problem using this constraint
            if prior_count > nmax:
                assert False, (
                    "Trying to apply RotationCountConstraint (%s, %s) on %s "
                    "for %s is imposible as prior count is %s" %
                    (nmin, nmax, resident, self.rotation, prior_count))

            model.Add((r_tot + prior_count) >= nmin)
            model.Add((r_tot + prior_count) <= nmax)


class RotationCountConstraintWithHistory(RotationCountConstraint):

    KEY_NAME = 'rot_count_including_history'

    @classmethod
    def from_yml_dict(cls, *args, **kwargs):
        return super().from_yml_dict(*args, **kwargs, include_history=True)


class RotationCountNotConstraint(Constraint):

    def __init__(self, rotation, ct):
        self.rotation = rotation
        self.ct = ct

    def apply(self, model, block_assigned, residents, blocks, rotations, grids):

        for resident in residents:
            r_tot = sum(block_assigned[(resident, block, self.rotation)] for block in blocks)
            model.Add(r_tot != self.ct)


class TrueSomewhereConstraint(Constraint):

    def __init__(self, eligible_field):
        self.eligible_field = eligible_field
    
    def apply(self, model, block_assigned, residents, blocks, rotations, grids):

        s = 0
        for loc,value in np.ndenumerate(self.eligible_field[0]):
            x,y,z = loc
            if value:
                res = residents[x]
                block = blocks[y]
                rot = rotations[z]
                s += block_assigned[res, block, rot]
        model.Add(s >= 1)


class ProhibitedCombinationConstraint(Constraint):

    def __init__(self, prohibited_fields):
        self.prohibited_fields = prohibited_fields
    
    def apply(self, model, block_assigned, residents, blocks, rotations, grids):
        
        list_length = len(self.prohibited_fields)
        sum = 0
        for field in self.prohibited_fields:
            for loc,value in np.ndenumerate(field):
                x,y,z = loc
                if value == True:
                    res = residents[x]
                    block = blocks[y]
                    rot = rotations[z]
                    sum += block_assigned[res, block, rot]
        model.Add(sum < list_length)


class MarkIneligibleConstraint(Constraint):

    def __init__(self, eligible_field):
        self.eligible_field = eligible_field
    
    def apply(self, model, block_assigned, residents, blocks, rotations, grids):

        sum = 0
        for (x,y,z), value in np.ndenumerate(~self.eligible_field[0]):
            if value == True:
                res = residents[x]
                block = blocks[y]
                rot = rotations[z]
                sum += block_assigned[res, block, rot]
        model.Add(sum == 0)


class RotationWindowConstraint(Constraint):

    def __repr__(self):
        return "%s(%s,%s,%s)" % (
            self.__class__, self.resident, self.rotation, self.possible_blocks)

    def __init__(self, resident, rotation, possible_blocks):

        self.resident = resident
        self.rotation = rotation
        self.possible_blocks = possible_blocks

    def apply(self, model, block_assigned, residents, blocks, rotations, grids):

        # Rotation is assigned to the resident somewhere in the "possible_blocks"
        sum = 0
        for block in self.possible_blocks:
            sum += block_assigned[self.resident, block, self.rotation]

        model.Add(sum >= 1)


class MinIndividualScoreConstraint(Constraint):

    def __init__(self, scores, min_score):
        assert isinstance(min_score, numbers.Number)
        assert min_score == int(min_score)

        self.scores = scores

        self.min_score = int(min_score)

        logger.info(f"Created MinIndividualScoreConstraint with "
                     f"min_score {self.min_score}")


    def apply(self, model, block_assigned, residents, blocks, rotations, grids):

        assert set(residents) == set([res for res, _, _ in block_assigned.keys()])

        for res in residents:
            res_obj = 0
            ct = 0
            for rot in rotations:
                for blk in blocks:
                    k = (res, blk, rot)
                    x = self.scores[k]

                    assert int(x) == x, f"Score for {x} {k} is not an integer"

                    res_obj += int(x) * block_assigned[k]
                    ct += 1

            logger.debug(f"Added {ct} scores for {res} in MinIndividualScoreConstraint")
            model.Add(res_obj < self.min_score)

        logger.info(f"Applied individual resident utility < {self.min_score} to "
                     f"{len(residents)} residents")


class MinTotalScoreConstraint(Constraint):

    def __init__(self, scores, min_score):
        assert isinstance(min_score, numbers.Number)
        assert min_score == int(min_score)

        self.scores = scores
        self.min_score = int(min_score)

        logger.info(f"Created MinTotalScoreConstraint with "
                     f"min_score {self.min_score}")

    def apply(self, model, block_assigned, residents, blocks, rotations, grids):

        obj = 0
        for res in residents:
            for rot in rotations:
                for blk in blocks:
                    k = (res, blk, rot)
                    x = self.scores[k]

                    assert int(x) == x, f"Score for {x} {k} is not an integer"

                    obj += int(x) * block_assigned[k]

        model.Add(obj <= self.min_score)

        logger.info(f"Applied total utility < {self.min_score} to "
                     f"{len(residents)} residents")

class GroupCountPerResidentPerWindow(Constraint):

    @classmethod
    def from_yml_dict(cls, params, config):

        # assert cls.KEY_NAME in params

        rotations_in_group = resolve_group(params['group'], config['rotations'])

        if params.get('include_history', False):
            prior_counts = accumulate_prior_counts(
                rotations_in_group, config['residents'])
        else:
            prior_counts = {}

        resident_to_count = {}
        if type(params['count']) is list:
            assert len(params['count']) == 2
            nmin, nmax = params['count']
            for res in config['residents'].keys():
                resident_to_count[res] = (
                    nmin - prior_counts.get(res, 0),
                    nmax - prior_counts.get(res, 0)
                )
        else:
            resident_to_count = {}
            for k, ct in params['count'].items():
                nmin, nmax = ct
                for res in resolve_group(k, config['residents']):
                    resident_to_count[res] = (
                        nmin - prior_counts.get(res, 0),
                        nmax - prior_counts.get(res, 0)
                    )

        return cls(
            rotations_in_group=rotations_in_group,
            resident_to_count=resident_to_count,
            window_size=params.get('window_size', len(config['blocks']))
        )

    def __repr__(self):
        return "GroupCountPerResident(%s,%s,%s)" % (
             self.rotations_in_group, self.n_min, self.n_max)

    def __init__(self, rotations_in_group, resident_to_count, window_size):

        self.rotations_in_group = rotations_in_group
        self.resident_to_count = resident_to_count
        self.window = window_size

    def apply(self, model, block_assigned, residents, blocks, rotations, grids):

        for res, (nmin, nmax) in self.resident_to_count.items():
            # although add_window_count_constraint accepts a list of
            # residents, we want to change n_min and n_max using historical
            # data on a per-resident level, so we call it multiple times
            add_window_count_constraint(
                model,
                block_assigned,
                [res],
                blocks,
                self.rotations_in_group,
                self.window,
                nmin,
                nmax
            )


class ResidentGroupConstraint(Constraint):

    def __init__(self, rotation, eligible_residents):

        self.rotation = rotation
        self.eligible_residents = eligible_residents

    def apply(self, model, block_assigned, residents, blocks, grids):

        add_resident_group_constraint(
            model, block_assigned, residents, blocks,
            self.rotation, self.eligible_residents
        )


class EligibleAfterBlockConstraint(Constraint):

    def __init__(self, rotation, resident_group, eligible_after_block):

        self.rotation = rotation
        self.resident_group = resident_group
        self.eligible_after_block = eligible_after_block

    def apply(self, model, block_assigned, residents, blocks, rotations, grids):

        eligible_index = blocks.index(self.eligible_after_block)+1
        ineligible_blocks = blocks[:eligible_index]

        add_resident_group_constraint(
            model, block_assigned, residents, blocks, rotations,
            self.rotation, self.resident_group, ineligible_blocks
        )


class TimeToFirstConstraint(Constraint):

    def __init__(self, rotations_in_group, window_size):
        self.rotations_in_group = rotations_in_group
        self.window_size = window_size

    def apply(self, model, block_assigned, residents, blocks, rotations, grids):

        for res in residents:
            count = 0
            for blk in blocks[:self.window_size]:
                for rot in self.rotations_in_group:
                    count += block_assigned[(res, blk, rot)]

            model.Add(count > 1)


def add_must_be_followed_by_constraint(model, block_assigned, residents, blocks,
                                       rotation, following_rotations):

    for a_block, b_block in zip(blocks[0:-1], blocks[1:]):
        for resident in residents:
            a = block_assigned[(resident, a_block, rotation)]

            n_electives = 0

            for elective in following_rotations:
                n_electives += block_assigned[(resident, b_block, elective)]

            model.Add(
                n_electives > 0
            ).OnlyEnforceIf(a)


def add_window_count_constraint(model, block_assigned, residents, blocks,
                                rotations, window_size, n_min, n_max):

    n_blocks = len(blocks)
    n_full_windows = n_blocks - window_size + 1

    for res in residents:
        for i in range(n_full_windows):
            ct = 0
            for blk in blocks[ i : window_size + i ]:
                for rot in rotations:
                    ct += block_assigned[(res, blk, rot)]
            assert n_min is not None
            assert n_max is not None
            model.Add(ct >= n_min)
            model.Add(ct <= n_max)

def add_resident_group_constraint(model, block_assigned, residents, blocks,
                                  rotation, eligible_residents, ineligible_blocks = None):
    # If all blocks are indicated, adds a constrains that the sum of
    # blocks = 0 if the resident is not in "eligible residents" group
    for res in residents:
        if ineligible_blocks is None:
            n = sum(block_assigned[(res, block, rotation)] for block in blocks)
            model.Add(n == 0).OnlyEnforceIf(res not in eligible_residents)

    # If only certain 'eligible blocks' have been indicated,
    # makes sure that the eligible_residents are NOT assigned the rotation
    # during an ineligible block)
        else:
            n = sum(block_assigned[(res, block, rotation)] for block in ineligible_blocks)
            model.Add(n == 0).OnlyEnforceIf(res in eligible_residents)
