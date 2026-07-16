from functools import partial

import numpy as np
import pytest

from ortools.sat.python import cp_model

from . import csts, io, exceptions, score


def test_prereq_cst_yaml_parsing():
    config = {
        'residents': {
            'Resident 1': {'history': ['Tutorial', 'Gen Surg']},
            'Resident 2': {'history': ['Tutorial', 'Gen Surg']},
            'Resident 3': {'history': ['Tutorial']},
            'Resident 4': {'history': ['Tutorial']}
        },
        'rotations': {
            'Tutorial': {'rot_count_including_history': [1, 1]},
            'Gen Surg': {'prerequisite': ['Tutorial']},
            'SICU-E4': {'prerequisite': {'Gen Surg': 1, 'Tutorial': 1}},
            'OB': {'prerequisite': ['Gen Surg']}
        },
        'blocks': {
            'Spring': {},
            'Summer': {},
            'Fall': {},
            'Winter': {}
        }
    }

    # checking format for prerequisite: [Gen Surg]
    cst = csts.PrerequisiteRotationConstraint.from_yml_dict(
        "Gen Surg", config['rotations']['Gen Surg'], config
    )

    assert cst.rotation == 'Gen Surg'
    assert cst.prior_counts == {
        'Tutorial': {'Resident 1': 1, 'Resident 2': 1,
                     'Resident 3': 1, 'Resident 4': 1}
    }
    assert cst.prerequisites == {('Tutorial',): 1}

    # checking format for prerequisite: [Gen Surg]
    cst = csts.PrerequisiteRotationConstraint.from_yml_dict(
        "SICU-E4", config['rotations']['SICU-E4'], config
    )

    assert cst.rotation == 'SICU-E4'
    assert cst.prior_counts == {
        'Gen Surg': {'Resident 1': 1, 'Resident 2': 1,
                     'Resident 3': 0, 'Resident 4': 0},
        'Tutorial': {'Resident 1': 1, 'Resident 2': 1,
                     'Resident 3': 1, 'Resident 4': 1}
    }
    assert cst.prerequisites == {('Tutorial',): 1, ('Gen Surg',): 1}


def test_coverage_cst_yaml_parsing():
    config = {
        'residents': {
            'Resident 1': {'group': ['CA1']},
            'Resident 2': {'group': ['CA1']},
            'Resident 3': {'group': ['CA2']},
            'Resident 4': {'group': ['CA3']}
        },
        'rotations': {
            'Gen Surg': {'groups': ['mor']},
            'Ortho': {'groups': ['mor']},
            'Ob': {},
            'PATA': {},
            'SICU-E4': {}
        },
        'blocks': {
            'Spring': {},
            'Summer': {},
            'Fall': {},
            'Winter': {}
        },
        'group_constraints': [
            {
                'kind': 'group_coverage_constraint',
                'group': 'mor',
                'count': [2, 2]
            },
            {
                'kind': 'group_coverage_constraint',
                'group': 'mor',
                'allowed_coverage': [2]
            }
        ]
    }

    cst = csts.GroupCoverageConstraint.from_yml_dict(
        config['group_constraints'][0], config
    )

    assert cst.rotations == ['Gen Surg', 'Ortho']
    assert cst.rmin == 2
    assert cst.rmax == 2
    assert cst.allowed_vals is None

    cst = csts.GroupCoverageConstraint.from_yml_dict(
        config['group_constraints'][1], config
    )

    assert cst.rotations == ['Gen Surg', 'Ortho']
    assert cst.rmin is None
    assert cst.rmax is None
    assert cst.allowed_vals == [2]


def test_consecutive_cst_yaml_parsing():
    config = {
        'rotations': {
            'Gen Surg': {'consecutive_count': 2},
        },
    }

    constraints = io.generate_rotation_constraints(config, [])

    assert constraints[0].rotation == 'Gen Surg'
    assert constraints[0].count == 2



def test_consecutive_cst_yaml_parsing():
    config = {
        'blocks': {'Bl1': {}, 'Bl2': {}, 'Bl3': {}},
        'rotations': {
            'Gen Surg': {'consecutive_count': {
                'count': 3,
                'forbidden_roots': ['Bl2', 'Bl3']
            }},
        },
    }

    constraints = io.generate_rotation_constraints(config, [])

    assert constraints[0].rotation == 'Gen Surg'
    assert constraints[0].count == 3
    assert tuple(constraints[0].forbidden_roots) == ('Bl2', 'Bl3')


