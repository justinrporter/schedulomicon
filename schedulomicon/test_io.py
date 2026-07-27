import itertools
import json
import os
import pickle

import pytest
import yaml

from . import io, exceptions, csts


@pytest.fixture
def dense_solution():
    """A dense 3-grid solution dict, as produced by solution_dict()."""
    return {
        'main': {
            ('R1', 'Block1', 'ICU'): 1,
            ('R1', 'Block1', 'Ortho'): 0,
            ('R1', 'Block2', 'ICU'): 0,
            ('R1', 'Block2', 'Ortho'): 1,
            ('R2', 'Block1', 'ICU'): 0,
            ('R2', 'Block1', 'Ortho'): 1,
            ('R2', 'Block2', 'ICU'): 1,
            ('R2', 'Block2', 'Ortho'): 0,
        },
        'backup': {
            ('R1', 'Block1'): 0,
            ('R1', 'Block2'): 1,
            ('R2', 'Block1'): 1,
            ('R2', 'Block2'): 0,
        },
        'vacation': {
            ('R1', 'Week 1', 'ICU'): 1,
            ('R1', 'Week 2', 'ICU'): 0,
            ('R2', 'Week 1', 'ICU'): 0,
            ('R2', 'Week 2', 'ICU'): 1,
        },
    }


def sparsify(solution):
    return {
        grid: {k: v for k, v in variables.items() if v != 0}
        for grid, variables in solution.items()
    }


def test_json_round_trip(tmp_path, dense_solution):
    fname = str(tmp_path / 'soln.json')
    io.write_solution(fname, dense_solution)
    assert io.read_solution(fname) == sparsify(dense_solution)


def test_json_schema_shape(tmp_path, dense_solution):
    fname = str(tmp_path / 'soln.json')
    io.write_solution(fname, dense_solution)

    with open(fname) as f:
        raw = json.load(f)

    assert raw['format_version'] == 1
    assert set(raw['grids']) == {'main', 'backup', 'vacation'}

    expected_key_fields = {
        'main': ['resident', 'block', 'rotation'],
        'backup': ['resident', 'block'],
        'vacation': ['resident', 'week', 'rotation'],
    }

    for grid_name, grid in raw['grids'].items():
        key_fields = grid['key_fields']
        assert key_fields == expected_key_fields[grid_name]

        keys = list(dense_solution[grid_name].keys())
        for i, field in enumerate(key_fields):
            assert grid['dimensions'][field] == \
                io.deduplicate_ordered([k[i] for k in keys])

        for row in grid['variables']:
            assert len(row) == len(key_fields) + 1
            assert row[-1] != 0


def test_unknown_grid_key_fallback(tmp_path):
    solution = {'mygrid': {('a', 'x'): 1, ('b', 'y'): 0}}
    fname = str(tmp_path / 'soln.json')
    io.write_solution(fname, solution)

    with open(fname) as f:
        raw = json.load(f)
    assert raw['grids']['mygrid']['key_fields'] == ['key_0', 'key_1']
    assert raw['grids']['mygrid']['dimensions'] == {
        'key_0': ['a', 'b'], 'key_1': ['x', 'y']
    }

    assert io.read_solution(fname) == {'mygrid': {('a', 'x'): 1}}


def test_known_grid_arity_mismatch_falls_back(tmp_path):
    # 'backup' normally has 2 key fields; a 3-tuple key must not be
    # mislabeled with the 2-field names.
    solution = {'backup': {('R1', 'Block1', 'extra'): 1}}
    fname = str(tmp_path / 'soln.json')
    io.write_solution(fname, solution)

    with open(fname) as f:
        raw = json.load(f)
    assert raw['grids']['backup']['key_fields'] == ['key_0', 'key_1', 'key_2']

    assert io.read_solution(fname) == solution


def test_write_unknown_extension_raises(tmp_path, dense_solution):
    with pytest.raises(exceptions.UnacceptableFileType):
        io.write_solution(str(tmp_path / 'soln.xlsx'), dense_solution)


def test_read_unknown_extension_raises(tmp_path):
    with pytest.raises(exceptions.UnacceptableFileType):
        io.read_solution(str(tmp_path / 'soln.xlsx'))


