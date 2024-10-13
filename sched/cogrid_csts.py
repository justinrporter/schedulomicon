import itertools

from . import csts, parser
from .util import resolve_group

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


class VacationCooldownConstraint(csts.Constraint):

    KEY_NAME = 'cooldown'
    ALLOWED_YAML_OPTIONS = ['window', 'count', 'where']

    @classmethod
    def from_yml_dict(cls, params, config, groups_array):

        groups_array = util.build_groups_array(config)

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
