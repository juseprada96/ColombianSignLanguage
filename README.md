# ColombianSignLanguage
Repo to study colombian sign language.

## GIF storage (Cloudflare R2)

GitHub Pages has a 1 GB site limit and its deploy step can time out on the full
GIF set. The app supports serving the GIFs from a public Cloudflare R2 bucket
instead (10 GB free storage, no egress fees).

### One-time setup

1. Create an R2 bucket, for example `csl-gifs`.
2. Enable public access for the bucket (`r2.dev` subdomain, or a custom domain).
3. Create an R2 API token with **Object Read & Write** access to that bucket.
4. Install the client:

   ```powershell
   python -m pip install boto3
   ```

5. Set the credentials. Either export them in your shell or copy
   `.env.example` to `.env` and fill it in (`.env` is gitignored):

   ```powershell
   Copy-Item .env.example .env
   # edit .env before continuing
   ```

   ```powershell
   $env:R2_ACCOUNT_ID="..."
   $env:R2_ACCESS_KEY_ID="..."
   $env:R2_SECRET_ACCESS_KEY="..."
   $env:R2_BUCKET="csl-gifs"
   $env:R2_PUBLIC_BASE_URL="https://pub-xxxxxxxx.r2.dev"
   ```

6. Upload the GIFs, keeping the `words/<SECTION>/<WORD>.gif` keys:

   ```powershell
   python scripts/upload_gifs.py --skip-existing
   ```

7. Put the public bucket URL (with a trailing slash) in `config.js`:

   ```js
   window.CSL_ASSET_BASE_URL = "https://pub-xxxxxxxx.r2.dev/";
   ```

   Leave it empty to use the local `words/` folder during development.

### Updating GIFs

After running the add-sign-video skill, upload the new files:

```powershell
python scripts/upload_gifs.py --skip-existing
```

GIFs are served with a 7-day cache. Re-uploading the same key updates the
object; use `--force` (omit `--skip-existing`) to overwrite a same-size file.
