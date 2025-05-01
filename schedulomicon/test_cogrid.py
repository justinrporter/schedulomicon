import tempfile
import pytest

import numpy as np

from . import io, solve, callback, cogrid_csts, csts, parser
from .test_solve import SolnPrinterTest


class VacationWeekSolnPrinter(SolnPrinterTest):
    def __init__(self, *args, **kwargs):
        self.solutions = []
        self.solution_count = 0

        self.vacation_assignments = []

        super().__init__(*args, **kwargs)

    def on_solution_callback(self):

        super().on_solution_callback()

        self.vacation_assignments.append(self.vacation_df())


def test_vacation_cooldown():

    residents = ['R1', 'R2']
    blocks = ['Spring', 'Summer']
    rotations = ['Ortho', 'GS']

    status, solver, solution_printer, model, wall_runtime = solve.solve(
        residents=residents,
        blocks=blocks,
        rotations=rotations,
        groups_array={'R1': np.ones((2, 2, 2)),  # not actually correct but shouldn't matter
                      'R2': np.ones((2, 2, 2))},
        cst_list=[
            cogrid_csts.VacationMappingConstraint(
                n_vacations_per_resident=2,
                max_vacation_per_week={'mor': 1},
                max_total_vacation={'mor': 4, 'Ortho': 2},
                week_to_blocks={
                    'Week 1': ['Spring'],
                    'Week 2': ['Spring'],
                    'Week 3': ['Summer'],
                    'Week 4': ['Summer'],
                },
                pool_to_rotations={'mor': ['Ortho', 'GS']}
            ),
            cogrid_csts.VacationCooldownConstraint(
                window=2,
                count=1,
                # selector=parser.Selector(
                #     'R1 or R2',
                # )
            )
        ],
        soln_printer=VacationWeekSolnPrinter,
        score_functions=[],
        n_processes=1,
        cogrids={
            'vacation': {
                'n_vacations_per_resident': 1,
                'blocks': {
                    'Week 1': {'rotation': 'Spring'},
                    'Week 2': {'rotation': 'Spring'},
                    'Week 3': {'rotation': 'Summer'},
                    'Week 4': {'rotation': 'Summer'},
                },
                'pools': {
                    'mor': {
                        'rotations': ['Ortho', 'GS'],
                        'max_vacation_per_week': 2
                    }
                },
            },
            'backup': False
        },
        max_time_in_mins=5,
        hint=None
    )

    vacation_df = solution_printer.vacation_assignments[0]
    assert vacation_df.groupby(['resident']
        ).sum().to_dict()['on_vacation'] == {'R1': 2, 'R2': 2}

    assert vacation_df.groupby(['week']
        ).sum().to_dict()['on_vacation'] == {
            'Week 1': 1,
            'Week 2': 1,
            'Week 3': 1,
            'Week 4': 1,
        }

    r1 = vacation_df[vacation_df.resident == 'R1'].groupby('week').sum()['on_vacation'].values
    r2 = vacation_df[vacation_df.resident == 'R2'].groupby('week').sum()['on_vacation'].values

    assert np.all(r1 == [0, 1, 0, 1]) or np.all(r2 == [0, 1, 0, 1])
    assert np.all(r1 == [1, 0, 1, 0]) or np.all(r2 == [1, 0, 1, 0])
