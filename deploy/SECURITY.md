# Secrets

Each secret the server, the scheduler, the bot and the backup job hold: where it lives, who can read
it and how it is rotated. Setup is in `docs/deploy.md`; this page is the list to check against.

None of these is ever put in the repository, a log line, a reply or an error. `revisionist web serve`
checks three of them at start and refuses, naming the setting and never its value:

- `REVISIONIST_MASTER_KEY_FILE` names a file that anyone but its owner can read;
- `REVISIONIST_DB` is a `postgresql://` address with an empty password and a host other than
  `localhost`, `127.0.0.1`, `::1` or a socket directory;
- `--transport openrouter` is chosen and `REVISIONIST_OPENROUTER_KEY` is empty.

The mark secret checks itself when the server is built (`engine/web/map_api.py`, `mark_secret`).

| Secret | Where it lives | Who can read it | How it is rotated |
|---|---|---|---|
| Mark secret, `REVISIONIST_MARK_SECRET` (64 hex digits) | the unit's `revisionist.env`, and the protected configuration backup | the account the unit runs as; mode 0600 on the file | Generate 64 new hex digits, replace the line, restart every web worker together (all workers of a deployment share it). Every seat's map and playback key changes; replay hashes do not. Keep the old value only until the restart. |
| Master key file, `REVISIONIST_MASTER_KEY_FILE` (a path; the file holds 32 random bytes, base64) | a file outside the repo and outside the backup directory, mode 0600, or a systemd credential named `revisionist-master-key`; a copy kept off the box | the account the unit runs as; the server refuses to start if group or others can read it | It wraps every data key in `seal_keys`, so it cannot be swapped by editing the file: a new key needs every wrapped key unwrapped with the old one and wrapped again, which no command does yet. Until then, rotate only by a planned re-seal; never overwrite the file. `new_master_key` refuses to overwrite. |
| OpenRouter key, `REVISIONIST_OPENROUTER_KEY` | the free instance's `.env` file, read by `web serve --transport openrouter` and `scheduler run --transport openrouter` | the account the unit runs as; mode 0600 | Make a new key on the OpenRouter account, replace the line, restart the free instance and run `revisionist web check-transport`, then delete the old key on the account. The transport reads the key's usage at start and refuses on any cost, so a leaked key can only spend the free models. |
| Database password, in `REVISIONIST_DB` (role `revisionist_app`) | `revisionist.env`, and the role in Postgres | the account the unit runs as | `ALTER ROLE revisionist_app PASSWORD '...'` in Postgres, replace the address, restart the units that read it. |
| Admin database password, in `REVISIONIST_ADMIN_DSN` (role `revisionist_admin`) | `revisionist-admin.env` | the account the backup job and the operator run as | As the database password, for `revisionist_admin`; the backup unit reads it at each run, so no restart. |
| Discord bot token, `REVISIONIST_DISCORD_TOKEN` | `revisionist.env` | the account the bot and the scheduler run as | Reset it in the Discord developer portal, replace the line, restart the bot and the scheduler. |
| Mail relay address, `REVISIONIST_NOTICE_SMTP` (may carry a user and password) | `revisionist.env` | the account the scheduler runs as | Change the relay's password, replace the line; the next scheduler run reads it. |
| Players' passwords | `web_accounts.password_hash`, scrypt only | nobody; the plain value is not stored | A player changes it with a recovery code. A recovery code works once and ends every session. |
| Session tokens | a cookie in the browser (`HttpOnly`, `SameSite=Strict`); `web_sessions.token_hash` holds the hash only | the browser that holds it | A sign-in opens a new one; a sign-out or a recovery ends them. |
| Recovery codes | shown once at sign-up and at recovery; `web_recovery_codes.code_hash` holds the hash only | the player | A recovery issues a fresh set. |

Env files: `chmod 600`, owned by the unit's account, outside the checkout. `tests/test_security_secrets.py`
holds the start checks and a scripted session (sign-up, sign-in, recovery, a failed model call) that
fails if a password, a session token, a recovery code, a key or the mark secret reaches the log.
