from dataclasses import dataclass, field
from typing import Optional
from xml.etree import ElementTree
import json
import os
import time
import logging

from curl_cffi import requests as cffi_requests
from curl_cffi.requests import Response
from curl_cffi.requests.exceptions import (
    ConnectionError as TMConnectionError,
    RequestException,
    Timeout,
    TooManyRedirects,
)
from bs4 import BeautifulSoup
from fastapi import HTTPException
from lxml import etree

from app.utils.utils import trim
from app.utils.xpath import Pagination

logger = logging.getLogger("transfermarkt-api")

# Cookie-Datei von solve_captcha.py
COOKIE_FILE = os.path.join(os.path.dirname(__file__), "..", "..", ".tm-cookies.json")

# curl_cffi-Session mit Browser-TLS-Impersonation. impersonate setzt JA3/TLS-Fingerprint
# + konsistenten Header-Satz. Das eliminiert die wiederkehrenden WAF-Blocks: der
# python-requests-Fingerprint war als Bot erkennbar, weshalb TM trotz gueltiger Cookies
# staendig neu challengte (405/202/403) und Verbindungen droppte ('Connection aborted').
#
# SELF-HEAL durch Identitaets-Rotation (kostenlos, ohne Mensch/CAPTCHA/Cookie-Refresh):
# bei WAF-Block oder Verbindungsabbruch wechselt make_request() auf das naechste Profil
# (frische TLS-Session, anderer Browser-Fingerprint) und versucht erneut. Verifiziert
# 2026-06-04: alle Profile erreichen TM COOKIELOS (Profil/Stats/Liga je HTTP 200) — die
# manuelle Cookie-Loesung ist damit nur noch Last-Resort, kein Pflicht-Pfad mehr.
IMPERSONATE_TARGETS = ["chrome", "chrome131", "safari", "edge"]
_target_idx = 0


def _build_session(target):
    """Frische curl_cffi-Session mit der angegebenen Browser-Impersonation."""
    s = cffi_requests.Session(impersonate=target)
    # Accept-Language ergaenzen (englische Vereins-/Wettbewerbsnamen). TLS-Fingerprint
    # und Header-Reihenfolge bleiben unter Kontrolle von impersonate.
    s.headers.update({"Accept-Language": "en-GB,en;q=0.9,de;q=0.5"})
    return s


_session = _build_session(IMPERSONATE_TARGETS[_target_idx])

_cookies_loaded = False
_parsed_tm_cookies = None  # einmal geparste TM-Cookies; Session-Rotation re-nutzt sie (kein Disk-Read pro Wechsel)
_last_waf_alert = 0


def _load_cookies():
    """Setze gespeicherte TM-Cookies in die aktuelle Session.

    Das Cookie-File wird nur EINMAL gelesen/geparst — Session-Rotationen (_rotate_session)
    nutzen die gecachte Liste, statt bei jedem Profil-Wechsel erneut von der Platte zu lesen.
    """
    global _cookies_loaded, _parsed_tm_cookies

    if _parsed_tm_cookies is None:
        cookie_path = os.path.normpath(COOKIE_FILE)
        if not os.path.exists(cookie_path):
            logger.warning(f"[TM] Keine Cookie-Datei gefunden: {cookie_path}")
            logger.warning("[TM] Bitte 'python3 solve_captcha.py' ausfuehren!")
            return False
        try:
            with open(cookie_path) as f:
                cookies = json.load(f)
            # Nur TM-Cookies behalten. solve_captcha.py sammelt unter Umstaenden auch
            # Ad-Tracker-Cookies (pubmatic, criteo, id5-sync, ...) — wenn die alle als
            # .transfermarkt.com reingeschrieben werden, antwortet TM mit HTTP 400
            # (Cookie-Header-Overflow).
            _parsed_tm_cookies = [c for c in cookies if "transfermarkt" in (c.get("domain") or "").lower()]
            logger.info(
                f"[TM] {len(_parsed_tm_cookies)} TM-Cookies geparst "
                f"({len(cookies) - len(_parsed_tm_cookies)} Nicht-TM-Cookies verworfen)"
            )
        except Exception as e:
            logger.error(f"[TM] Cookie-Laden fehlgeschlagen: {e}")
            return False

    for c in _parsed_tm_cookies:
        domain = (c.get("domain") or "").lower()
        _session.cookies.set(
            c["name"], c["value"],
            domain=domain if domain.startswith(".") else "." + domain.lstrip("www."),
            path=c.get("path", "/"),
        )
    _cookies_loaded = True
    return True


