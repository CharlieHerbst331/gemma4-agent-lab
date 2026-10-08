"""Input errors for the hygiene checker. The CLI maps these to exit code 2."""


class HygieneInputError(ValueError):
    """The patch, trace, run directory, or policy could not be read."""
