"""Polls an IPAWS-OPEN EAS feed on its own thread and hands new alerts to a callback."""
import logging
import threading
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from cap_alert import NotDeliverable, parse_cap

ATOM = '{http://www.w3.org/2005/Atom}'


class IpawsPoller(threading.Thread):
    def __init__(self, name, url, interval, on_alert, stop_event, timeout=15, skip_existing=True):
        super().__init__(name=name, daemon=True)
        self.url = url
        self.interval = float(interval)
        self.on_alert = on_alert  # called as on_alert(source_name, alert_dict)
        self.stop_event = stop_event
        self.timeout = timeout
        self.skip_existing = skip_existing  # ignore whatever's already active when we start
        self.seen = set()
        self.log = logging.getLogger(name)

    def fetch(self, url):
        req = urllib.request.Request(url, headers={'User-Agent': 'EASyPyCAP'})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return r.read()

    def entry_links(self):
        # the feed is an Atom index, each <entry> links to the actual CAP
        root = ET.fromstring(self.fetch(self.url))
        links = []
        for entry in root.iter(ATOM + 'entry'):
            link = entry.find(ATOM + 'link')
            if link is not None and link.get('href'):
                links.append(link.get('href'))
        return links

    def poll(self):
        for link in self.entry_links():
            if link in self.seen or self.stop_event.is_set():
                continue
            try:
                raw = self.fetch(link)
            except urllib.error.HTTPError as e:
                if e.code in (403, 404, 410):  # IPAWS gives a 403 once an alert expires
                    self.seen.add(link)
                else:
                    self.log.warning(f'Could not download {link}: {e}')
                continue
            except OSError as e:
                self.log.warning(f'Could not download {link}: {e}')  # try again next poll
                continue

            self.seen.add(link)
            try:
                alert = parse_cap(raw)
            except NotDeliverable as e:
                self.log.info(f'Skipping {link}: {e}')
                continue
            except (ValueError, ET.ParseError) as e:
                self.log.warning(f'Invalid CAP at {link}: {e}')
                continue
            self.on_alert(self.name, alert)

    def run(self):
        self.log.info(f'Polling {self.url} every {self.interval:g}s')
        # if the first fetch fails we keep retrying it instead of polling,
        # otherwise a network blip at startup would air every active alert
        primed = not self.skip_existing
        while True:
            try:
                if primed:
                    self.poll()
                else:
                    self.seen.update(self.entry_links())
                    primed = True
                    self.log.info(f'Ignoring {len(self.seen)} alert(s) already active at startup')
            except (OSError, ET.ParseError) as e:
                self.log.warning(f'Poll failed: {e}')
            except Exception:
                self.log.exception('Unexpected error while polling')
            if self.stop_event.wait(self.interval):
                return
