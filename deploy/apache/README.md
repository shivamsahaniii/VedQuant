# Local URL with Apache: http://local.vedquant.com

Apache forwards requests to the two Vedquant servers; it does not run Vedquant itself (no PHP).

| Path | Goes to |
| --- | --- |
| `http://local.vedquant.com/` | Vue dashboard (Vite dev server, `127.0.0.1:5173`) |
| `http://local.vedquant.com/api/...` | FastAPI (Docker, `127.0.0.1:8000`) |

This only adds a new site. Existing sites (Sangam etc.) are not changed.

## Install (once)

Run from the project root (`~/Downloads/Vedquant`):

```bash
sudo cp deploy/apache/local.vedquant.com.conf /etc/apache2/sites-available/
echo "127.0.0.1       local.vedquant.com" | sudo tee -a /etc/hosts
sudo a2enmod proxy proxy_http
sudo a2ensite local.vedquant.com.conf
sudo apache2ctl configtest                 # must print "Syntax OK"
sudo systemctl reload apache2
```

## Run Vedquant

```bash
docker compose up -d                        # API, database, Redis
cd frontend && npm run dev                  # dashboard
```

Then open http://local.vedquant.com

## Remove

```bash
sudo a2dissite local.vedquant.com.conf
sudo rm /etc/apache2/sites-available/local.vedquant.com.conf
sudo sed -i '/local\.vedquant\.com/d' /etc/hosts
sudo systemctl reload apache2
```

## Production

Later (Phase 4) the production server uses HTTPS and serves the built frontend (`npm run build` → `frontend/dist`) as static files instead of the Vite dev server. See `md/SETUP.md`.