def _check_waf_block(response: Response) -> bool:
    """Pruefe ob Response eine WAF-Challenge ist."""
    if response.status_code == 405 and "Human Verification" in response.text:
        return True
    if response.status_code == 403:
        return True
    # 202 Interstitial — TM liefert Challenge-HTML ohne canonical-Link.
    # Tritt bei Stats-/Leistungsdatendetails-URLs auf, wenn Cookies nur das
    # Profile-Challenge bestanden haben. Ohne diesen Check parst der Scraper
    # das Challenge-HTML und wirft generisches 404 statt sauber zu alerten.
    if response.status_code == 202 and 'rel="canonical"' not in response.text:
        return True
    return False


def _handle_waf_block():
    """Logge WAF-Block und alerte (max 1x pro 5 Min)."""
    global _last_waf_alert
    now = time.time()
    if now - _last_waf_alert > 300:
        _last_waf_alert = now
        logger.error("[TM] ⚠️ WAF-Block — alle Impersonation-Profile erschoepft (echter IP-Bann?).")
        logger.error("[TM] → Letzter Ausweg: 'python3 solve_captcha.py' + Backend neu starten.")


def _rotate_session():
    """Self-Heal: wechselt auf die naechste Impersonation-Identitaet (frische TLS-Session).
    Ein neuer Handshake mit anderem Browser-Profil umgeht Fingerprint-basierte WAF-
    Re-Challenges und Verbindungsabbrueche ohne Mensch, CAPTCHA oder Cookie-Refresh."""
    global _session, _target_idx, _cookies_loaded
    _target_idx = (_target_idx + 1) % len(IMPERSONATE_TARGETS)
    _session = _build_session(IMPERSONATE_TARGETS[_target_idx])
    _cookies_loaded = False
    _load_cookies()  # best-effort, optionaler Boost
    logger.warning(f"[TM] Self-Heal: Session rotiert auf impersonate={IMPERSONATE_TARGETS[_target_idx]}")


# Cookies beim Import laden (best-effort — System funktioniert auch cookielos)
_load_cookies()


