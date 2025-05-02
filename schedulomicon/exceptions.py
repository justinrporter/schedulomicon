class YAMLConfigurationMalformedError(Exception):
    def __init__(self, message):
        super().__init__(message)

class YAMLParseError(Exception):
    def __init__(self, message):
        super().__init__(message)


class IncompatibleConstraintsException(Exception):
    def __init__(self, message):
        super().__init__(message)


class NameNotFound(Exception):
    def __init__(self, message, name):
        super().__init__(message)
        self.name = name


class UnacceptableFileType(Exception):
    def __init__(self, message):
        super().__init__(message)
