# bowling-tournament-app

The desk stores tournament data in an on-disk SQLite file, `tournament.db`.

`TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` are not read. Streamlit Secrets entries for Turso are ignored, and a deploy does not need a Turso database. Those secrets can be removed from the Streamlit app after this is deployed.

On Streamlit Cloud the disk is ephemeral. A sleep or a redeploy can reset the file. During a live tournament, while the app is up and people are using it, the file stays. Download a backup from Backup & Restore after each squad and keep that file somewhere safe. That backup is the copy of events, bowlers, and scores.

Staff sign-in accounts are copied on their own so they survive that reset. The copy is an encrypted snapshot — Argon2 password hashes, names, emails, centers, and roles, never a plaintext password — stored as one message in the CHUSBC Gmail account, under the label `PrismStaffVault`. Tournament data is not in that snapshot. Hosted Turso is not used.

The vault is optional. With the secrets below missing, the desk still runs and the built-in admin can still sign in, but any other staff account disappears on the next reboot.

## Staff accounts after a reboot

In the Streamlit app's secrets, set:

```toml
STAFF_VAULT_KEY = "a long random string you make up, at least 32 characters"
CHUSBC_GMAIL_APP_PASSWORD = "the Gmail app password already used for desk mail"
CHUSBC_GMAIL_USER = "chusbc.tournaments@gmail.com"
```

`CHUSBC_GMAIL_USER` can be omitted when the mailbox is `chusbc.tournaments@gmail.com`. `CHUSBC_GMAIL_APP_PASSWORD` is the same app password the registration emails already use. No Google Drive folder and no Turso database are required.

On that Google account, turn IMAP on: Gmail → Settings → See all settings → Forwarding and POP/IMAP → Enable IMAP → Save Changes.

Save the secrets, then reboot the Streamlit app once so it picks them up. The first start with those secrets copies the staff accounts still on disk into the vault. After a later reboot, an empty staff table is filled from the vault and the same passwords work. Adding, approving, editing, or deleting an account updates the vault. If the secrets are wrong or IMAP is off, account changes still save on the disk and the Staff Accounts page says the vault did not sync.

Do not put `STAFF_VAULT_KEY` in a local secrets file unless that computer should read and update the live staff list. The key is what decrypts the mailbox copy.

Accounts that were already wiped before this vault existed cannot be recovered. Those people sign up again once; that sign-up is what the vault keeps.
