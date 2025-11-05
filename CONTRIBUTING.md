# Contributing to Asya

We welcome contributions to Asya! This document provides guidelines for contributing to this open source project.

## Code of Conduct

By participating in this project, you agree to abide by our code of conduct. Please be respectful and constructive in all interactions.

## Development Setup

### Prerequisites

- Go 1.23+
- Python 3.13+
- **[uv](https://github.com/astral-sh/uv)** (required for Python development)
- Docker and Docker Compose
- Make
- kubectl (for Kubernetes development)

### Installation

1. Fork and clone the repository:
```bash
git clone https://github.com/your-username/asya.git
cd asya
```

2. Install development dependencies:
```bash
make install-dev
make install-hooks
```

3. Verify your setup:
```bash
make test-unit
```

## Development Workflow

### Making Changes

1. Create a feature branch:
```bash
git checkout -b feature/your-feature-name
```

2. Make your changes following our coding standards
3. Add tests for new functionality
4. Run the test suite:
```bash
make test-all
```

5. Run linting:
```bash
make lint
```

### Submitting Changes

1. Push your branch to your fork
2. Create a pull request with:
   - Clear description of changes
   - Reference to any related issues
   - Test results
   - Documentation updates if needed

## Coding Standards

### Go Code
- Follow standard Go formatting (`gofmt`)
- Use meaningful variable and function names
- Add comments for exported functions
- Write unit tests for new functionality

### Python Code
- Follow PEP 8 style guidelines
- Use type hints where appropriate
- Write docstrings for functions and classes
- Use `uv` for dependency management

### Documentation
- Update README.md for significant changes
- Add inline code comments for complex logic
- Update API documentation as needed

## Testing

### Unit Tests
```bash
make test-unit                    # All unit tests
make test-unit-sidecar           # Go sidecar tests
make test-unit-gateway           # Go gateway tests  
make test-unit-runtime           # Python runtime tests
```

### Integration Tests
```bash
make test-integration            # All integration tests
```

### End-to-End Tests
```bash
cd examples/deployment-minikube
./deploy.sh && ./test-e2e.sh
```

## Security

- Never commit secrets, API keys, or sensitive data
- Report security vulnerabilities through our [security policy](SECURITY.md)
- Follow secure coding practices

## Getting Help

- Check existing [issues](https://github.com/deliveryhero/asya/issues)
- Join discussions in [GitHub Discussions](https://github.com/deliveryhero/asya/discussions)
- Review the [documentation](docs/index.md)

## License

By contributing to Asya, you agree that your contributions will be licensed under the Apache 2.0 License.
