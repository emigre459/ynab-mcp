from example_app.greeting import greet


def test_greet_returns_personalized_message() -> None:
    assert greet("Gridium") == "Hello, Gridium!"


def test_greet_rejects_empty_name() -> None:
    import pytest

    with pytest.raises(ValueError):
        greet("")
