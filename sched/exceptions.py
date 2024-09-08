class YAMLParseError(Exception):
    def __init__(self, message):
        super().__init__(message)


class IncompatibleConstraintsException(Exception):
    def __init__(self, message):
        super().__init__(message)
