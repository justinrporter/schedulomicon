import itertools
import numbers
import logging
import numpy as np

from . import exceptions, parser
from .exceptions import YAMLParseError
from .util import resolve_group, accumulate_prior_counts


logger = logging.getLogger(__name__)


class Constraint:
    """Base class for all scheduling constraints.

    Defines the interface for constraints that can be applied to a scheduling model.
    All concrete constraints must implement the apply method.
    """

    def apply(self, model, block_assigned, residents, blocks, rotations, grids):
        """Apply this constraint to the scheduling model.

        Args:
            model: The CP-SAT model to apply constraints to
            block_assigned: Dictionary mapping (resident, block, rotation) tuples to boolean variables
            residents: List of resident names
            blocks: List of block names (time periods)
            rotations: List of rotation names
            grids: Auxiliary data structures for constraint application
        """
        raise NotImplementedError("Constraint %s failed to implement apply" % self)

    @classmethod
    def _check_yaml_params(cls, root_entity, cst_params):
        """Validate parameters from YAML configuration.

        Args:
            root_entity: The entity (e.g., rotation name) this constraint is attached to
            cst_params: Dictionary of parameters from YAML

        Raises:
            YAMLParseError: If parameter is not in allowed options
        """
        for key in cst_params:
            if key not in cls.ALLOWED_YAML_OPTIONS:
                raise YAMLParseError(
                    f'On {root_entity}, option {key} not allowed (allowed '
                    f'options are {cls.xf_YAML_OPTIONS}).'
                )


