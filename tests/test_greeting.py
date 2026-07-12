from example_app.greeting import greet


def test_greet_returns_personalized_message() -> None:
    assert greet("World") == "Hello, World!"


def test_greet_rejects_empty_name() -> None:
    import pytest

    with pytest.raises(ValueError):
        greet("")
