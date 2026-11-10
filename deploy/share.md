# Opening VedQuant from another device (laptop hosting, Tailscale)

The `web` service (docker compose) serves the built site + API on `127.0.0.1:8080`.
Tailscale puts that port on a private HTTPS address that only invited devices can open.

## One-time setup on the laptop (needs sudo and your own login)
    curl -fsSL https://tailscale.com/install.sh | sh
    sudo tailscale up            # opens a login link: choose "Sign in with GitHub"
    sudo tailscale serve --bg 8080
    tailscale serve status       # shows the address: https://<laptop>.<tailnet>.ts.net

The first `serve` may print a link to turn on HTTPS certificates for your tailnet: open it, enable.

## Give someone access
Tailscale admin console (https://login.tailscale.com/admin/machines) -> this laptop -> Share ->
send the invite link. They install the Tailscale app, sign in with their own account, accept,
then open the address above. Remove the share there to take access away.

## Notes
- Private: without the invite the address does not open. Do NOT use `tailscale funnel` (public)
  while sign-ups are open.
- After frontend changes: `(cd frontend && npm run build)`; the `web` service picks it up.
- "Login with Dhan" works only on http://local.vedquant.com (Dhan's fixed Redirect URL).
- The laptop must be on and awake during market hours (09:00-15:35 IST).