class RotationCoverageConstraint(Constraint):
    """Enforces minimum and maximum number of residents assigned to a rotation per block.

    This constraint controls how many residents can be assigned to a specific rotation
    during each block. It can either specify minimum/maximum values or provide a list
    of allowed values for the number of residents.

    This is a rotation-scoped constraint, nested directly under a rotation name.

    YAML Example:
        residents:
          [...]
        rotations:
          Emergency:
            coverage: [1, 2]  # min 1, max 2 residents per block
            # OR, to restrict to specific values only:
            # coverage:
            #   allowed_values: [0, 2, 4]
        blocks:
          [...]
    """

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
    """Applies coverage constraints to a group of rotations rather than a single rotation.

    Similar to RotationCoverageConstraint but operates on a group of rotations defined
    in the configuration. This allows setting minimum/maximum values for multiple
    rotations collectively.

    This is a group-scoped constraint defined in the top-level group_constraints
    section, not nested under any individual rotation.

    Example
    -------

    .. code-block:: yaml

        residents:
          [...]
        rotations:
          Emergency:
            groups: [hospital]
          Surgery:
            groups: [hospital]
          [...]
        blocks:
          [...]
        group_constraints:
          - kind: group_coverage_constraint
            group: hospital         # Group name defined via `groups:` on rotations
            min: 2                  # At least 2 residents across all hospital rotations per block
            max: 4                  # At most 4 residents
            # OR use allowed_coverage: [0, 2, 4] for discrete values
            # blocks: [Block 1, Block 2]  # Optional: restrict to specific blocks
    """

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
    """Ensures a resident completes prerequisite rotations before being assigned to a rotation.

    This constraint requires that a resident must have completed a specified number of
    instances of prerequisite rotations before they can be assigned to the target rotation.
    Supports both single rotations and rotation groups as prerequisites.

    This is a rotation-scoped constraint, nested directly under a rotation name.

    YAML Example:
        residents:
          [...]
        rotations:
          ICU:
            prerequisite: [Tutorial 1, Tutorial 2]  # Must complete both before ICU
            # OR, to require a count from a rotation group:
            # prerequisite:
            #   heavy-rc: 1  # Must complete 1 rotation from the heavy-rc group first
        blocks:
          [...]
    """

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
    """Makes a resident ineligible for a rotation after meeting specified conditions.

    The inverse of PrerequisiteRotationConstraint - prevents assignment to a rotation
    once a resident has completed specified rotations or reached count thresholds.
    All constraints in the ineligibility list must be met for the resident to become ineligible.

    This is a rotation-scoped constraint, nested directly under a rotation name.

    YAML Example:
        residents:
          [...]
        rotations:
          SICU:
            ineligible_after:
              SICU-E4 CBY: 2  # Ineligible for SICU after completing 2 SICU-E4 CBY rotations
        blocks:
          [...]
    """

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
    """Restricts where consecutive sequences of a rotation can begin.

    Defines specific blocks where consecutive sequences of a rotation are allowed to start.
    This constraint works in conjunction with ConsecutiveRotationCountConstraint to
    control where multi-block sequences may begin.

    This is a rotation-scoped constraint, nested directly under a rotation name.
    It is typically used alongside consecutive_count.

    YAML Example:
        residents:
          [...]
        rotations:
          ICU:
            consecutive_count: 2
            allowed_roots: [Block 1, Block 5]  # Consecutive ICU sequences can only start at Block 1 or Block 5
        blocks:
          [...]
    """
    
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
    """Enforces that a rotation must occur in consecutive blocks of a specified length.

    This constraint ensures that when a resident is assigned to a rotation, they must
    be assigned to it for a specific number of consecutive blocks. It can also specify
    allowed or forbidden starting points (roots) for these consecutive sequences.

    This is a rotation-scoped constraint, nested directly under a rotation name.

    YAML Example:
        residents:
          [...]
        rotations:
          ICU:
            consecutive_count: 2  # Must be assigned for exactly 2 consecutive blocks
            # OR, with explicit root restrictions:
            # consecutive_count:
            #   count: 2
            #   forbidden_roots: [Block 1, Block 3]  # Can't start a sequence at these blocks
            #   allowed_roots: [Block 5A, Block 10A]  # Can only start sequences here
        blocks:
          [...]
    """

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

            for r in params['consecutive_count'].get('forbidden_roots', []):
                if r in config['blocks']:
                    forbidden_roots.append(r)
                else:
                    forbidden_roots.extend(resolve_group(r, config['blocks']))

            for r in params['consecutive_count'].get('allowed_roots', []):
                if r in config['blocks']:
                    assert r not in forbidden_roots
                    allowed_roots.append(r)
                else:
                    blks = resolve_group(r, config['blocks'])
                    for b in blks:
                        assert b not in forbidden_roots
                    allowed_roots.extend(blks)

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
    """Requires that a rotation must be followed immediately by specified rotations.

    This constraint ensures that after a resident completes this rotation,
    they must be assigned to one of the specified following rotations in the next block.
    Often used to ensure appropriate transitions between heavy rotations and lighter ones.

    This is a rotation-scoped constraint, nested directly under a rotation name.

    YAML Example:
        residents:
          [...]
        rotations:
          ICU:
            must_be_followed_by: [elective, Nephrology (DOM) CBY, Neurology (DOM) CBY]
            # After an ICU block, the next block must be one of the listed rotations
        blocks:
          [...]
    """

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
    """Prevents residents from being assigned to a rotation too soon again.

    Ensures that a resident cannot be assigned to a rotation more than a specified
    number of times within a sliding window of blocks.

    This is a rotation-scoped constraint and must be nested under a specific rotation
    in the YAML config, not at the root level.

    Example
    -------

    .. code-block:: yaml

        residents:
          [...]
        rotations:
          - name: ICU
            cool_down:
              window: 4  # Look at every 4-block window
              count: 1   # Maximum 1 instance of this rotation in any 4-block window
              suppress_for: ["Smith, John"]  # Optional: residents exempt from this constraint
        blocks:
          [...]
    """

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
    """Controls the total number of times a resident is assigned to a rotation.

    This constraint limits how many times a resident can be assigned to a specific rotation
    across all blocks. It can specify different limits for different residents or resident groups,
    and can be configured with minimum and maximum values.

    This is a rotation-scoped constraint, nested directly under a rotation name.

    YAML Example:
        residents:
          [...]
        rotations:
          ICU:
            rot_count: [0, 2]  # Each resident does 0–2 ICU blocks total
            # OR, a single exact count for all residents:
            # rot_count: 2
            # OR, different limits per resident group:
            # rot_count:
            #   CA1: [0, 1]  # CA1 residents: 0–1 ICU blocks
            #   CA2: [1, 2]  # CA2 residents: 1–2 ICU blocks
        blocks:
          [...]
    """

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
    """Extension of RotationCountConstraint that includes historical assignments.

    Similar to RotationCountConstraint, but also considers past rotation assignments
    from resident history when calculating rotation counts. This is useful for
    residents who have already completed parts of their training.

    This is a rotation-scoped constraint, nested directly under a rotation name.

    Example
    -------

    .. code-block:: yaml

        residents:
          Smith, John:
            history:
              ICU: 1  # Already completed 1 ICU block before this schedule
          [...]
        rotations:
          ICU:
            rot_count_including_history: [0, 2]  # 0–2 total ICU blocks including prior history
        blocks:
          [...]
    """

    KEY_NAME = 'rot_count_including_history'

    @classmethod
    def from_yml_dict(cls, *args, **kwargs):
        return super().from_yml_dict(*args, **kwargs, include_history=True)


