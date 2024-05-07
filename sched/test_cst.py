from . import csts


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
            'Gen Surg': {'group': ['mor']},
            'Ortho': {'group': ['mor']},
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
        'group_constraints': {
            'kind': 'group_coverage_constraint',
            'group': 'mor',
            'count': [2, 2]
        }
    }

    cst = csts.PrerequisiteRotationConstraint.from_yml_dict(
        "Gen Surg", config['rotations']['Gen Surg'], config
    )

