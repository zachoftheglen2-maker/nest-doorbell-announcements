# Nest Authentication Recovery (experimental 0.1.0)

This app is separate from the announcement integration and does not use or operate locks. It monitors the Homebridge app logs for the named NestAccfactory Google account. It uses an isolated persistent Chromium profile accessible through Home Assistant ingress (admin only, no exposed port). Google passwords are not stored or automatically submitted. Google may block the browser or require interactive verification.

## First setup

1. Install and start with automatic_recovery **off**. Keep Homebridge and delivery automation unchanged.
2. Open the Web UI and select Connect browser display, then Open Nest website. Sign in to your own Google account and complete any verification yourself.
3. Click Test browser session. It attempts a fresh Nest browser authentication exchange; it does not modify Homebridge. A passed result only means a valid Google token response was observed.
4. Confirm monitor status shows authorised. If log unavailable, verify the Homebridge app slug and Supervisor access. The default slug is based on the existing Homebridge app; change if needed.
5. Before enabling automatic recovery, make a Homebridge backup via its UI. Set Homebridge URL and UI administrator credentials in the app Configuration. These are Homebridge credentials, not Google credentials. Use only a local trusted server; HTTPS preferred if available. Google and Homebridge credentials never belong in GitHub or logs.
6. Enable automatic_recovery and restart this app only. On a new authentication failure, it attempts a fresh exchange in the browser, checks the named Google account and dedicated child bridge via the Homebridge UI API, updates that plugin's account, and requests only its child bridge restart. If the browser session is no longer valid, it sends a persistent notification rather than trying to bypass Google verification.

One attempt per distinct failure log, at least 30 minutes apart. Browser login is persistent across app restarts. A browser response does not guarantee Homebridge will accept it. The app does not test audible announcements. Stop/uninstall this app to stop monitoring and changes. It does not roll back credentials already saved through Homebridge UI.

## Permissions and limitations

Supervisor manager permission is required to read another app's logs. Home Assistant API access is used for persistent notifications. Browser runs as a separate user with no inherited Supervisor token, but Chromium's sandbox is disabled in this experimental container. Use only the intended Nest sign-in page, not general browsing. The UI is restricted to Supervisor ingress.

No guarantee of automatic recovery after Google revokes the browser session or retires the Nest website. The Homebridge UI endpoint shapes and Google browser request are based on current documentation/source; actual container build and end-to-end operation have not yet been tested on a running Home Assistant instance. Leave automatic recovery off until the browser and monitor work. Never deliberately invalidate the working Homebridge session just to test this app.
