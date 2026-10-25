# bowling-tournament-app

The desk stores tournament data in an on-disk SQLite file, `tournament.db`.

`TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` are not read. Streamlit Secrets entries for Turso are ignored, and a deploy does not need a Turso database. Those secrets can be removed from the Streamlit app after this is deployed.

On Streamlit Cloud the disk is ephemeral. A sleep or a redeploy can reset the file. During a live tournament, while the app is up and people are using it, the file stays. Download a backup from Backup & Restore after each squad and keep that file somewhere safe.
