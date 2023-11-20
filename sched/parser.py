from functools import partial

import pyparsing as pp

from . import exceptions


def resolve_eligible_field(statement, groups_array, residents, blocks, rotations):

    block = pp.Combine(
        pp.Keyword("Block") + pp.White(' ', max=1) + pp.Word(pp.nums),
        adjacent=False
    )
    string_literal = pp.QuotedString('\'') | pp.QuotedString('"')
    operator = pp.oneOf('and or not & | !')
    term = pp.Combine(
        pp.OneOrMore(pp.Word(pp.alphanums + '-_.,\'()'),
                     stop_on=operator),
        adjacent=False,
        join_string=' '
    )

    term.setParseAction(partial(_resolve_identifier, groups_array=groups_array))
    block.setParseAction(partial(_resolve_identifier, groups_array=groups_array))
    string_literal.setParseAction(partial(_resolve_identifier, groups_array=groups_array))

    expression = pp.infix_notation(
        block | string_literal | term,
        [
            (pp.Keyword("not"), 1, pp.opAssoc.RIGHT, _not_parse_action),
            (pp.Keyword("and"), 2, pp.opAssoc.LEFT, _and_parse_action),
            (pp.Keyword("or"), 2, pp.opAssoc.LEFT, _or_parse_action)
        ],
        lpar=pp.Suppress('<'), rpar=pp.Suppress('>')
    )

    eligible_field = expression.parse_string(statement)

    return eligible_field

def _not_parse_action(arg):
    op, group_array = arg[0]
    assert op in ['not', '~']
    return ~group_array

def _and_parse_action(arg):
    assert all(o in ['&', 'and'] for o in arg[0][1::2])

    operands = arg[0][::2]
    a = operands[0]
    for o in operands:
        a = a & o

    return a

def _or_parse_action(arg):
    assert all(o in ['|', 'or'] for o in arg[0][1::2])

    operands = arg[0][::2]
    a = operands[0]
    for o in operands:
        a = a | o

    return a

def _resolve_identifier(gramm: pp.ParseResults, groups_array):
    group_name = gramm[0]
    try:
        return groups_array[group_name]
    except KeyError:
        raise exceptions.YAMLParseError(
            f"Couldn't find {group_name} in list of groups: {groups_array.keys()}"
        )