def test_consecutive_cst_cool_down_incompatible():
    config = {
        'rotations': {
            'Gen Surg': {
                'consecutive_count': 2,
                'cool_down': {'window': 2}
            },
        },
    }

    with pytest.raises(exceptions.IncompatibleConstraintsException):
        constraints = io.generate_rotation_constraints(config, [])


def test_consecutive_cst_forbidden_root_group():
    config = {
        'blocks': {
            'Block 1A': {'groups': ['a_block']},
            'Block 1B': {'groups': ['b_block']},
            'Block 2A': {'groups': ['a_block']},
            'Block 2B': {'groups': ['b_block']},
        },
        'rotations': {
            'Gen Surg': {'consecutive_count': {
                'count': 2,
                'forbidden_roots': ['Block 1A', 'b_block']
            }},
        },
    }

    constraints = io.generate_rotation_constraints(config, [])

    assert constraints[0].rotation == 'Gen Surg'
    assert constraints[0].count == 2
    assert tuple(constraints[0].forbidden_roots) == ('Block 1A', 'Block 1B', 'Block 2B')


def test_all_group_count_per_resident():
    config = {
        'residents': {
            'R1': {'groups': ['CA1'], 'history': ['Ro1']},
            'R2': {'groups': ['CA1'], 'history': ['Ro2', 'Ro2']},
        },
        'rotations': {
            'Ro1': {'groups': ['g1']},
            'Ro2': {'groups': ['g1']},
        },
        'blocks': {
            'Bl1': {}, 'Bl2': {}, 'Bl3': {}
        },
        'group_constraints': [{
            'kind': 'all_group_count_per_resident',
            'group': 'g1',
            'count': {
                'CA1': [0, 4],
            },
            'include_history': True
        }]
    }

    constraints = io.generate_constraints_from_configs(config, [])
    c = constraints[0]

    assert c.rotations_in_group == ['Ro1', 'Ro2']
    assert c.resident_to_count == {'R1': (-1, 3), 'R2': (-2, 2)}
    assert c.window == 3

def test_ineligible_before_cst():
    config = {
        'residents': {
            'R1': {'groups': ['CA1'], 'history': ['Ro1']},
            'R2': {'groups': ['CA1'], 'history': ['Ro2', 'Ro2']},
        },
        'rotations': {
            'Ro1': {'ineligible_after': {'Ro2': 1}},
            'Ro2': {},
        },
        'blocks': {
            'Bl1': {}, 'Bl2': {}, 'Bl3': {}
        },
    }

    constraints = io.generate_rotation_constraints(config, [])

    c = constraints[0]
    assert c.prior_counts == {'Ro2': {'R1': 0, 'R2': 2}}
    assert c.prerequisites == {('Ro2',): 1}
    assert c.rotation == 'Ro1'

#test _pools - write out the yaml at the top. it should be like test solve. test_cst shows how tests work. write a function that says test_whatever. write code and then write asserts. pytest will tell you if the asserts fail.
#  longer tests in test_solve.  residents, blocks, rotations, cogrids_avail, groups_array = io.process_config(config)


def test_allowed_roots_yaml_parsing():
    config = {
        'blocks': {'Bl1': {}, 'Bl2': {}, 'Bl3': {}},
        'rotations': {
            'ICU': {'allowed_roots': ['Bl1', 'Bl3']},
        },
    }
    constraints = io.generate_rotation_constraints(config, [])
    assert constraints[0].rotation == 'ICU'
    assert tuple(constraints[0].allowed_roots) == ('Bl1', 'Bl3')


def test_prohibit_wired_up():
    config = {
        'residents': {
            'R1': {'prohibit': ['Bl1 and Ro1', 'Bl2 and Ro1']},
            'R2': {},
        },
        'rotations': {'Ro1': {}, 'Ro2': {}},
        'blocks': {'Bl1': {}, 'Bl2': {}, 'Bl3': {}},
    }
    _, _, _, _, groups_array = io.process_config(config)
    constraints = io.generate_resident_constraints(config, groups_array)
    prohibited = [c for c in constraints if isinstance(c, csts.ProhibitedCombinationConstraint)]
    assert len(prohibited) == 1
    assert len(prohibited[0].prohibited_fields) == 2


