# Local Docker operations

The [root quick start](../README.md#quick-start) is the first-run path. Prerequisites:
a running Docker-compatible engine, Docker Compose v2 or newer, Git, and free loopback
ports 3000/8000. No host Python, Node, database or provider credentials are needed to run
the app. These are local development defaults, not a public deployment recipe. The frontend
is a production build, but keep the shipped API `APP__ENV=development` for local plain HTTP;
`APP__ENV=production` requires HTTPS CORS origins and Secure session cookies. A public
deployment needs its own TLS/security configuration, not these plain-HTTP defaults.

## What runs

| Service | Image/build | Role |
| --- | --- | --- |
| `web` | `apps/web/Dockerfile` | Non-root production Next.js standalone server, `public` and `.next/static`; browser at http://localhost:3000 |
| `api` | `apps/api/Dockerfile` | Non-root FastAPI, runs `alembic upgrade head` before opening port 8000; API/docs at http://localhost:8000/docs |
| `worker` | Same image as API | Celery prefork worker; waits for the migrated, healthy API |
| `db` | PostgreSQL, pinned in Compose | Private network hostname `db`; named `db-data` volume |
| `redis` | Redis, pinned in Compose | Private hostname `redis`; Celery broker/results and rate-limit counters |

API/worker share runtime settings, database and Redis URLs. The default `AI__PROVIDER=fake`
is an **offline deterministic model**, not a real AI provider. Identity providers are
disabled by default; password registration works without third-party credentials.
No demo data is seeded automatically. To opt in explicitly on a local database you own:

```sh
docker compose exec api python -m app.seed_demo --confirm-demo-accounts
```

Read the [demo-account warning and credentials](../apps/api/README.md#local-demo-data-explicit-optional)
first. You do not need the seed to create your own account through the web app.

`GET /health` is process liveness (also the Compose API healthcheck);
`GET /health/ready` checks PostgreSQL, Redis and the selected AI provider. `/status` in the
web app displays these checks. API health alone is not proof a worker consumed a job:
generate step proposals in a task, wait for completion, then explicitly accept them.

## Rebuild, update and stop safely

From the same checkout/project/configuration used at first run:

```sh
# After a reviewed source update, or an edit to NEXT_PUBLIC_* in .env:
docker compose up --build -d
# Inspect service state; inspect logs locally, redact before sharing.
docker compose ps
# Stop and remove containers/network, retaining named data volumes:
docker compose down
# Recreate later with the same project name and configuration:
docker compose up --build -d
```

A fresh checkout, `git pull`, browser cache clearing or `docker compose restart` **does
not rebuild images**. `up --build` builds changed sources and recreates affected services.
Do not use `--no-recreate` for an update. If a stale container remains, verify the Compose
project and working directory, then use `docker compose up --build -d --force-recreate`
on **that owned project only**. `docker compose images` and `docker compose ps` help check
the selected images/containers. Verify the expected UI and `/status` in your browser.
Rebuilding normally reuses locked dependency layers; it need not disable the build cache.

`db-data` retains accounts, projects, tasks, steps and attachment metadata.
`attachments-data` retains uploaded bytes at `/var/lib/ballasttasks/attachments`.
An empty attachment volume inherits ownership from the image (API uid 1001); changing
`STORAGE__LOCAL_DIRECTORY` also requires creating/owning that path in the Dockerfile.
Retain **both** volumes together. Never use `down -v`, prune, or remove volumes as an
update/troubleshooting step. Take database and file backups before significant upgrades;
rebuilding is not a backup or an automatic schema rollback. Changing PostgreSQL's major
version requires a planned database upgrade, not just an image change.

Redis has no configured durable named volume. Do not promise that queued jobs, unaccepted
proposals or counters survive Redis/container loss. Let active jobs settle before normal
shutdown; accepted steps are PostgreSQL rows. Never purge queues as an update step.

## Separate local stacks and alternate ports

The default Compose project is `ballasttasks`. Two checkouts using it address the **same
stack**, not independent copies. Use a distinct project name, configuration and free ports
before starting a second stack. Project names isolate application image tags as well as
containers, networks and named data volumes. Do not retag a shared application image.

For example, create a separate local file only if absent:

```sh
if [ ! -e .env.sandbox ]; then (umask 077; cp .env.example .env.sandbox); fi
```

Edit that file privately, keeping database credentials internally consistent and setting:

```dotenv
COMPOSE_PROJECT_NAME=ballasttasks-sandbox
BT_API_PORT=48080
BT_WEB_PORT=43000
NEXT_PUBLIC_API_URL=http://localhost:48080
CORS__ALLOWED_ORIGINS='["http://localhost:43000"]'
SSO__API_PUBLIC_BASE_URL=http://localhost:48080
SSO__WEB_CALLBACK_URL=http://localhost:43000/auth/callback
```

Check those example ports are free. Use **both** the interpolation file and runtime file
selector on every command (the API and worker must not silently load another `.env`):

```sh
export BT_ENV_FILE="$PWD/.env.sandbox"
docker compose -p ballasttasks-sandbox --env-file "$BT_ENV_FILE" -f docker-compose.yml up --build -d
docker compose -p ballasttasks-sandbox --env-file "$BT_ENV_FILE" -f docker-compose.yml ps
docker compose -p ballasttasks-sandbox --env-file "$BT_ENV_FILE" -f docker-compose.yml down
```

Use the same prefix for `exec`, rebuilds and any other lifecycle operation. Bare `make up`
or `make down` is for the default quick-start configuration, not an alternate stack.
The container-network URLs remain `db:5432` and `redis:6379`, regardless of host HTTP ports.
The public API URL is used by the **browser**: do not set it to `http://api:8000`.
Keep API and web same-site and use one browser hostname consistently (`localhost` and
`127.0.0.1` are different origins). Use isolated browser profiles for independent local
stacks: browser cookies are host-scoped, not port-scoped. See the authoritative
[authentication contract](architecture.md#authentication) for session/deployment requirements.

## Troubleshooting and private configuration

- **Port in use:** do not stop another stack; choose free ports and update all matching
  browser URLs/CORS origins, then rebuild the web image.
- **Old UI or wrong API:** verify the selected project/ports and image IDs first.
  `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_SERVICE_MODE` are build-time inputs; changing only
  a running container's environment does nothing. Rebuild with `up --build` and keep
  `NEXT_PUBLIC_SERVICE_MODE=http` for the real backend, not the explicit in-memory demo.
- **API not healthy:** inspect local API/migration and database logs. Incorrect database
  credentials in an existing `.env` are not fixed by copying the template over it.
  `POSTGRES_*` initialises an empty volume only; changing a password in the file does not
  change a password already stored in PostgreSQL. Preserve the volume and reconcile
  credentials intentionally.
- **Upload permission failure:** check the configured mount and non-root ownership; do not
  run the API as root or make files world-writable to hide it.
- **Generation remains pending:** check worker readiness and matching Redis/database/AI
  settings. Readiness does not exercise the queue. Default fake AI needs no key; real
  providers are optional operator configuration, not a first-run requirement.
- **429:** respect `Retry-After`; retain the normal auth 10/60s, authenticated 120/60s and
  anonymous 60/60s limits. Do not reset counters or increase limits to make a smoke pass.

Never commit `.env` files or credentials. Each app's `.dockerignore` allows only production
build inputs, excluding local env and test artifacts. Runtime secrets belong in the runtime
file, not Dockerfile `ARG`/`ENV`, build arguments or public frontend variables. Avoid sharing
raw `docker compose config`, `docker inspect`, environment dumps or credential-bearing logs;
those can expose secrets even though the Docker build context excludes them.
