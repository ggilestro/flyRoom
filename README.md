# flyPush

[![CI](https://github.com/ggilestro/flyPush/actions/workflows/ci.yml/badge.svg)](https://github.com/ggilestro/flyPush/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

A modern SaaS web application for managing *Drosophila* (fruit fly) stocks in research laboratories. Multi-tenant architecture supporting multiple labs with complete data isolation, PWA support for desktop and mobile use.

## Features

### Stock Management
- **Create, organize, and track fly stocks** with genotypes, sources, locations, and custom notes
- **Tagging system** - categorize stocks with custom tags and colors for easy filtering
- **Soft delete** - safely archive stocks without permanent deletion
- **Full-text search** - find stocks by genotype, notes, or any field

### FlyBase Integration
- **Search 188,000+ stocks** from 7 major Drosophila stock centers worldwide:
  | Repository | Stocks |
  |------------|--------|
  | Bloomington (BDSC) | 91,288 |
  | Vienna (VDRC) | 38,371 |
  | Kyoto | 26,204 |
  | NIG-Fly | 20,783 |
  | KDRC | 7,020 |
  | FlyORF | 3,059 |
  | NDSSC | 2,072 |
- **One-click import** - search external databases and import directly to your collection
- **Automatic metadata** - FlyBase IDs, genotypes, and source URLs included

### Cross Planning
- **Plan genetic crosses** between stocks in your collection
- **Track cross status** - planned, in progress, completed, or failed
- **Link offspring** - connect completed crosses to resulting stocks
- **Cross history** - full audit trail of breeding experiments

### Label Generation
- **QR codes** - generate scannable codes for vial labeling
- **Barcodes** - support for standard barcode formats
- **Custom formats** - configurable label layouts

### Data Import/Export
- **Bulk import** from CSV or Excel files
- **Template download** - get properly formatted import templates
- **Validation** - preview and validate data before committing

### Multi-Tenant Architecture
- **Complete data isolation** - each lab's data is strictly separated
- **User management** - admins can invite and manage team members
- **Role-based access** - admin and user roles with appropriate permissions

### PWA Support
- **Installable** - add to home screen on mobile devices
- **Offline capable** - works without internet connection
- **Responsive design** - optimized for desktop, tablet, and mobile

## Technology Stack

| Layer | Technology |
|-------|------------|
| Backend | FastAPI (Python 3.11+) |
| Database | MariaDB 10.11+ |
| ORM | SQLAlchemy 2.0 + Alembic migrations |
| Authentication | JWT tokens + bcrypt password hashing |
| Frontend | Jinja2 + HTMX + Alpine.js + Tailwind CSS |
| PWA | Service Worker + Web App Manifest |
| Containers | Docker + docker-compose |
| Validation | Pydantic v2 |

## Quick Start

### Prerequisites

- Docker and docker-compose (recommended)
- Python 3.11+ (for local development)

### Using Docker (Recommended)

```bash
# Clone the repository
git clone https://github.com/ggilestro/flyPush.git
cd flyPush

# Copy and configure environment
cp .env.example .env
# Edit .env with your settings (change passwords!)

# Start the application
docker-compose up -d

# Open http://localhost:8000 in your browser
```

### Local Development

```bash
# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Start MariaDB (using Docker)
docker-compose up -d db

# Run database migrations
alembic upgrade head

# Start the development server
uvicorn app.main:app --reload
```

## Project Structure

```
flyPush/
├── app/
│   ├── main.py              # FastAPI application entry point
│   ├── config.py            # Settings via pydantic-settings
│   ├── dependencies.py      # Dependency injection
│   ├── db/                  # Database models and session
│   ├── auth/                # Authentication (JWT, passwords)
│   ├── stocks/              # Stock CRUD operations
│   ├── crosses/             # Cross planning and tracking
│   ├── labels/              # QR/barcode generation
│   ├── imports/             # CSV/Excel import
│   ├── tenants/             # Tenant/admin management
│   ├── plugins/             # External integrations (FlyBase)
│   │   └── flybase/         # FlyBase multi-repository plugin
│   ├── templates/           # Jinja2 HTML templates
│   └── static/              # CSS, JS, PWA assets
├── alembic/                 # Database migrations
├── tests/                   # Test suite
├── docs/                    # Documentation
├── docker-compose.yml
├── Dockerfile
└── pyproject.toml
```

## API Reference

### Authentication
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/auth/register` | POST | Create account and organization |
| `/api/auth/login` | POST | Login and receive JWT |
| `/api/auth/logout` | POST | Logout (invalidate token) |
| `/api/auth/me` | GET | Get current user info |

### Stocks
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/stocks` | GET | List stocks (paginated, filterable) |
| `/api/stocks` | POST | Create new stock |
| `/api/stocks/{id}` | GET | Get stock details |
| `/api/stocks/{id}` | PUT | Update stock |
| `/api/stocks/{id}` | DELETE | Soft delete stock |

### External Sources (FlyBase)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/plugins/sources` | GET | List available sources with repository info |
| `/api/plugins/sources/{source}/stats` | GET | Get source statistics |
| `/api/plugins/sources/{source}/repositories` | GET | List repositories |
| `/api/plugins/search` | GET | Search external database |
| `/api/plugins/details/{source}/{id}` | GET | Get stock details |
| `/api/plugins/import` | POST | Import stocks to collection |

### Crosses
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/crosses` | GET | List crosses |
| `/api/crosses` | POST | Plan a new cross |
| `/api/crosses/{id}` | GET | Get cross details |
| `/api/crosses/{id}/start` | POST | Start cross |
| `/api/crosses/{id}/complete` | POST | Complete cross |
| `/api/crosses/{id}/fail` | POST | Mark as failed |

### Labels
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/labels/formats` | GET | List label formats |
| `/api/labels/stock/{id}/qr` | GET | Get QR code image |
| `/api/labels/stock/{id}/barcode` | GET | Get barcode image |

## Running Tests

```bash
# Activate virtual environment
source .venv/bin/activate

# Run all tests
pytest

# Run with coverage report
pytest --cov=app --cov-report=html

# Run specific test module
pytest tests/test_plugins/ -v

# Run only fast unit tests (skip slow integration tests)
pytest -m "not slow"
```

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DATABASE_URL` | Database connection URL | Yes |
| `SECRET_KEY` | JWT signing key (32+ chars) | Yes |
| `DEBUG` | Enable debug mode | No (default: false) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT expiration | No (default: 30) |
| `SMTP_HOST` | SMTP server for emails | No |
| `SMTP_PORT` | SMTP port | No |
| `SMTP_USER` | SMTP username | No |
| `SMTP_PASSWORD` | SMTP password | No |

## Documentation

- **[User Guide](docs/user-guide.md)** - Complete guide for using flyPush
- **[Plugins Developer Guide](docs/plugins-dev-guide.md)** - Creating new integrations

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Install pre-commit hooks (first time only):
   ```bash
   source .venv/bin/activate
   pip install pre-commit
   pre-commit install
   ```
4. Make your changes
5. Run tests (`pytest`)
6. Pre-commit hooks will automatically run on commit to:
   - Format code with Black
   - Sort imports and lint with Ruff
   - Check for common issues (trailing whitespace, large files, etc.)
7. For manual checks:
   ```bash
   black .                 # Format code
   ruff check --fix .      # Lint and auto-fix
   pytest                  # Run tests
   ```
8. Commit your changes (hooks run automatically)
9. Push to the branch
10. Open a Pull Request

### Pre-commit Hooks

The project uses pre-commit hooks to ensure code quality. These run automatically on every commit:

- **Black** - Code formatting (100 char line length)
- **Ruff** - Fast Python linter with auto-fix
- **File checks** - Trailing whitespace, large files, merge conflicts, etc.

Manual-only hooks (run with `pre-commit run --hook-stage manual <hook-name>`):
- **mypy** - Static type checking
- **bandit** - Security vulnerability scanning

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Author

**Giorgio Gilestro** - [giorgio@gilest.ro](mailto:giorgio@gilest.ro)

- Lab website: [lab.gilest.ro](https://lab.gilest.ro)
- Personal website: [giorgio.gilest.ro](https://giorgio.gilest.ro)

## Acknowledgments

- [FlyBase](https://flybase.org) for providing comprehensive Drosophila stock data
- [Bloomington Drosophila Stock Center](https://bdsc.indiana.edu) and all contributing stock centers
- The FastAPI, HTMX, and Alpine.js communities