def test_unknown_key_in_rotation_raises():
    config = {
        'rotations': {'Ro1': {'group': ['g1']}},
        'residents': {},
        'blocks': {},
    }
    with pytest.raises(ValueError, match="Unknown key 'group' in rotation 'Ro1'"):
        io.generate_rotation_constraints(config, [])


def test_unknown_key_in_rotation_suggests_correction():
    config = {
        'rotations': {'Ro1': {'group': ['g1']}},
        'residents': {},
        'blocks': {},
    }
    with pytest.raises(ValueError, match="Did you mean 'groups'"):
        io.generate_rotation_constraints(config, [])


def test_unknown_key_in_resident_raises():
    config = {
        'residents': {'R1': {'group': ['CA1']}},
        'rotations': {},
        'blocks': {},
    }
    with pytest.raises(ValueError, match="Unknown key 'group' in resident 'R1'"):
        io.generate_resident_constraints(config, [])


def test_unknown_key_in_resident_suggests_correction():
    config = {
        'residents': {'R1': {'group': ['CA1']}},
        'rotations': {},
        'blocks': {},
    }
    with pytest.raises(ValueError, match="Did you mean 'groups'"):
        io.generate_resident_constraints(config, [])


def test_unknown_key_in_block_raises():
    config = {
        'blocks': {'Bl1': {'group': ['g1']}},
        'residents': {},
        'rotations': {},
    }
    with pytest.raises(ValueError, match="Unknown key 'group' in block 'Bl1'"):
        io.generate_block_constraints(config, [])


def _solve_with_min_total(bound):
    """Build a tiny two-grid model where both variables are forced on
    (total score 2) and apply a MinTotalScoreConstraint bound."""
    model = cp_model.CpModel()
    a = model.NewBoolVar('a')
    b = model.NewBoolVar('b')
    model.Add(a == 1)
    model.Add(b == 1)

    grids = {
        'main': {'variables': {('x',): a}},
        'backup': {'variables': {('y',): b}},
    }

    grid_and_functions = [
        ('main', partial(score.objective_from_score_dict,
                         scores={('x',): 1}, default_score=0)),
        ('backup', partial(score.objective_from_score_dict,
                           scores={('y',): 1}, default_score=0)),
    ]

    cst = csts.MinTotalScoreConstraint(
        grid_and_functions=grid_and_functions, min_score=bound)
    cst.apply(
        model,
        block_assigned=grids['main']['variables'],
        residents=[], blocks=[], rotations=[],
        grids=grids
    )

    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    return solver.StatusName(status)


def test_min_total_score_constraint_bound_enforced():
    # both grids sum to 2, which exceeds the bound of 1
    assert _solve_with_min_total(bound=1) == 'INFEASIBLE'


def test_min_total_score_constraint_satisfied_is_feasible():
    assert _solve_with_min_total(bound=2) in ('OPTIMAL', 'FEASIBLE')


def _legacy_min_total_scores(tmp_path):
    """Build a dense main-grid score dict the way external API callers do:
    rankings CSV -> io.rankings_from_csv -> score.score_dict_from_df."""
    residents = ['R1']
    blocks = ['Bl1']
    rotations = ['ICU', 'Cardiology']

    csv = tmp_path / 'rankings.csv'
    csv.write_text("resident,ICU,Cardiology\nR1,3,1\n")

    scores = score.score_dict_from_df(
        io.rankings_from_csv(csv), residents, blocks, rotations, None)
    return residents, blocks, rotations, scores


def _solve_with_legacy_min_total(tmp_path, bound):
    """Force R1 into ICU (score 3) and apply the legacy positional-form
    MinTotalScoreConstraint with the given bound."""
    residents, blocks, rotations, scores = _legacy_min_total_scores(tmp_path)

    model = cp_model.CpModel()
    block_assigned = {
        (res, blk, rot): model.NewBoolVar(f'{res}_{blk}_{rot}')
        for res in residents for blk in blocks for rot in rotations
    }
    model.Add(block_assigned[('R1', 'Bl1', 'ICU')] == 1)
    model.Add(block_assigned[('R1', 'Bl1', 'Cardiology')] == 0)

    cst = csts.MinTotalScoreConstraint(scores, bound)
    cst.apply(
        model,
        block_assigned=block_assigned,
        residents=residents, blocks=blocks, rotations=rotations,
        grids={'main': {'variables': block_assigned}},
    )

    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    return solver.StatusName(status)