class RotationCountNotConstraint(Constraint):
    """Prevents a specific exact count of a rotation from being assigned.

    This constraint ensures that a resident is not assigned to a rotation
    exactly a specified number of times. For example, it can be used to
    prevent exactly 1 assignment (forcing either 0 or 2+ assignments).

    This is a rotation-scoped constraint, nested directly under a rotation name.
    Note: unlike most rotation constraints, this one is handled directly in io.py
    rather than via a KEY_NAME / from_yml_dict pattern.

    YAML Example:
        residents:
          [...]
        rotations:
          ICU:
            not_rot_count: 1  # Resident cannot do exactly 1 ICU block; must do 0 or 2+
        blocks:
          [...]
    """

    def __init__(self, rotation, ct):
        self.rotation = rotation
        self.ct = ct

    def apply(self, model, block_assigned, residents, blocks, rotations, grids):

        for resident in residents:
            r_tot = sum(block_assigned[(resident, block, self.rotation)] for block in blocks)
            model.Add(r_tot != self.ct)


class TrueSomewhereConstraint(Constraint):
    """Ensures that at least one assignment from a set of possible assignments is made.

    This constraint forces the scheduler to make at least one assignment from a predefined
    set of eligible assignments. It's often used to implement resident preferences or
    requirements (e.g., "must do at least one of these rotations").

    .. deprecated::
        Use the ``sum > 0`` selector syntax instead (io.py:193).
        The ``true_somewhere`` YAML key is no longer supported.
    """

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


class FieldSumConstraint(Constraint):

    def __init__(self, satisfies_sum_fn, field):
        self.satisfies_sum_fn = satisfies_sum_fn
        self.field = field

    def apply(self, model, block_assigned, residents, blocks, rotations, grids):

        s = 0
        for loc, value in np.ndenumerate(self.field[0]):
            x,y,z = loc
            if value:
                res = residents[x]
                block = blocks[y]
                rot = rotations[z]
                s += block_assigned[res, block, rot]

        model.Add(self.satisfies_sum_fn(s))