@dataclass
class TransfermarktBase:
    """
    Base class for making HTTP requests to Transfermarkt and extracting data from the web pages.

    Args:
        URL (str): The URL for the web page to be fetched.
    Attributes:
        page (ElementTree): The parsed web page content.
        response (dict): A dictionary to store the response data.
    """

    URL: str
    page: ElementTree = field(default_factory=lambda: None, init=False)
    response: dict = field(default_factory=lambda: {}, init=False)

    def make_request(self, url: Optional[str] = None) -> Response:
        """
        Make an HTTP GET request to the specified URL.

        Args:
            url (str, optional): The URL to make the request to. If not provided, the class's URL
                attribute will be used.

        Returns:
            Response: An HTTP Response object containing the server's response to the request.

        Raises:
            HTTPException: If there are too many redirects, or if the server returns a client or
                server error status code.
        """
        url = self.URL if not url else url

        # Cookies nachladen falls noch nicht geschehen (best-effort, optional)
        if not _cookies_loaded:
            _load_cookies()

        # Self-Heal-Loop: bei WAF-Block/Verbindungsabbruch auf naechste Impersonation-
        # Identitaet rotieren und erneut versuchen. Jede Rotation = frische TLS-Session.
        n = len(IMPERSONATE_TARGETS)
        for attempt in range(n):
            is_last = attempt == n - 1
            try:
                response: Response = _session.get(url=url)
            except TooManyRedirects:
                raise HTTPException(status_code=404, detail=f"Not found for url: {url}")
            except Timeout:
                if not is_last:
                    _rotate_session()
                    continue
                raise HTTPException(status_code=504, detail=f"Timeout for url: {url}")
            except (TMConnectionError, RequestException) as e:
                # Verbindungsabbruch/RST = haeufiges Block-Symptom → Identitaet wechseln.
                if not is_last:
                    _rotate_session()
                    continue
                raise HTTPException(status_code=503, detail=f"Connection/request error for url: {url}. {e}")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Error for url: {url}. {e}")

            # WAF-Challenge → rotieren und retry; erst nach Erschoepfung aller Profile alerten.
            if _check_waf_block(response):
                if not is_last:
                    _rotate_session()
                    continue
                _handle_waf_block()
                raise HTTPException(
                    status_code=503,
                    detail="Transfermarkt WAF-Block (alle Impersonation-Profile erschoepft).",
                )

            if 400 <= response.status_code < 500:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Client Error. {response.reason} for url: {url}",
                )
            elif 500 <= response.status_code < 600:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Server Error. {response.reason} for url: {url}",
                )
            return response

    def request_url_bsoup(self) -> BeautifulSoup:
        """
        Fetch the web page content and parse it using BeautifulSoup.

        Returns:
            BeautifulSoup: A BeautifulSoup object representing the parsed web page content.

        Raises:
            HTTPException: If there are too many redirects, or if the server returns a client or
                server error status code.
        """
        response: Response = self.make_request()
        return BeautifulSoup(markup=response.content, features="html.parser")

    @staticmethod
    def convert_bsoup_to_page(bsoup: BeautifulSoup) -> ElementTree:
        """
        Convert a BeautifulSoup object to an ElementTree.

        Args:
            bsoup (BeautifulSoup): The BeautifulSoup object representing the parsed web page content.

        Returns:
            ElementTree: An ElementTree representing the parsed web page content for further processing.
        """
        return etree.HTML(str(bsoup))

    def request_url_page(self) -> ElementTree:
        """
        Fetch the web page content, parse it using BeautifulSoup, and convert it to an ElementTree.

        Returns:
            ElementTree: An ElementTree representing the parsed web page content for further
                processing.

        Raises:
            HTTPException: If there are too many redirects, or if the server returns a client or
                server error status code.
        """
        bsoup: BeautifulSoup = self.request_url_bsoup()
        return self.convert_bsoup_to_page(bsoup=bsoup)

    def raise_exception_if_not_found(self, xpath: str):
        """
        Raise an exception if the specified XPath does not yield any results on the web page.

        Args:
            xpath (str): The XPath expression to query elements on the page.

        Raises:
            HTTPException: If the specified XPath query does not yield any results, indicating an invalid request.
        """
        if not self.get_text_by_xpath(xpath):
            raise HTTPException(status_code=404, detail=f"Invalid request (url: {self.URL})")

    def get_list_by_xpath(self, xpath: str, remove_empty: Optional[bool] = True) -> Optional[list]:
        """
        Extract a list of elements from the web page using the specified XPath expression.

        Args:
            xpath (str): The XPath expression to query elements on the page.
            remove_empty (bool, optional): If True, remove empty or whitespace-only elements from
                the list. Default is True.

        Returns:
            Optional[list]: A list of elements extracted from the web page based on the XPath query.
                If remove_empty is True, empty or whitespace-only elements are filtered out.
        """
        elements: list = self.page.xpath(xpath)
        if remove_empty:
            elements_valid: list = [trim(e) for e in elements if trim(e)]
        else:
            elements_valid: list = [trim(e) for e in elements]
        return elements_valid or []

    def get_text_by_xpath(
        self,
        xpath: str,
        pos: int = 0,
        iloc: Optional[int] = None,
        iloc_from: Optional[int] = None,
        iloc_to: Optional[int] = None,
        join_str: Optional[str] = None,
    ) -> Optional[str]:
        """
        Extract text content from the web page using the specified XPath expression.

        Args:
            xpath (str): The XPath expression to query elements on the page.
            pos (int, optional): Index of the element to extract if multiple elements match the
                XPath. Default is 0.
            iloc (int, optional): Extract a single element by index, used as an alternative to 'pos'.
            iloc_from (int, optional): Extract a range of elements starting from the specified
                index (inclusive).
            iloc_to (int, optional): Extract a range of elements up to the specified
                index (exclusive).
            join_str (str, optional): If provided, join multiple text elements into a single string
                using this separator.

        Returns:
            Optional[str]: The extracted text content from the web page based on the XPath query and
                optional parameters. If no matching element is found, None is returned.
        """
        element = self.page.xpath(xpath)

        if not element:
            return None

        if isinstance(element, list):
            element = [trim(e) for e in element if trim(e)]

        if isinstance(iloc, int):
            element = element[iloc]

        if isinstance(iloc_from, int) and isinstance(iloc_to, int):
            element = element[iloc_from:iloc_to]

        if isinstance(iloc_to, int):
            element = element[:iloc_to]

        if isinstance(iloc_from, int):
            element = element[iloc_from:]

        if isinstance(join_str, str):
            return join_str.join([trim(e) for e in element])

        try:
            return trim(element[pos])
        except IndexError:
            return None

    def get_last_page_number(self, xpath_base: str = "") -> int:
        """
        Retrieve the last page number for a paginated result based on the provided base XPath.

        Args:
            xpath_base (str): The base XPath for extracting page number information.

        Returns:
            int: The last page number for search results. Returns 1 if no page numbers are found.
        """

        for xpath in [Pagination.PAGE_NUMBER_LAST, Pagination.PAGE_NUMBER_ACTIVE]:
            url_page = self.get_text_by_xpath(xpath_base + xpath)
            if url_page:
                return int(url_page.split("=")[-1].split("/")[-1])
        return 1
