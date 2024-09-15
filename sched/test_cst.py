import pytest

from . import csts, io, exceptions


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
