"""The error of a drawing that does not convert, shared by the modules that run the tools."""


class ConversionError(Exception):
    """A drawing that the converter cannot turn into SVG."""
