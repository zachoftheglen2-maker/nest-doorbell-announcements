# Nest Doorbell Announcements 0.1.0

A community Home Assistant custom integration for a local announcement provider. **This development build still requires the existing Homebridge audio relay.** It does not implement Google OAuth or direct Nest audio streaming. Do not remove your working Homebridge installation.

## Install

In Home Assistant 2026.11 or newer, open Settings > Marketplace > Add from link and enter https://github.com/zachoftheglen2-maker/nest-doorbell-announcements. Select Integration if prompted and install. On older versions with HACS already installed, use Custom repositories, select Integration and download. Follow any restart prompt.

Then open Settings > Devices & services > Add integration > Nest Doorbell Announcements. Enter the same endpoint as your existing rest_command, default http://127.0.0.1:8765/announcement, and timeout 50 seconds.

## Test

In Developer Tools > Actions, use:

```yaml
action: nest_announcements.play
data: {}
```

The action never operates a lock. Confirm audible playback yourself. To read the last recorded result without playing audio:

```yaml
action: nest_announcements.status
data: {}
```

Status is not a live authentication check. Playback validates HTTP 200, positive bytes sent and FFmpeg exit code 0, and rejects overlapping calls. No automatic retries are made because timeouts may occur after audio has played. No Google credentials are required here. Configure only a provider you control; don't expose it publicly.

## Development status

The transport was tested locally; Home Assistant registration and device playback have not been tested on a live instance. Google's SDM camera API is receive-only; newer Google Home talkback APIs are restricted. An independent provider remains to be developed. Keep your existing automation unchanged while testing.

Remove the integration from Devices & services and uninstall it from Marketplace if needed. No changes are made to Yale or Homebridge.

## References

- https://developers.google.com/nest/device-access/api/doorbell
- https://developers.google.com/nest/device-access/traits/device/camera-live-stream
- https://developers.home.google.com/apis/android/device/doorbell
