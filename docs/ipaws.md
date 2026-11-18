# `modules/ipaws.py`

This module polls one IPAWS-OPEN EAS feed. Each feed runs as its own thread.

```python
IpawsPoller(name, url, interval, on_alert, stop_event, timeout=15, skip_existing=True)
```

| Argument | Meaning |
|---|---|
| `name` | Name of the source. It is also the thread name and the logger name. |
| `url` | Feed URL. The real feed is `https://apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/feed`. |
| `interval` | Seconds between polls. This is `poll_dur` in `sources.json`. |
| `on_alert` | `on_alert(name, alert_dict)` is called for each new alert. The dict comes from `cap_alert.parse_cap`. |
| `stop_event` | A `threading.Event`. Set it to stop the thread. |
| `timeout` | HTTP timeout in seconds. |
| `skip_existing` | If true, alerts already in the feed when the thread starts are ignored, so a restart doesn't air them again. |

## The feed

The feed URL returns an Atom index with one `<entry>` per active alert. Each entry links to the full CAP XML:

```xml
<entry>
  <title>SPW</title>
  <link href="https://apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/eas/300134373042"/>
  <category term="06"  label="statefips"/>
  <category term="SPW" label="event"/>
</entry>
```

## What each poll does

1. Fetches the index and collects the `<link href>` of every entry.
2. Skips any link it has already seen.
3. Downloads the CAP from each new link.
   - If the server answers HTTP 403, 404 or 410, the alert has expired; IPAWS returns 403 for this. The link is marked as seen and nothing is logged.
   - Any other download error is logged and the link is tried again on the next poll.
4. Parses the CAP with `parse_cap`.
   - A `Cancel` (or any other `NotDeliverable`) is logged at INFO and skipped.
   - Malformed CAP is logged as a warning and skipped.
5. Calls `on_alert`.

`on_alert` runs on the poller's own thread. If it takes a long time, for example while sending to an encoder, the next poll waits for it to finish.

## Notes

- **The seen list lives in memory only.** After a restart, `skip_existing` is what keeps active alerts from airing again. If the first fetch at startup fails, the thread keeps retrying that step instead of polling, so a network blip at launch can't cause every active alert to air.
- **IPAWS signatures (XML-DSig) are not checked.** The HTTPS connection to FEMA is what you are trusting.
