# Watching from outside the house (optional)

[← Troubleshooting](troubleshooting.md) · [Back to the front page](../README.md)

**Phone alerts already work anywhere.** This page is only for when you also want to **see the Kiln Helper screen** away from home, like Skutt's KilnLink app.

The safe way is **[Tailscale](https://tailscale.com)**, a free private network between your own devices. Nothing is opened to the internet.

> **Don't** "port forward" Kiln Helper on your router. That would let anyone on the internet reach your kiln.

## Set up (about 10 minutes)

1. Make a free account at [tailscale.com](https://tailscale.com).
2. On the Pi:
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up
   ```
   Open the link it prints and sign in.
3. Install the **Tailscale** app on your phone and sign in with the same account.
4. In the Tailscale app, find the Pi (named **kiln**) and open:
   **http://kiln:8081**

Now Kiln Helper works on your phone anywhere your phone has internet.

## Safety notes
- Set a **grown-up PIN** (⚙ Settings → Grown-up lock) so starting a firing always needs it
- Starting a firing when you're away from the kiln is your choice. Kiln Helper's auto-shutoffs and alerts help, but a person nearby is still the best safety device

---
[← Troubleshooting](troubleshooting.md) · [Back to the front page](../README.md)
