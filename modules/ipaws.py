"""Poll an IPAWS-OPEN EAS feed for new alerts."""
import logging
import threading
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from cap_alert import NotDeliverable, parse_cap

ATOM = '{http://www.w3.org/2005/Atom}'
EXPIRED_HTTP_CODES = (403, 404, 410)


class IpawsPoller(threading.Thread):
    def __init__(self, name, url, interval, on_alert, stop_event, timeout=15, skip_existing=True):
        super().__init__(name=name, daemon=True)
        self.url = url
        self.interval = float(interval)
        self.on_alert = on_alert
        self.stop_event = stop_event
        self.timeout = timeout
        self.skip_existing = skip_existing
        self.seen = set()
        self.log = logging.getLogger(name)

    def fetch(self, url):
        request = urllib.request.Request(url, headers={'User-Agent': 'EASyPyCAP'})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read()

    def entry_links(self):
        root = ET.fromstring(self.fetch(self.url))
        links = []
        for entry in root.iter(ATOM + 'entry'):
            link = entry.find(ATOM + 'link')
            if link is None:
                continue
            href = link.get('href')
            if href:
                links.append(href)
        return links

    def poll(self):
        for link in self.entry_links():
            if link in self.seen or self.stop_event.is_set():
                continue
            try:
                raw = self.fetch(link)
            except urllib.error.HTTPError as error:
                # IPAWS can return 403 after an alert expires.
                if error.code in EXPIRED_HTTP_CODES:
                    self.seen.add(link)
                else:
                    self.log.warning(f'Could not download {link}: {error}')
                continue
            except OSError as error:
                self.log.warning(f'Could not download {link}: {error}')
                continue

            self.seen.add(link)
            try:
                alert = parse_cap(raw)
            except NotDeliverable as error:
                self.log.info(f'Skipping {link}: {error}')
                continue
            except (ValueError, ET.ParseError) as error:
                self.log.warning(f'Invalid CAP at {link}: {error}')
                continue
            self.on_alert(self.name, alert)

    def run(self):
        self.log.info(f'Polling {self.url} every {self.interval:g}s')
        skip_startup_alerts = self.skip_existing
        while True:
            try:
                if skip_startup_alerts:
                    # Retry this step if the startup fetch fails.
                    self.seen.update(self.entry_links())
                    skip_startup_alerts = False
                    self.log.info(f'Ignoring {len(self.seen)} alert(s) already active at startup')
                else:
                    self.poll()
            except (OSError, ET.ParseError) as error:
                self.log.warning(f'Poll failed: {error}')
            except Exception:
                self.log.exception('Unexpected error while polling')
            if self.stop_event.wait(self.interval):
                return