def test_missing_format_version_raises():
    with pytest.raises(exceptions.UnacceptableFileType):
        io.solution_from_json_dict({'grids': {}})


def test_wrong_format_version_raises():
    with pytest.raises(exceptions.UnacceptableFileType):
        io.solution_from_json_dict({'format_version': 2, 'grids': {}})


def test_malformed_row_raises():
    json_dict = {
        'format_version': 1,
        'grids': {
            'main': {
                'key_fields': ['resident', 'block', 'rotation'],
                'dimensions': {},
                'variables': [['R1', 'Block1', 1]],  # missing a key component
            }
        }
    }
    with pytest.raises(ValueError, match='main'):
        io.solution_from_json_dict(json_dict)


def test_duplicate_rows_warn_last_wins():
    json_dict = {
        'format_version': 1,
        'grids': {
            'main': {
                'key_fields': ['resident', 'block', 'rotation'],
                'dimensions': {},
                'variables': [
                    ['R1', 'Block1', 'ICU', 1],
                    ['R1', 'Block1', 'ICU', 0],
                ],
            }
        }
    }
    with pytest.warns(UserWarning):
        solution = io.solution_from_json_dict(json_dict)
    assert solution == {'main': {('R1', 'Block1', 'ICU'): 0}}


def test_empty_grid_round_trip(tmp_path):
    solution = {'main': {}}
    fname = str(tmp_path / 'soln.json')
    io.write_solution(fname, solution)
    assert io.read_solution(fname) == {'main': {}}


def test_pickle_round_trip(tmp_path, dense_solution):
    fname = str(tmp_path / 'soln.pkl')
    io.write_solution(fname, dense_solution)
    assert io.read_solution(fname) == dense_solution


def test_pickle_extension_round_trip(tmp_path, dense_solution):
    fname = str(tmp_path / 'soln.pickle')
    io.write_solution(fname, dense_solution)
    assert io.read_solution(fname) == dense_solution


def test_numbered_path_json():
    assert io.numbered_path('new.json', 1) == 'new-1.json'


def test_numbered_path_preserves_extension():
    assert io.numbered_path('results.csv', 2) == 'results-2.csv'
    assert io.numbered_path('soln.pkl', 10) == 'soln-10.pkl'


def test_numbered_path_preserves_directories():
    assert io.numbered_path(os.path.join('out', 'runs', 'new.json'), 3) == \
        os.path.join('out', 'runs', 'new-3.json')


def test_numbered_path_no_extension():
    assert io.numbered_path('new', 1) == 'new-1'


@pytest.fixture
def problem_config_path(tmp_path):
    config = {
        'residents': {'R1': {}, 'R2': {}},
        'rotations': {'Rotation1': {}, 'Rotation2': {}},
        'blocks': {'Block1': {}, 'Block2': {}},
    }
    path = tmp_path / 'config.yml'
    with open(path, 'w') as f:
        yaml.dump(config, f)
    return str(path)


def test_load_problem_basic(problem_config_path):
    problem = io.load_problem(problem_config_path)

    assert problem.residents == ['R1', 'R2']
    assert problem.blocks == ['Block1', 'Block2']
    assert problem.rotations == ['Rotation1', 'Rotation2']
    assert problem.cogrids == {}
    assert set(problem.config['residents']) == {'R1', 'R2'}
    assert 'R1' in problem.groups_array
    assert isinstance(problem.cst_list, list)
    assert problem.hint is None


SELECTOR_SOURCES = [
    ('resident group', 'residents', 'Resident', 'group'),
    ('block group', 'blocks', 'Block', 'group'),
    ('rotation group', 'rotations', 'Rotation', 'group'),
    ('resident name', 'residents', 'Resident', 'name'),
    ('block name', 'blocks', 'Block', 'name'),
    ('rotation name', 'rotations', 'Rotation', 'name'),
]


def config_with_selector_sources(*selected_sources):
    config = {
        'residents': {'Resident': {}},
        'blocks': {'Block': {}},
        'rotations': {'Rotation': {}},
    }

    for source, config_type, item, source_type in SELECTOR_SOURCES:
        if source not in selected_sources:
            continue
        if source_type == 'group':
            config[config_type][item]['groups'] = ['shared']
        else:
            config[config_type]['shared'] = config[config_type].pop(item)

    return config


