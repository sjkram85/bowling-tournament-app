# bowling-tournament-app

## Prism A.I. (Grok)

Co-Pilot, the Rule Arbitrator, roster reading, and lane photos call xAI Grok. Nothing in the app calls Google Gemini.

In the Streamlit app's secrets, set:

```toml
XAI_API_KEY = "the key from the xAI console"
```

Optional model overrides. Leave them unset to use the defaults (`grok-4.7` for Co-Pilot and the Rule Arbitrator, `grok-4.6` once when that model is busy or over its limit):

```toml
XAI_MODEL = "grok-4.7"
XAI_RULES_MODEL = "grok-4.7"
XAI_BACKUP_MODEL = "grok-4.6"
```

`GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_RULES_MODEL`, and `GEMINI_BACKUP_MODEL` are not read. Those secrets can be removed from the Streamlit app after this is deployed. Save the secrets, then reboot the app once so it picks them up.

The desk stores tournament data in an on-disk SQLite file, `tournament.db`.

`TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` are not read. Streamlit Secrets entries for Turso are ignored, and a deploy does not need a Turso database. Those secrets can be removed from the Streamlit app after this is deployed. Hosted Turso is not the live database.

On Streamlit Cloud the disk is ephemeral. A sleep or a redeploy can reset the file. During a live tournament, while the app is up and people are using it, the file stays. With the secrets below set, the desk also keeps an encrypted copy of that file in the CHUSBC Gmail account, under the label `PrismTournamentVault` (events, bowlers, scores, lanes, and the rest of the tournament file). After a reboot, an empty database is filled from the latest copy. A database that already has events is not replaced by an older copy.

That copy updates on its own after scores, registrations, and event changes. It waits a short time so a run of score entries becomes one save, and it ignores the "on duty" heartbeat. Download a backup from Backup & Restore after each squad anyway and keep that file somewhere safe. That file is the extra copy you can restore by hand.

Staff sign-in accounts are copied on their own so they survive that reset. The copy is an encrypted snapshot — Argon2 password hashes, names, emails, centers, and roles, never a plaintext password — stored as one message in the same mailbox, under the label `PrismStaffVault`. The staff copy does not include events or scores.

Both copies are optional. With the secrets below missing, the desk still runs and the built-in admin can still sign in. Any other staff account, and the tournament file, disappear on the next reboot. Scoring still works on the disk while the app is up.

## Staff accounts and tournament data after a reboot

In the Streamlit app's secrets, set:

```toml
STAFF_VAULT_KEY = "a long random string you make up, at least 32 characters"
CHUSBC_GMAIL_APP_PASSWORD = "the Gmail app password already used for desk mail"
CHUSBC_GMAIL_USER = "chusbc.tournaments@gmail.com"
```

`CHUSBC_GMAIL_USER` can be omitted when the mailbox is `chusbc.tournaments@gmail.com`. `CHUSBC_GMAIL_APP_PASSWORD` is the same app password the registration emails already use. No second key, no Google Drive folder, and no Turso database are required. The tournament copy uses `STAFF_VAULT_KEY`.

On that Google account, turn IMAP on: Gmail → Settings → See all settings → Forwarding and POP/IMAP → Enable IMAP → Save Changes.

Save the secrets, then reboot the Streamlit app once so it picks them up. The first start with those secrets copies the staff accounts and the tournament still on disk into the mailbox. The app creates the `PrismStaffVault` and `PrismTournamentVault` labels itself. After a later reboot, an empty staff table and an empty tournament file are filled from those copies and the same passwords work. Adding, approving, editing, or deleting an account updates the staff copy. Entering scores, registrations, or event changes updates the tournament copy. If the secrets are wrong or IMAP is off, those changes still save on the disk. Staff Accounts, Backup & Restore, and the sidebar say the mailbox copy did not sync.

Do not put `STAFF_VAULT_KEY` in a local secrets file unless that computer should read and update the live staff list and the live tournament. The key is what decrypts both mailbox copies.

Accounts, events, and scores that were already wiped before the first successful copy cannot be recovered. Staff sign up again once. For a tournament, download a backup after each squad if you also want a file outside the mailbox.
