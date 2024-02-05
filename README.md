# Fast Food Memes 

➡️ https://t.me/ffmemesbot ⬅️

## Local Development

### First Build Only
1. `cp .env.example .env`
2. `docker network create ffmemes_network`
3. `docker-compose up -d --build`

Don't forget to fill the local `.env` file with all envs you need.

### Test local changes

Before sending a PR you must test your new code. The easiest way is to run `ipython` shell, then import the functions you may need and test them. Note that ipython can run async functions without wrapping them with `asyncio.run(...)`.

``` shell
docker compose exec app ipython
```

### Linters
Format the code with `ruff --fix` and `ruff format`
```shell
docker compose exec app format
```

### Migrations
- Create an automatic migration from changes in `src/database.py`
```shell
docker compose exec app makemigrations *migration_name*
```
- Run migrations
```shell
docker compose exec app migrate
```
- Downgrade migrations
```shell
docker compose exec app downgrade -1  # or -2 or base or hash of the migration
```

### Tests
All tests are integrational and require DB connection. 

One of the choices I've made is to use default database (`postgres`), separated from app's `app` database.
- Using default database makes it easier to run tests in CI/CD environments, since there is no need to setup additional databases
- Tests are run with upgrading & downgrading alembic migrations. It's not perfect, but works fine. 

Run tests
```shell
docker compose exec app pytest
```
### Justfile
The template is using [Just](https://github.com/casey/just). 

It's a Makefile alternative written in Rust with a nice syntax.

You can find all the shortcuts in `justfile` or run the following command to list them all:
```shell
just --list
```
Info about installation can be found [here](https://github.com/casey/just#packages).

### Backup and Restore database
We are using `pg_dump` and `pg_restore` to backup and restore the database.
- Backup
```shell
just backup
# output example
Backup process started.
Backup has been created and saved to /backups/backup-year-month-date-HHMMSS.dump.gz
```

- Copy the backup file or a directory with all backups to your local machine
```shell
just mount-docker-backup  # get all backups
just mount-docker-backup backup-year-month-date-HHMMSS.dump.gz  # get a specific backup
```
- Restore
```shell
just restore backup-year-month-date-HHMMSS.dump.gz
# output example
Dropping the database...
Creating a new database...
Applying the backup to the new database...
Backup applied successfully.
```