@pytest.mark.parametrize(
    'first_source, second_source',
    itertools.combinations([source[0] for source in SELECTOR_SOURCES], 2),
)
def test_process_config_rejects_selector_namespace_collisions(
        first_source, second_source):
    config = config_with_selector_sources(first_source, second_source)

    with pytest.raises(exceptions.YAMLConfigurationMalformedError) as exc_info:
        io.process_config(config)

    message = str(exc_info.value)
    assert "'shared'" in message
    assert first_source in message
    assert second_source in message


def test_process_config_allows_reusing_group_within_scope():
    config = {
        'residents': {
            'Resident A': {'groups': ['shared', 'shared']},
            'Resident B': {'groups': ['shared']},
        },
        'blocks': {'Block': {}},
        'rotations': {'Rotation': {}},
    }

    _, _, _, _, groups_array = io.process_config(config)

    assert groups_array['shared'].all()


@pytest.mark.parametrize(
    'config_text, duplicate_key',
    [
        (
            """residents:
  R1: {}
rotations:
  Rotation1: {groups: [team]}
blocks:
  Block1: {}
group_constraints:
  - kind: group_coverage_constraint
    group: team
    min: 1
    max: 1
group_constraints:
  - kind: group_coverage_constraint
    group: team
    min: 0
    max: 1
""",
            'group_constraints',
        ),
        (
            """residents:
  R1:
    sum == 1:
      - Rotation1
    sum == 1:
      - Rotation1
rotations:
  Rotation1: {}
blocks:
  Block1: {}
""",
            'sum == 1',
        ),
    ],
)
def test_load_problem_rejects_duplicate_yaml_keys(
        tmp_path, config_text, duplicate_key):
    config_path = tmp_path / 'duplicate-key.yml'
    config_path.write_text(config_text)

    with pytest.raises(yaml.constructor.ConstructorError) as exc_info:
        io.load_problem(str(config_path))

    assert f"found duplicate key ({duplicate_key})" in str(exc_info.value)


def test_load_problem_require_appends_field_sum_constraint(problem_config_path):
    problem = io.load_problem(
        problem_config_path,
        require=('sum == 0: R1 and Block1 and Rotation1',)
    )

    assert len(problem.cst_list) == 1
    assert isinstance(problem.cst_list[-1], csts.FieldSumConstraint)


def test_load_problem_hint_round_trips(problem_config_path, tmp_path):
    solution = {
        'main': {
            ('R1', 'Block1', 'Rotation1'): 1,
            ('R1', 'Block2', 'Rotation2'): 0,
        }
    }
    hint_path = str(tmp_path / 'hint.json')
    io.write_solution(hint_path, solution)

    problem = io.load_problem(problem_config_path, hint_path=hint_path)

    assert problem.hint == {'main': {('R1', 'Block1', 'Rotation1'): 1}}


def test_load_problem_hint_omitted_is_none(problem_config_path):
    problem = io.load_problem(problem_config_path)
    assert problem.hint is None


def test_load_problem_coverage_csvs(problem_config_path, tmp_path):
    coverage_min = tmp_path / 'coverage_min.csv'
    coverage_min.write_text(
        ',Block1,Block2\n'
        'Rotation1,1,1\n'
        'Rotation2,0,0\n'
    )
    coverage_max = tmp_path / 'coverage_max.csv'
    coverage_max.write_text(
        ',Block1,Block2\n'
        'Rotation1,2,2\n'
    )

    problem = io.load_problem(
        problem_config_path,
        coverage_min=str(coverage_min),
        coverage_max=str(coverage_max),
    )

    coverage_csts = [c for c in problem.cst_list
                     if isinstance(c, csts.RotationCoverageConstraint)]
    assert len(coverage_csts) == 6  # 4 rmin + 2 rmax
    assert sum(1 for c in coverage_csts if c.rmin is not None) == 4
    assert sum(1 for c in coverage_csts if c.rmax is not None) == 2