def test_min_total_score_legacy_positional_bound_enforced(tmp_path):
    # the forced assignment scores 3, which exceeds the bound of 2
    assert _solve_with_legacy_min_total(tmp_path, bound=2) == 'INFEASIBLE'


def test_min_total_score_legacy_positional_satisfied_is_feasible(tmp_path):
    assert _solve_with_legacy_min_total(tmp_path, bound=3) in (
        'OPTIMAL', 'FEASIBLE')


def test_min_total_score_legacy_attributes_preserved(tmp_path):
    _, _, _, scores = _legacy_min_total_scores(tmp_path)
    cst = csts.MinTotalScoreConstraint(scores, 5)
    assert cst.scores is scores
    assert cst.min_score == 5


def test_min_total_score_legacy_keyword_call(tmp_path):
    _, _, _, scores = _legacy_min_total_scores(tmp_path)
    cst = csts.MinTotalScoreConstraint(scores=scores, min_score=5)
    assert cst.scores is scores
    assert cst.min_score == 5


def test_min_total_score_both_forms_raises():
    with pytest.raises(ValueError):
        csts.MinTotalScoreConstraint(
            scores={}, min_score=0, grid_and_functions=[])


def test_min_total_score_neither_form_raises():
    with pytest.raises(ValueError):
        csts.MinTotalScoreConstraint(min_score=0)


def test_sum_key_in_resident_is_valid():
    config = {
        'residents': {'R1': {'sum > 2': ['Ro1 or Ro2']}},
        'rotations': {'Ro1': {}, 'Ro2': {}},
        'blocks': {'Bl1': {}},
    }
    _, _, _, _, groups_array = io.process_config(config)
    constraints = io.generate_resident_constraints(config, groups_array)
    assert len(constraints) == 1


def _sum_dsl_config():
    config = {
        'residents': {'R1': {}, 'R2': {}},
        'rotations': {'Ro1': {}, 'Ro2': {}, 'Ro3': {}},
        'blocks': {'Bl1': {}, 'Bl2': {}},
    }
    _, _, _, _, groups_array = io.process_config(config)
    return config, groups_array


def test_field_sum_constraint_builder():
    config, groups_array = _sum_dsl_config()

    cst = io.field_sum_constraint('sum > 2', 'Ro1 or Ro2', config, groups_array)

    assert isinstance(cst, csts.FieldSumConstraint)
    assert cst.satisfies_sum_fn(3)
    assert not cst.satisfies_sum_fn(2)
    expected = groups_array['Ro1'] | groups_array['Ro2']
    assert np.array_equal(cst.field[0], expected)


def test_parse_cli_constraint():
    config, groups_array = _sum_dsl_config()

    cst = io.parse_cli_constraint('sum == 0: R1 and Bl1', config, groups_array)

    assert isinstance(cst, csts.FieldSumConstraint)
    assert cst.satisfies_sum_fn(0)
    assert not cst.satisfies_sum_fn(1)
    expected = groups_array['R1'] & groups_array['Bl1']
    assert np.array_equal(cst.field[0], expected)


def test_parse_cli_constraint_missing_colon_raises():
    config, groups_array = _sum_dsl_config()
    with pytest.raises(exceptions.YAMLParseError, match="missing a ':'"):
        io.parse_cli_constraint('sum == 0 R1 and Bl1', config, groups_array)


def test_parse_cli_constraint_empty_selector_raises():
    config, groups_array = _sum_dsl_config()
    with pytest.raises(exceptions.YAMLParseError, match="empty selector"):
        io.parse_cli_constraint('sum == 0:   ', config, groups_array)


def test_parse_cli_constraint_bad_operator_raises():
    config, groups_array = _sum_dsl_config()
    with pytest.raises(exceptions.YAMLParseError, match="not recognized"):
        io.parse_cli_constraint('sum ~= 1: R1', config, groups_array)