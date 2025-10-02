# Agent Onboarding

Welcome! The notes below summarize the key workflows pulled from `README.md` so you can get productive quickly.

## Running the application locally
1. `cp .env.example .env`
2. `docker network create ffmemes_network`
3. `docker compose up -d --build`
4. Populate the new `.env` with the credentials you need before interacting with the services.

## Test execution
- All tests depend on the Alembic migrations that are automatically upgraded and downgraded by the `run_migrations` fixture in `tests/conftest.py`. No extra work is required when you call `pytest`, but keep the hook in mind if you introduce new migrations.
- The canonical Docker workflow is `docker compose exec app pytest`.
- When running tests outside Docker, export the environment variables seeded in `pytest.ini`:
  - `SITE_URL`
  - `DATABASE_URL`
  - `REDIS_URL`
  - `SITE_DOMAIN`
  - `SECURE_COOKIES`
  - `ENVIRONMENT`
  - `CORS_HEADERS`
  - `CORS_ORIGINS`

## Formatting and linting
Use Ruff for linting and formatting via Docker: `docker compose exec app format` (runs `ruff --fix` and `ruff format`).

## Async testing pattern
Follow the existing async pattern in `tests/recommendations/test_meme_queue.py` by decorating coroutine tests with `@pytest.mark.asyncio`.
