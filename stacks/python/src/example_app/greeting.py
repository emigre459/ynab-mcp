"""A tiny example module that proves the stack's tooling works end to end."""


def greet(name: str) -> str:
    """Return a personalized greeting.

    Parameters
    ----------
    name : str
        The name to greet. Must be non-empty.

    Returns
    -------
    str
        A greeting of the form ``"Hello, <name>!"``.

    Raises
    ------
    ValueError
        If ``name`` is empty.
    """
    if not name:
        raise ValueError("name must be non-empty")
    return f"Hello, {name}!"
