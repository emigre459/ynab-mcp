---
description: Python best practices and patterns for this repo (structure, style, types, testing, errors, docs)
appliesTo: "**/*.py"
---

# Python Best Practices

## Project Structure
- Use src-layout with `src/<your_package>/`
- Place tests in `tests/` directory parallel to `src/`
- Keep configuration in `conf/` or as environment variables
- Store requirements in `pyproject.toml`
- Use `uv` for package and environment management
- Use `templates/` for Jinja2 templates
- Use `docker/` when building microservices content (e.g. Dockerfiles, docker-compose.yaml files, etc.)

## Code Style
- Follow Black code formatting
- Use isort for import sorting
- Follow PEP 8 naming conventions:
  - snake_case for functions and variables
  - PascalCase for classes
  - UPPER_CASE for constants
- Maximum line length of 88 characters (Black default)
- Use absolute imports over relative imports

## Type Hints
- Use type hints for all function parameters and returns
- Import types from `typing` module
- Use `Optional[Type]` instead of `Type | None`
- Use `TypeVar` for generic types
- Define custom types in `types.py`
- Use `Protocol` for duck typing

## Databases
- Use proper connection pooling
- Define models in separate modules
- Implement proper relationships
- Use proper indexing strategies
- Implement proper pagination

## Authentication
- Use proper session security
- Implement CSRF protection
- Use proper role-based access control

## API Design
- Use FastAPI for RESTful endpoints but always consider making it an MCP (Model Context Protocol) server first. Ideally both use patterns (standard REST and LLM calls via MCP) can be supported.
- Implement proper request validation
- Use proper HTTP status codes
- Handle errors consistently
- Use proper response formats
- Implement proper rate limiting
- Use best practice patterns for handling traffic spikes, including concurrent connections management

## Testing
- ALWAYS use a red-green test-driven development (TDD) pattern when building new features: tests first that fail, then get them passing with feature building
- Use pytest for testing
- Use the xdist plugin for parallelizing tests for speed
- Make tests fully independent — `make tests` runs `pytest -n auto`, so order is
  not guaranteed. If two tests must share filesystem or other side-effecting
  state, enforce it with a fixture (autouse / parametrize / monkeypatch), never
  with implicit ordering or implicit cleanup. Default filesystem tests to
  `tmp_path`; if code resolves paths from a project-rooted constant (e.g.
  `PROJECT_ROOT`), monkeypatch it to `tmp_path` so each test gets its own sandbox.
- Write tests for **everything**
- Use pytest-cov for coverage
- Implement proper fixtures
- Use proper mocking with pytest-mock
- Test all error scenarios

## Security
- Use HTTPS in production
- Implement proper CORS
- Sanitize all user inputs
- Use proper session configuration
- Implement proper logging
- Follow OWASP guidelines

## Performance
- Use proper caching when appropriate
- Implement database query optimization
- Use background tasks for heavy operations
- Monitor application performance

## Error Handling
- Create custom exception classes
- Use proper try-except blocks
- Implement proper logging and logging levels
- Do not use f-strings for logs, use % notation (so they are lazy-evaluated)
- Do not use print statements outside of standalone scripts, anything worth seeing on the terminal should be a logger.X() call
- Return proper error responses
- Handle edge cases properly
- Use proper error messages

## Documentation
- Use NumPy-style docstrings on every function/method/class, matching the VSCode
  autoDocstring extension's **numpy preset** (the house style). Sections in order:
  one-line imperative summary, then `Parameters` / `Returns` (or `Yields`) /
  `Raises` as applicable. Document defaults in the description with the literal
  phrase `, by default <value>` (not `, default <value>` on the type line).
- Put type hints on the signature itself — every parameter and return. Prefer
  PEP 604 unions (`X | None`) over `Optional[X]`. Type hints are not a substitute
  for the docstring sections, nor vice versa: ship both.
- Docstrings **everywhere**. Carve-outs: `__init__` may omit `Returns`; trivial
  one-line helpers may omit `Parameters`/`Returns` (type hints still required);
  Pydantic `@model_validator` may use short prose form; test functions may use a
  one-line docstring but still annotate non-fixture args.
- Document all public APIs
- Keep README.md updated with all new changes
- Use proper inline comments
- Generate API documentation
- Document environment setup

## Development Workflow
- Use virtual environments (venv)
- Implement pre-commit hooks
- Use proper Git workflow
- Follow semantic versioning
- Use proper CI/CD practices
- Implement proper logging

## Dependencies
- Pin dependency versions
- Use requirements.txt for production
- Separate dev dependencies
- Use proper package versions
- Regularly update dependencies
- Check for security vulnerabilities