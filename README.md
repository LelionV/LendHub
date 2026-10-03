# LendHub backend (Django + DRF)

Borrowers, guarantors and investors on one platform; admins control scoring, pricing and profit sharing.
Everything below the "Configurable in the database" heading is editable in `/admin/` with no code change.

## Run it
```bash
tar xzf lendhub-backend.tar.gz && cd lendhub
./setup.sh --demo            # venv, migrate, seed rules, demo users (password demo12345), runserver :8000
python manage.py createsuperuser
python -m pytest -q          # 15 end-to-end tests
```
Docker/PostgreSQL: copy `.env.example` to `.env`, then `docker compose up --build`
(the `cron` service runs overdue processing and score recalculation daily).

- Admin dashboard: `http://localhost:8000/dashboard/` (stats, loan review queue, CSV exports)
- Rules, users, ledger, audit trail: `http://localhost:8000/admin/`
- API base: `/api/v1/` (JWT: `Authorization: Bearer <access>`)

## Configurable in the database (admin → Rules)
| Model | Controls |
|---|---|
| Score factors | weight / on-off for repayment history, previous loans, late payments, outstanding balance, loan frequency |
| Score bands | score range → annual flat interest %, max amount, max term |
| Loan products | min/max amount, allowed terms, origination fee %, late fee %, grace days, default threshold, guarantor liability % |
| Distribution policies | investor / guarantor / platform % of interest (must total 100) |
| Platform settings | max open loans, guarantor exposure cap, new-borrower score, min investment, currency |
| Score adjustments | manual +/- points per user (any other admin-defined criterion) |

Each loan **snapshots** the band, rate, fees and split in force at application time, so later edits never alter existing loans.
Every rule change, loan transition, repayment and payout is written to the immutable audit log.

## Workflow
`PENDING_GUARANTOR → ADMIN_REVIEW → FUNDING → ACTIVE → COMPLETED` (or `GUARANTOR_REJECTED`, `REJECTED`, `OVERDUE`, `DEFAULTED`).
A guarantor is mandatory (DB constraint + service check; self-guarantee blocked). Transitions are only possible through
`loans.services.transition()`.

- **Pricing:** annual flat rate: `interest = amount × rate% × months/12`, equal monthly installments.
- **Funding:** investors fund a shared pool; an approved loan draws pro rata from free capital, and waits in `FUNDING` until the pool can cover it (auto-funds when money arrives or principal returns).
- **Repayment waterfall (oldest installment first):** late fee → interest → principal.
- **Profit split:** interest of each repayment is split by the loan's snapshot (investor share pro rata to funding; remainder cents to platform). Late fees and origination fees are platform revenue.
- **Default:** daily `process_overdue` marks overdue, charges the late fee once, and after `default_after_days` defaults the loan and opens a **guarantee claim** (`liability % × outstanding principal`). Admin settles claims with `settle_claim` (applied through the normal waterfall).
- **Ledger:** double-entry, append-only (`CASH`, `RECEIVABLE`, `POOL`, `REVENUE`, per-user `WALLET`). Every posting must balance.

## API summary
| Endpoint | Purpose |
|---|---|
| `POST auth/register/` `auth/login/` `auth/refresh/` | sign-up (choose roles) / JWT |
| `GET,PATCH me/` · `GET credit-score/` | profile + wallet · score, band, history |
| `GET guarantors/?q=` · `GET loan-products/` · `POST loans/quote/` | pick a guarantor, products, preview cost |
| `GET,POST loans/` · `GET loans/{id}/` · `POST loans/{id}/repay/` | borrower loans, schedule, repayment |
| `GET guarantees/requests/[?status=pending]` · `POST …/{id}/approve/` `reject/` | guarantor inbox + decision |
| `GET guarantor/earnings/` · `GET guarantor/claims/` | guarantor income / called guarantees |
| `GET,POST investments/` · `POST investments/{id}/withdraw/` · `GET investments/summary/` `earnings/` | investor funding & returns |
| `POST wallet/withdraw/` | withdraw earnings |
| `GET notifications/` · `POST notifications/read-all/` `{id}/read/` · `POST devices/` | in-app feed, push token registration |
| `GET transactions/` | the user's transaction history |

Errors are `{"detail": "..."}` with HTTP 400 for business-rule violations.

## Integration points
- **Payments:** `loans.services.record_repayment`, `funding.services.invest`, `withdraw_*` are the only money entry points. Connect your payment provider's callback to them and set `ALLOW_SELF_REPORTED_REPAYMENTS=0`.
- **Push:** `notifications.services.send_push` is a stub; wire FCM there (tokens stored via `POST devices/`).
- **Not included yet:** KYC document upload, PDF reports (CSV exports are provided), SMS/email.
