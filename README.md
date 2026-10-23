# Contractor Leads API

Backend for a Finnish contractor marketplace where customers publish
construction, renovation and maintenance projects, and contractors spend
credits to unlock customer contact details.

The MVP exists to answer one question from the business roadmap:
**will contractors pay for access to customer leads?**

## Quick start

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync                      # install locked dependencies (incl. dev/test)
uv run pytest                # run the test suite
LEADS_ADMIN_EMAIL=admin@example.com LEADS_ADMIN_PASSWORD=change-me \
  uv run uvicorn app.main:create_app --factory --reload
```

Interactive API docs are served at `http://localhost:8000/docs`.

With Docker:

```sh
docker build -t contractor-leads-api .
docker run --rm contractor-leads-api pytest              # tests, no network needed
docker run --rm -p 8000:8000 contractor-leads-api        # API server
```

## Configuration

All settings are read from environment variables in `app/config.py`.

| Variable | Default | Purpose |
|---|---|---|
| `LEADS_DATABASE_URL` | `sqlite:///./leads.db` | SQLAlchemy database URL |
| `LEADS_SECRET_KEY` | `dev-secret-change-me` | Signs access tokens; **set in production** |
| `LEADS_PAYMENT_WEBHOOK_SECRET` | `dev-webhook-secret` | Verifies payment notifications |
| `LEADS_UNLOCK_COST` | `1` | Credits charged per contact unlock |
| `LEADS_MEDIA_DIR` | `./media` | Where project images are stored |
| `LEADS_ADMIN_EMAIL` / `LEADS_ADMIN_PASSWORD` | unset | Admin account created at startup if missing |

Project categories and credit packages are defined in `app/config.py`
(`CATEGORIES`, `DEFAULT_PACKAGES`) pending business confirmation.

## Project layout

```
app/
  main.py          app factory, error handling, router wiring
  config.py        settings, categories, credit packages
  models.py        SQLAlchemy models
  schemas.py       request/response models
  i18n.py          English/Finnish messages and language resolution
  security.py      password hashing and signed tokens (stdlib only)
  validators.py    Finnish Y-tunnus validation
  payments.py      PaymentProvider interface + FakePaymentProvider
  deps.py          DB session, current user and role guards
  services/
    credits.py     credit ledger, contact unlocking
    presenters.py  response building, contact visibility rules
    reports.py     marketplace metrics
  routers/         auth, profiles, projects, credits, messages, reviews, admin
tests/             pytest suite, one file per area
```

## Roadmap coverage

| Phase | Feature | Main endpoints |
|---|---|---|
| 2 | Registration, profiles, public contractor profiles | `/auth/*`, `/me/customer-profile`, `/me/contractor-profile`, `/contractors` |
| 3 | Project creation, images, approval | `/projects`, `/projects/{id}/submit`, `/projects/{id}/images`, `/admin/projects/*` |
| 4 | Public browsing, search, locked contact area | `GET /projects`, `GET /projects/{id}`, `/categories` |
| 5 | Credits and contact unlocking | `/projects/{id}/unlock`, `/me/unlocks`, `/me/credits` |
| 6 | Credit packages, payments, manual credits | `/credits/packages`, `/credits/checkout`, `/payments/webhook`, `/admin/contractors/{id}/credits` |
| 7 | Project-based messaging | `/projects/{id}/conversations`, `/conversations/{id}/messages`, `/me/conversations` |
| 8 | Reviews and moderation | `/reviews`, `/admin/reviews` |
| 9 | Admin operations and reports | `/admin/users`, `/admin/transactions`, `/admin/payments`, `/admin/unlocks`, `/admin/reports` |

English and Finnish are supported through `?lang=fi` or the
`Accept-Language` header. Errors use the shape
`{"error": {"code": "...", "message": "..."}}`, where `code` is stable and
`message` is localized.

## Business rules

**Projects**

- Lifecycle: `draft → submitted → published`, or `submitted → rejected → submitted`.
  An admin can move a project to `removed` from `submitted`, `published` or `rejected`.
- Only `published` projects are public. Owners and admins can see their
  projects in every status.
- Editing a published project sends it back to `submitted` for re-approval.
- Images are limited by count and size, and their type is detected from the
  file content (JPEG, PNG, WebP), not from the client's header.

**Credits and unlocking**

- Customer contact details stay hidden until a contractor unlocks the project.
  The owner and admins can always see them.
- A contractor pays at most once per project. A unique database constraint
  enforces this, and a repeat unlock returns `charged: false`.
- Any number of contractors may unlock the same project.
- Unlocked contacts stay available, even if the project is later removed.
- Every balance change is written to an append-only ledger
  (`credit_transactions`), together with the resulting balance. A guarded
  UPDATE keeps balances from going negative.

**Payments**

- Buying credits creates a `pending` payment and returns the provider's
  checkout URL. Credits are added only after a correctly signed `paid`
  webhook arrives.
- Webhooks are idempotent. A repeated or late notification never credits a
  payment twice and never changes a completed payment.

**Messaging and reviews**

- A conversation is tied to one project and one contractor, and it can start
  only after that contractor has unlocked the project.
- A customer can review a contractor only for one of their own projects that
  the contractor unlocked, and only once per project. Hidden reviews are left
  out of public profiles and ratings.

**Accounts**

- Admins are provisioned through configuration. Self-registration as an
  admin is refused.
- Suspended users can't log in, their tokens stop working, and suspended
  contractors disappear from public listings.

## Not yet implemented

- **Real payment provider.** The roadmap leaves the choice to the business.
  To add one, implement `PaymentProvider` in `app/payments.py` and pass it to
  `create_app(payment_provider=...)`.
- **Database migrations.** Tables are created at startup with
  `metadata.create_all`. Add Alembic before the first production deploy.
- **Frontend and email notifications.** This repository is the API only.

## License

[MIT](LICENSE) © 2026 dan-gusmao
