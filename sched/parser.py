import pyparsing as pp


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

    term.setParseAction(resolve_identifier)
    block.setParseAction(resolve_identifier)
    string_literal.setParseAction(resolve_identifier)

    expression = pp.infixNotation(
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
    l_arg, op, r_arg = arg[0]
    assert op in ['&', 'and']
    return l_arg & r_arg

def _or_parse_action(arg):
    l_arg, op, r_arg = arg[0]
    assert op in ['|', 'or']
    return l_arg | r_arg

def _resolve_identifier(gramm: pp.ParseResults):
    assert gramm[0] in groups_array.keys()
    return groups_array[gramm[0]]