class ProhibitedCombinationConstraint(Constraint):
    """Prevents certain combinations of assignments from occurring simultaneously.

    This constraint ensures that not all assignments in a specified set of prohibited
    assignments can be made simultaneously. Useful for preventing conflicting assignments
    or enforcing "either/or" style constraints.

    This is a per-resident constraint, nested under the resident name in the
    residents section using the key `prohibit`.

    Example
    -------

    .. code-block:: yaml

        residents:
          Smith, John:
            prohibit:
              - ICU and Block 1  # Smith cannot be assigned ICU in Block 1
          [...]
        rotations:
          [...]
        blocks:
          [...]
    """

    KEY_NAME = 'prohibit'

    @classmethod
    def from_yml_dict(cls, res, params, config, groups_array):
        prohibited_fields = []
        for selector_string in params[cls.KEY_NAME]:
            field = parser.resolve_eligible_field(
                f"{res} and ({selector_string})",
                groups_array,
                config['residents'].keys(),
                config['blocks'].keys(),
                config['rotations'].keys()
            )
            prohibited_fields.append(field[0])
        return cls(prohibited_fields)

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
    """Prevents assignments to ineligible resident-block-rotation combinations.

    This constraint marks specific resident-block-rotation combinations as ineligible,
    ensuring that these assignments cannot be made. The inverse of the eligibility field
    is used to identify and prohibit ineligible assignments.

    Note: this constraint class is not currently wired up in io.py.

    This is a per-resident constraint. When active it would be nested under
    the resident in the residents section using the key `ineligible`.

    Example (structure only; not currently active)
    ----------------------------------------------

    .. code-block:: yaml

        residents:
          Smith, John:
            ineligible:
              - Surgery and Block 1  # Smith cannot be assigned Surgery in Block 1
          [...]
        rotations:
          [...]
        blocks:
          [...]
    """

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
    """Ensures a resident is assigned to a rotation within a specific window of blocks.

    This constraint requires that a resident must be assigned to a specific rotation
    at least once within a defined set of blocks (the "window"). This is useful for
    enforcing requirements that residents complete certain rotations during specific
    time periods.

    Note: this constraint class is not currently wired up in io.py.

    This is a top-level config constraint, defined under the rotation_windows key.

    YAML Example (structure, not currently active):
        residents:
          [...]
        rotations:
          [...]
        blocks:
          [...]
        rotation_windows:
          Smith, John:
            Cardiology: [Block 1, Block 2, Block 3]  # Smith must do Cardiology in one of these blocks
    """

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
    """Enforces a minimum score/utility for each resident's schedule.

    This constraint ensures that each resident's schedule has a total utility score
    that meets or exceeds a specified minimum. Utilities/scores are assigned to
    individual resident-block-rotation assignments and then summed.

    Note: This constraint enforces a score LESS THAN the minimum (not ≥).
    Commonly used with negative scores to set a maximum threshold for negative utility.

    YAML Example:
        min_individual_score: -100  # Each resident's schedule must have score ≥ -100
    """

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
    """Enforces a minimum score/utility for the entire schedule across all residents.

    This constraint ensures that the total utility score of the entire schedule
    (summed across all residents) meets or exceeds a specified minimum threshold.
    Used to enforce overall schedule quality.

    Note: This constraint enforces a score LESS THAN OR EQUAL TO the minimum (not ≥).
    Commonly used with negative scores to set a maximum threshold for negative utility.

    YAML Example:
        min_total_score: -1000  # Total schedule score must be ≥ -1000
    """

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
    """Controls how many rotations from a group a resident can do within a time window.

    This constraint limits how many rotations from a specified group a resident
    can be assigned to within a sliding window of blocks. Can be configured with
    different limits for different residents or resident groups.

    This is a group-scoped constraint defined in the top-level group_constraints
    section.

    Example
    -------

    .. code-block:: yaml

        residents:
          [...]
        rotations:
          ICU:
            groups: [tough]
          Surgery:
            groups: [tough]
          [...]
        blocks:
          [...]
        group_constraints:
          - kind: window_group_count_per_resident
            group: tough        # Group name defined via `groups:` on rotations
            count: [0, 2]       # Each resident can do at most 2 tough rotations
            window_size: 3      # ...in any 3-block window
    """

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
    """Restricts which residents can be assigned to a specific rotation.

    This constraint limits a rotation to only be assigned to a specified group
    of eligible residents. All other residents will be ineligible for this rotation.

    Note: this constraint class is not currently wired up in io.py.

    This is a top-level config constraint, defined under the resident_groups key.

    YAML Example (structure, not currently active):
        residents:
          [...]
        rotations:
          [...]
        blocks:
          [...]
        resident_groups:
          Cardiology: ["Smith, John", "Jones, Mary"]  # Only these residents are eligible for Cardiology
    """

    def __init__(self, rotation, eligible_residents):
        self.rotation = rotation
        self.eligible_residents = eligible_residents

    def apply(self, model, block_assigned, residents, blocks, grids):

        add_resident_group_constraint(
            model, block_assigned, residents, blocks,
            self.rotation, self.eligible_residents
        )


