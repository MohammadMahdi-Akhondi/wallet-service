# Wallet Service

A Django wallet service. It supports wallet creation, deposits, and scheduled withdrawals that are executed asynchronously with Celery while keeping wallet balances consistent under concurrent workers.

## Tech Stack

- Python 3.10
- Django 3.2
- Django REST Framework
- PostgreSQL
- Redis
- Celery worker and Celery beat
- Docker Compose
- drf-spectacular for OpenAPI/Swagger

## Main Features

- Create wallets with a UUID and non-negative balance.
- Deposit positive amounts into a wallet.
- Schedule withdrawals for a future timestamp.
- Execute due withdrawals in background workers.
- Prevent wallet overdraft with database row locks.
- Record wallet movements in a transaction ledger.
- Handle third-party transfer success, explicit failure, and unknown outcomes.
- Recover stale `processing` withdrawals after worker interruption.

## API Endpoints

Base URL when running locally:

```text
http://localhost:8000
```

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/v1/wallets/` | Create a wallet. |
| `GET` | `/v1/wallets/{uuid}/` | Retrieve wallet balance and metadata. |
| `POST` | `/v1/wallets/{uuid}/deposit` | Deposit money into a wallet. |
| `POST` | `/v1/wallets/{uuid}/withdrawal` | Schedule a future withdrawal. |
| `GET` | `/swagger/` | Open Swagger UI. |
| `GET` | `/schema/` | OpenAPI schema. |

Example create wallet:

```bash
curl -X POST http://localhost:8000/v1/wallets/ \
  -H "Content-Type: application/json" \
  -d '{}'
```

Example deposit:

```bash
curl -X POST http://localhost:8000/v1/wallets/<wallet_uuid>/deposit \
  -H "Content-Type: application/json" \
  -d '{"amount": 1000}'
```

Example schedule withdrawal:

```bash
curl -X POST http://localhost:8000/v1/wallets/<wallet_uuid>/withdrawal \
  -H "Content-Type: application/json" \
  -d '{"amount": 500, "execute_at": "2026-09-16T12:30:00Z"}'
```

`execute_at` must be in the future. The service creates the withdrawal immediately, then Celery executes it at or after the requested time.

## How To Run

The easiest way to run the full system is Docker Compose. It starts:

- Django API on port `8000`
- PostgreSQL on port `5432`
- Redis on port `6379`
- Celery beat scheduler
- Three Celery workers
- Mock third-party transfer service on port `8010`

```bash
docker compose up --build
```

After startup, open:

```text
http://localhost:8000/swagger/
```

Run migrations manually if needed:

```bash
docker compose exec web python manage.py migrate
```

Run tests:

```bash
docker compose exec web python manage.py test wallets
```

Stop the project:

```bash
docker compose down
```

Stop the project and remove the local PostgreSQL volume:

```bash
docker compose down -v
```

## Local Run Without Docker

Docker Compose is recommended because the default settings expect PostgreSQL at host `db` and Redis at host `redis`. For a manual local run, provide environment variables for your local services:

```bash
cd wallet
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export POSTGRES_DB=wallet
export POSTGRES_USER=wallet
export POSTGRES_PASSWORD=wallet
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export CELERY_BROKER_URL=redis://localhost:6379/0
export CELERY_RESULT_BACKEND=redis://localhost:6379/1
export THIRD_PARTY_TRANSFER_BASE_URL=http://localhost:8010

