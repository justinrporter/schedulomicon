import itertools

from . import csts, parser
from .util import resolve_group


# VACATION CONSTRAINTS -------------------------------------------------


class VacationMappingConstraint(csts.Constraint):

    @classmethod
    def from_yml_dict(cls, params, config):

        max_vacation_per_week = {
            k: v['max_vacation_per_week'] for k, v in config['vacation']['pools'].items()
            if 'max_vacation_per_week' in v
        }
        max_total_vacation = {
            k: v['max_total_vacation'] for k, v in config['vacation']['pools'].items()
            if 'max_total_vacation' in v
        }

        n_vacations_per_resident = int(config['vacation']['n_vacations_per_resident'])

        week_to_blocks = {
            week: spec['blocks'] for week, spec
            in config['vacation']['blocks'].items()
        }

        pool_to_rotations = {
            p: c['rotations'] for p, c
            in config['vacation']['pools'].items()
        }

        rots_with_pool = list(itertools.chain(*pool_to_rotations.values()))

        for r in config['rotations'].keys():
            assert r in rots_with_pool, f'Rotation "{r}" not found in vacation'

        return cls(
            n_vacations_per_resident=n_vacations_per_resident,
            max_vacation_per_week=max_vacation_per_week,
            max_total_vacation=max_total_vacation,
            week_to_blocks=week_to_blocks,
            pool_to_rotations=pool_to_rotations
        )

    def __init__(self, n_vacations_per_resident, max_vacation_per_week, max_total_vacation, week_to_blocks, pool_to_rotations):

        self.n_vacations_per_resident = n_vacations_per_resident
        self.max_vacation_per_week = max_vacation_per_week
        self.max_total_vacation = max_total_vacation
        self.week_to_blocks = week_to_blocks

        self.pool_to_rotations = pool_to_rotations

        self.rotation_to_pool = {}
        for pool, rotations in self.pool_to_rotations.items():
            for rot in rotations:
                self.rotation_to_pool[rot] = pool

    def apply(self, model, block_assigned, residents, blocks, rotations, grids):

        block_assigned = grids['main']['variables']
        vacation_assigned = grids['vacation']['variables']

        residents = grids['vacation']['dimensions']['residents']
        weeks = grids['vacation']['dimensions']['blocks']
        pools = grids['vacation']['dimensions']['pools']

        # STEP 1: if vacation is assigned on resident/rotation/week,
        # then resident/rotation/block must also be true.
        # this is enforced by way of a <= constraint since:
        # vacation assigned may be 0 or 1 if block is 1
        # vacation assigned must be 0 if block is 0

        for week in weeks:
            blocks = self.week_to_blocks[week]
            for block in blocks:
                for rotation in rotations:
                    for resident in residents:
                        model.Add(
                            vacation_assigned[resident, week, rotation] <=
                            block_assigned[resident, block, rotation]
                        )

        # STEP 2: limit the number of vacations that can be assigned per
        # pool

        for pool in pools:
            n_vacations_this_year = 0
            for week in weeks:
                n_vacations_this_week_for_this_pool = 0
                for rot in self.pool_to_rotations[pool]:
                    for res in residents:
                        n_vacations_this_week_for_this_pool += vacation_assigned[res, week, rot]

                if pool in self.max_vacation_per_week:
                    model.Add(
                        n_vacations_this_week_for_this_pool <= self.max_vacation_per_week[pool]
                    )
                n_vacations_this_year += n_vacations_this_week_for_this_pool

            if pool in self.max_total_vacation:
                model.Add(
                    n_vacations_this_year <= self.max_total_vacation[pool]
                )

        # STEP 3: require vacation gets assigned

        for res in residents:
            n_vac_this_resident = 0
            for rot in rotations:
                for week in weeks:
                    n_vac_this_resident += vacation_assigned[res, week, rot]
            model.Add(n_vac_this_resident == self.n_vacations_per_resident)

class ChosenVacationConstraint(csts.Constraint):

    def __init__(self, res, week):

        self.res = res
        self.week = week

    def apply(self, model, block_assigned, residents, blocks, rotations, grids):

        vacation_assigned = grids['vacation']['variables']

        ct = 0
        for rot in rotations:
            ct += vacation_assigned[self.res, self.week, rot]
        model.Add(ct == 1)

class VacationCooldownConstraint(csts.Constraint):

    KEY_NAME = 'cooldown'
    ALLOWED_YAML_OPTIONS = ['window', 'count', 'where']

    @classmethod
    def from_yml_dict(cls, params, config, groups_array):

        #groups_array = util.build_groups_array(config)

        return cls(
            window=params['window'],
            count=params.get('count', 1),
            # selector=parser.Selector(params['where'], groups_array=groups_array)
        )

    def __init__(self, window, count):

        self.window = window
        self.count = count
        # self.selector = selector

    def apply(self, model, block_assigned, residents, blocks, rotations, grids):

        vacation_assigned = grids['vacation']['variables']
        residents = grids['vacation']['dimensions']['residents']
        weeks = list(grids['vacation']['dimensions']['blocks'].keys())

        for res in residents:
            for i, w_i in enumerate(weeks):

                ct = 0
                for j in range(i, min(i+self.window, len(weeks))):

                    week = weeks[j]
                    for rot in rotations:
                        ct += vacation_assigned[res, week, rot]
                model.Add(ct <= self.count)


# BACKUP CONSTRAINTS ---------------------------------------------------


class SetBackupConstraint(csts.Constraint):

    def __init__(self, settings):
        self.settings = settings

    def apply(self, model, block_assigned, residents, blocks, rotations, grids):

        for k, v in self.settings.items():
            model.Add(
                grids['backup']['variables'][k] == v
            )


class BackupRequiredOnBlockBackupConstraint(csts.Constraint):

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


class RotationBackupCountConstraint(csts.Constraint):

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


class BanBackupBlockContraint(csts.Constraint):
    def __init__(self, resident, block):
        self.block = block
        self.resident = resident

    def apply(self, model, block_assigned, residents, blocks, rotations, grids):

        block_backup = grids['backup']['variables']

        model.Add(block_backup[(self.resident, self.block)] == 0)


class BackupEligibleBlocksBackupConstraint(csts.Constraint):

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


class BanRotationBlockConstraint(csts.Constraint):

    def __init__(self, block, rotation):
        self.block = block
        self.rotation = rotation

    def apply(self, model, block_assigned, residents, blocks, rotations, grids):

        for resident in residents:
            model.Add(block_assigned[(resident, self.block, self.rotation)] == 0)