class EligibleAfterBlockConstraint(Constraint):
    """Makes residents eligible for a rotation only after a specified block.

    This constraint prevents a group of residents from being assigned to a rotation
    until after a specific block in the schedule. They become eligible for the rotation
    in all blocks that follow the specified block.

    Note: this constraint class is not currently wired up in io.py.

    This is a top-level config constraint, defined under the eligible_after key.

    YAML Example (structure, not currently active):
        residents:
          [...]
        rotations:
          [...]
        blocks:
          [...]
        eligible_after:
          Cardiology:
            residents: ["Smith, John", "Jones, Mary"]
            block: Block 10  # These residents become eligible for Cardiology only after Block 10
    """

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
    """Ensures residents are assigned to a rotation group early in their schedule.

    This constraint requires that a resident must be assigned to at least one rotation
    from a specified group within an initial window of blocks at the beginning of
    the schedule. Used to ensure early exposure to important rotation types.

    This is a group-scoped constraint defined in the top-level group_constraints
    section.

    Example
    -------

    .. code-block:: yaml

        residents:
          [...]
        rotations:
          ICU:
            groups: [critical]
          Emergency:
            groups: [critical]
          [...]
        blocks:
          [...]
        group_constraints:
          - kind: time_to_first
            group: critical     # Group name defined via `groups:` on rotations
            window_size: 8      # Every resident must do at least one critical rotation in the first 8 blocks
    """

    def __init__(self, rotations_in_group, window_size):
        """Initialize a time to first constraint.

        Args:
            rotations_in_group: List of rotations in the group
            window_size: Number of initial blocks in which a rotation must be assigned
        """
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
    """Helper function to apply a must-be-followed-by constraint.
    
    Ensures that when a resident is assigned to a rotation in a block, they must be
    assigned to one of the specified following rotations in the next block.
    
    Args:
        model: The CP-SAT model
        block_assigned: Dictionary mapping (resident, block, rotation) tuples to boolean variables
        residents: List of resident names
        blocks: List of block names
        rotation: The rotation that must be followed
        following_rotations: List of allowed rotations that can follow
    """
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
    """Helper function to apply a sliding window count constraint.
    
    Ensures that within any consecutive window of blocks of a specified size,
    the number of times a resident is assigned to rotations from a specified set
    falls within given minimum and maximum bounds.
    
    Args:
        model: The CP-SAT model
        block_assigned: Dictionary mapping (resident, block, rotation) tuples to boolean variables
        residents: List of resident names
        blocks: List of block names
        rotations: List of rotations to count
        window_size: Size of the sliding window in blocks
        n_min: Minimum number of assignments allowed in the window
        n_max: Maximum number of assignments allowed in the window
    """
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
    """Helper function to apply eligibility constraints for resident groups.
    
    Either restricts a rotation to only eligible residents, or prevents eligible residents
    from being assigned to a rotation during specified ineligible blocks.
    
    Args:
        model: The CP-SAT model
        block_assigned: Dictionary mapping (resident, block, rotation) tuples to boolean variables
        residents: List of resident names
        blocks: List of block names
        rotation: The rotation to restrict
        eligible_residents: List of residents eligible for the rotation
        ineligible_blocks: Optional list of blocks where eligible residents cannot be assigned
    """
    # If all blocks are indicated, adds a constraint that the sum of
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