python manage.py migrate
python manage.py runserver
```

In separate terminals:

```bash
cd wallet
celery -A wallet worker --loglevel=info
```

```bash
cd wallet
celery -A wallet beat --loglevel=info
```

The mock third-party service also needs to be running if withdrawals should complete end-to-end.

## Withdrawal Logic

The withdrawal flow is implemented in `wallet/wallets/services/withdrawal_service.py`.

### 1. Scheduling

`schedule_withdrawal(wallet_uuid, amount, execute_at)` validates that:

- `amount` is positive.
- `execute_at` is in the future.
- the wallet exists.

It then creates a `Withdrawal` with status `pending`. It does not reserve money during scheduling. This is intentional: funds are checked at execution time so the balance decision uses the latest wallet state.

After the database transaction commits, the service enqueues a Celery task with `eta=withdrawal.execute_at`. Using `transaction.on_commit` avoids dispatching a task for a withdrawal that later rolls back.

### 2. Finding Due Withdrawals

Celery beat runs `wallets.tasks.enqueue_due_withdrawals` every 5 seconds. It calls `claim_due_withdrawal_ids`, which selects due withdrawals with status `pending` or `retrying`.

The query uses `select_for_update(skip_locked=True)`, so multiple workers can scan due withdrawals without processing the same row at the same time.

### 3. Claiming A Withdrawal

`execute_withdrawal(withdrawal_id)` first calls `_claim_withdrawal`.

Inside a database transaction, the withdrawal row is locked. The service only continues if:

- status is `pending` or `retrying`;
- `execute_at <= now`.

The withdrawal is then marked `processing`, `locked_at` is updated, and `attempt_count` is incremented.

### 4. Reserving Funds

`_reserve_funds` locks both the withdrawal and wallet rows.

If a successful reservation already exists, the service treats reservation as already done and continues. This protects the flow from duplicate task execution.

If the wallet balance is too low:

- a failed reservation transaction is written;
- the withdrawal is marked `failed`;
- no third-party transfer call is made.

If the balance is enough:

- wallet balance is decreased;
- a successful `withdrawal_reservation` transaction is written.

The wallet has a database constraint requiring `balance >= 0`, and row locking prevents concurrent withdrawals from overdrawing the same wallet.

### 5. Calling The Third-Party Transfer

After funds are reserved, the service calls `ThirdPartyTransferClient.transfer` with:

- wallet UUID;
- amount;
- withdrawal ID.

The third-party client maps the response into one of three statuses:

- `success`: transfer completed.
- `failed`: third-party explicitly rejected or failed the transfer.
- `unknown`: timeout, connection error, unexpected request error, or ambiguous server error.

### 6. Finalizing The Result

For `success`:

- withdrawal is marked `success`;
- a `withdrawal_capture` transaction is created if missing.

For explicit `failed`:

- a `withdrawal_refund` transaction is created if missing;
- wallet balance is increased back by the withdrawal amount;
- withdrawal is marked `failed`.

For `unknown`:

- withdrawal is marked `unknown`;
- reserved funds stay deducted;
- no refund is created automatically.

The `unknown` state is conservative. Once money may have left the system, automatically refunding could create double-spend risk. A real production system should reconcile this state with the payment provider.

### 7. Stale Processing Recovery

Celery beat also runs `recover_stale_processing_withdrawals` every 5 seconds.

If a withdrawal remains `processing` longer than `WITHDRAWAL_STALE_PROCESSING_SECONDS`:

- if no successful reservation exists, it is marked `retrying` so it can be executed again;
- if a successful reservation exists, it is marked `unknown` because the worker may have stopped after reserving funds or while calling the third-party service.

This keeps stuck withdrawals visible and avoids unsafe automatic retries after money has already been reserved.

## Data Model Summary

`Wallet`

- `uuid`: public wallet identifier.
- `balance`: integer balance.
- constraint: balance cannot be negative.

`Withdrawal`

- linked to a wallet.
- has `amount`, `execute_at`, `status`, `attempt_count`, `locked_at`, `processed_at`, and `failure_reason`.
- statuses: `pending`, `processing`, `success`, `failed`, `unknown`, `retrying`.

`Transaction`

- append-only style ledger for wallet movements.
- transaction types: `deposit`, `withdrawal_reservation`, `withdrawal_capture`, `withdrawal_refund`.
- unique constraint on `(withdrawal, type)` prevents duplicate reservation, capture, or refund rows for the same withdrawal.

## Important Design Decisions

- Balance changes happen inside database transactions.
- Wallet rows are locked before changing balances.
- Withdrawal rows are locked before changing withdrawal state.
- Scheduled withdrawals do not reserve funds early.
- Third-party unknown outcomes are not auto-refunded.
- Celery tasks are safe to retry around internal state changes because transaction rows are checked before duplicate balance changes.
- `transaction.on_commit` is used before enqueueing the first ETA task.

## Configuration

The service reads configuration from environment variables:

| Variable | Default |
| --- | --- |
| `DJANGO_SECRET_KEY` | development-only fallback |
| `DJANGO_DEBUG` | `True` |
| `DJANGO_ALLOWED_HOSTS` | `*` |
| `POSTGRES_DB` | `wallet` |
| `POSTGRES_USER` | `wallet` |
| `POSTGRES_PASSWORD` | `wallet` |
| `POSTGRES_HOST` | `db` |
| `POSTGRES_PORT` | `5432` |
| `CELERY_BROKER_URL` | `redis://redis:6379/0` |
| `CELERY_RESULT_BACKEND` | `redis://redis:6379/1` |
| `THIRD_PARTY_TRANSFER_BASE_URL` | `http://third-party:8010` |
| `THIRD_PARTY_TRANSFER_TIMEOUT` | `3` |
| `WITHDRAWAL_SCAN_LIMIT` | `100` |
| `WITHDRAWAL_STALE_PROCESSING_SECONDS` | `300` |

## Future Improvements

- Add an idempotency key when calling the third-party transfer provider. The current request sends `withdrawal_id`, but a formal provider-supported idempotency key would make retries safer across network failures.
- Add a reconciliation job for `unknown` withdrawals. It should query the provider by idempotency key or provider reference and then mark the withdrawal as `success` or refund it if the provider confirms failure.
- Split settings by environment, for example `settings/local.py`, `settings/test.py`, and `settings/production.py`.
- Add `.env.example` and avoid keeping development defaults inside production settings.
- Use `uv` for faster, reproducible dependency management and lock files.
- Add authentication and authorization around wallet APIs.
- Add request-level idempotency for deposit and schedule-withdrawal APIs so clients can safely retry HTTP requests.
- Harden production deployment settings: `DEBUG=False`, strict `ALLOWED_HOSTS`, secure secret management, TLS, CORS restrictions, and health checks.
