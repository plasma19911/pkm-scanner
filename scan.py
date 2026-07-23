#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pokemon TCG Angebots- & Vorbestellungs-Scanner
================================================
Durchsucht eine Liste deutscher Pokemon-TCG-Shops (die auf Shopify laufen und
daher eine oeffentliche products.json-Schnittstelle anbieten) nach Pokemon-
Artikeln und erzeugt eine fertige HTML-Datei mit zwei Bereichen:

  1) ANGEBOTE        -> aktuell reduzierte Artikel (compare_at_price > price)
  2) VORBESTELLUNGEN  -> Artikel, die als Preorder/Vorbestellung markiert sind

In beiden Faellen werden NUR Artikel angezeigt, die noch verfuegbar
(bestellbar) sind - inklusive Bild, Titel, Shop und Preis.

Ausfuehren:
    python3 scan.py

Ergebnis:
    angebote.html  (im selben Ordner) -> im Browser oeffnen

Hinweise:
- Nur Shops mit oeffentlicher Shopify products.json API werden automatisch
  gescannt. Weitere Shops kannst du einfach unten in SHOPS ergaenzen.
- Shops ohne offene API werden am Ende der HTML-Seite als Link aufgelistet,
  damit du sie von Hand pruefen kannst.
- Bitte fair bleiben: das Skript macht wenige Requests mit Pausen und ist
  nur fuer gelegentlichen, privaten Gebrauch gedacht.
"""

import json
import re
import time
import datetime
import argparse
import os
import io
import html
import threading
import urllib.request
import urllib.error
import urllib.parse
import hashlib
import socket
import concurrent.futures

try:
    from PIL import Image, ImageDraw
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

# Playwright ist eine OPTIONALE Erweiterung fuer Shops, die hinter einem
# JS-basierten Bot-Check (z.B. Cloudflare "Just a moment...") stecken und
# daher mit einfachen HTTP-Anfragen (urllib) nicht erreichbar sind, mit
# einem echten Browser aber schon. Ohne Playwright installiert laeuft das
# Skript ganz normal weiter - diese einzelnen Shops bleiben dann einfach
# als manueller Link stehen (kein Zwang zur Installation fuer alle).
try:
    from playwright.sync_api import sync_playwright
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

# Shops mit bestaetigter oeffentlicher Shopify products.json API
SHOPS = [
    {"name": "God of Cards",     "domain": "godofcards.com"},
    {"name": "CardsRFun",        "domain": "cardsrfun.de"},
    {"name": "Yonko TCG",        "domain": "yonko-tcg.de"},
    {"name": "CrispyCards",      "domain": "crispycards.de"},
    {"name": "cardcosmos",       "domain": "cardcosmos.de"},
    {"name": "TCGViert",         "domain": "tcgviert.com"},
    {"name": "CardBuddys",       "domain": "cardbuddys.de"},
    {"name": "Tradingtoys",      "domain": "tradingtoys.de"},
    {"name": "Pokeflip",         "domain": "pokeflip.com"},
    {"name": "Battle Bear",      "domain": "battle-bear.de"},
    {"name": "Kartenbasis",      "domain": "kartenbasis.de"},
    {"name": "Card Club",        "domain": "cardclub.de"},
    {"name": "AdventureCardz",   "domain": "adventurecardz.de"},
    {"name": "2Sleeve",          "domain": "2sleeve.de"},
    {"name": "Nerdbank",         "domain": "nerdbank.de"},
    {"name": "Pruckis",          "domain": "pruckis.de"},
    {"name": "LottiCards",       "domain": "www.lotticards.de"},
    {"name": "MoCards",          "domain": "mocards.de"},
    {"name": "Webbas Kartenecke","domain": "webbas-kartenecke.de"},
    {"name": "GeeksHeaven",      "domain": "geeksheaven.de"},
    {"name": "Crocus Cards",     "domain": "crocus-cards.de"},
    {"name": "Kartenschatz",     "domain": "kartenschatz.de"},
    {"name": "Cards-Uniques",    "domain": "cards-uniques.de"},
    {"name": "Tenkaichi",        "domain": "tenkaichi.de"},
    {"name": "OpasLaden",        "domain": "opasladen.de"},
    {"name": "Cardgames24",      "domain": "cardgames24.de"},
    {"name": "VanessasTCG-Shop", "domain": "vanessastcg-shop.de"},
    {"name": "Play-Maniac",      "domain": "play-maniac.de"},
    {"name": "Pokeminati",       "domain": "pokeminati.de"},
    {"name": "RotDerSammler",    "domain": "rotdersammler.de"},
    {"name": "Fictionary-World", "domain": "fictionary-world.de"},
    {"name": "Redrum-Verlag",    "domain": "redrum-verlag.de"},
    {"name": "Poke-Hype2K",      "domain": "poke-hype2k.de"},
    {"name": "Kofuku",           "domain": "kofuku.de"},
    {"name": "Poke-Centre",      "domain": "poke-centre.de"},
    {"name": "Kartenladen24",    "domain": "kartenladen24.de"},
    {"name": "Toy-Treasure",     "domain": "toy-treasure.com"},
    {"name": "FantasiaCards",    "domain": "fantasiacards.de"},
    {"name": "Battle of Cards",  "domain": "www.battleofcards.de"},
    {"name": "Booster TCG",      "domain": "boostertcg.de"},
    {"name": "PokePrinz",        "domain": "pokeprinz.de"},
    {"name": "Pokemon-TCG-Shop", "domain": "www.pokemon-tcg-shop.de"},
    {"name": "NerdManiaShop",    "domain": "nerdmaniashop.de"},
    {"name": "WolffCards",       "domain": "wolffcards.com"},
]

# Shops auf WooCommerce-Basis mit offener Store-API (kein Shopify) - werden
# per scan_shop_woocommerce() statt scan_shop() gescannt (anderes JSON-
# Format, siehe dort).
WOOCOMMERCE_SHOPS = [
    {"name": "Sapphire-Cards",    "domain": "sapphire-cards.de"},
    {"name": "Bulk Paradise TCG", "domain": "bulkparadise-tcg.de"},
    {"name": "TCG-24",            "domain": "tcg-24.de"},
    {"name": "TCG-Love",          "domain": "tcg-love.de"},
    {"name": "Play-And-Collect",  "domain": "play-and-collect.de"},
    {"name": "House of Cards and Games", "domain": "house-of-cards-and-games.de"},
    {"name": "Pokemonladen",      "domain": "pokemonladen.de"},
]

# Shops mit offener WooCommerce-API, aber hinter einem JS-Bot-Check (z.B.
# Cloudflare) - normale HTTP-Anfragen (urllib) werden dort abgewiesen,
# ein echter Browser (Playwright) kommt aber durch. Wird NUR gescannt,
# wenn Playwright installiert ist (siehe _PLAYWRIGHT_AVAILABLE oben).
WOOCOMMERCE_JS_PROTECTED_SHOPS = [
    {"name": "KeepSeven", "domain": "keepseven.de"},
]

# Shops mit einem individuellen HTML-Scraper (kein Shopify/WooCommerce,
# jeweils eigener Code noetig - siehe scan_shop_tcgtrade etc.). Wird NUR
# gescannt, wenn Playwright installiert ist.
CUSTOM_SCRAPER_SHOPS = [
    {"name": "TCG-Trade", "domain": "tcg-trade.de", "scraper": "tcgtrade"},
    {"name": "Poke-Corner", "domain": "www.card-corner.de", "scraper": "gambio",
     "categories": ["Pokemon-Display", "Pokemon-Box", "Pokemon-Booster"]},
    {"name": "Comic Planet", "domain": "www.comicplanet.de", "scraper": "comicplanet"},
    {"name": "Gate to the Games", "domain": "www.gate-to-the-games.de", "scraper": "gambio",
     "categories": [
         "Pokemon-Karten/Pokemon-Displays/",
         "Pokemon-Karten/Pokemon-Tin-Boxen/",
         "Pokemon-Karten/Sonderboxen/",
         "Pokemon-japanische-Booster-Display-Boxen-guenstig-online-kaufen/",
     ]},
    {"name": "PokeGeoDude", "domain": "pokegeodude.shop", "scraper": "gambio",
     "categories": [
         "sammelkarten/pokemon/boosterdisplay",
         "sammelkarten/pokemon/etb",
         "sammelkarten/pokemon/blister",
         "sammelkarten/pokemon/collection",
         "sammelkarten/pokemon/pin-tin",
         "sammelkarten/pokemon/high-end",
     ]},
    {"name": "Games-Island", "domain": "games-island.eu", "scraper": "jtl",
     "categories": [
         "c/Pokemon/Booster-Displays",
         "c/Pokemon/Boxen-Sets",
         "c/Pokemon/Elite-Trainer-Box",
         "c/Pokemon/Multi-Pack-Blister",
         "c/Pokemon/Sammelkoffer",
         "c/Pokemon/Sammelerset",
         "c/Pokemon/Tins",
         "c/Pokemon/Raritaeten",
     ]},
]

# Shops ohne offene API (kein automatisches Scannen moeglich) -> nur als Link
# Shops ohne offene API (kein automatisches Scannen moeglich) -> nur als Link.
# HINWEIS: Alle frueher hier gelisteten Shops wurden entweder erfolgreich
# automatisiert (siehe SHOPS/WOOCOMMERCE_SHOPS/CUSTOM_SCRAPER_SHOPS oben)
# oder als nicht erreichbar/nicht relevant identifiziert (z.B. reine
# Wix-Shops ohne stabile Selektoren, aktiv gesperrte APIs, oder Shops ohne
# echte Pokemon-Sammelkarten-Produkte wie JK Entertainment (reines MTG)
# oder Tabletop-Dragon (nur 2 nicht lieferbare Nicht-TCG-Artikel)).
MANUAL_SHOPS = []

# Einzelne Produkt-URLs, die bewusst IMMER ausgeschlossen werden - z.B. weil
# der Shop einen Bestandsfehler hat (Produkt wird als verfuegbar angezeigt,
# aber der Warenkorb lehnt es als "0 auf Lager" ab). Betrifft NUR die
# konkrete URL, nicht das gleiche Produkt bei anderen Shops.
EXCLUDED_PRODUCT_URLS = {
    # TCG-Love zeigt dieses Produkt als verfuegbar, der Warenkorb lehnt es
    # aber ab ("nicht vorraetig, 0 auf Lager") - echter Shop-Bug.
    "https://tcg-love.de/pokemon-prismatic-evolutions-super-premium-collection/",
    # Titel nennt ueberhaupt kein Produkttyp-Wort ("Schwert und Schild
    # Fusionsangriff (DE)") - ist tatsaechlich nur ein EINZELNER Booster,
    # kein Display (kann textuell nicht automatisch unterschieden
    # werden, da kein Hinweis im Titel steht).
    "https://house-of-cards-and-games.de/produkt/pokemon-schwert-und-schild-fusions-angriff-deutsch/",
}

MAX_PAGES_PER_SHOP = 12     # je 250 Artikel -> bis zu 3000 Artikel pro Shop (vorher 4=1000, zu wenig fuer grosse Shops)
REQUEST_DELAY_SEC = 1.5     # kleine Pause zwischen Requests (fair bleiben)
TIMEOUT_SEC = 12
USER_AGENT = "Mozilla/5.0 (compatible; PokemonAngebotsScanner/1.0; privater Gebrauch)"

POKEMON_PATTERN = re.compile(r"pok[eé]mon", re.IGNORECASE)

# Der tatsaechlich genutzte Server-Port (wird von serve() beim Start
# ueberschrieben, falls --port abweichend vom Standard gesetzt wurde).
# Das ist wichtig, damit die in angebote.html eingebettete SERVER_BASE-Adresse
# immer zum tatsaechlich laufenden Server passt.
CURRENT_SERVER_PORT = 8765
PREORDER_PATTERN = re.compile(
    r"vorbestell|vorverkauf|preorder|pre-order|pre order", re.IGNORECASE
)

# Erkennt Einzelkarten und gegradete Karten (Slabs), die ausgeschlossen
# werden sollen - nur versiegelte (sealed) Produkte wie Booster, Displays,
# ETBs, Tins, Collections etc. sollen uebrig bleiben.
GRADED_PATTERN = re.compile(
    r"\bpsa\s?-?\d|\bbgs\s?-?\d|\bcgc\s?-?\d|\bace\s?-?\d|\bslab\b|\bslap\b|"
    r"\bgraded\b|\bap\s*grading\b|\baog\s?-?\d|\bgma\s?-?\d|\btag\s?-?\d|"
    r"\bsgc\s?-?\d|\bnear\s*mint\b.*\d\.\d|\bgrading\s*\d",
    re.IGNORECASE,
)

# Ungegradete Einzelkarten sollen komplett raus (nicht als eigene Kategorie).
# Erkennungsmerkmale: das Wort "Einzelkarte" selbst, klassisches
# Kartennummer-Format wie "4/102", oder das bei vielen Shops (z.B. TCGplayer-
# Feeds) uebliche Format "<Kartenname> - <Setname> (<Raritaet>) [<Setcode>-<Nr>]"
# z.B. "Gyarados - Clash of the Blue Sky (Holo Rare) [PCG2-024]".
SINGLE_CARD_EXCLUDE_PATTERN = re.compile(
    r"einzelkarte|single\s*card|"
    r"\b[a-z]{0,3}\d{1,3}\s?/\s?[a-z]{0,4}-?[a-z0-9]{0,4}\b|"  # Kartennummer-Format wie 4/102, GG59/GG70, 001/SV-P
    r"\[[a-z0-9]{2,8}-[a-z0-9]{2,6}\]|"  # Set-Code-Format wie [s8b-074], [PCG2-024]
    r"\b(swsh|sm|xy|bw|dp|hgss|pop|np|sv|mep)\d{2,4}\b|"  # Promo-Codes ohne Schraegstrich wie SWSH230, SM211, MEP DE010
    r"\bmep\s*[a-z]{0,3}\d{2,4}\b|"  # "MEP DE010" (mit Leerzeichen)
    r"\b\d{2,4}\s?-\s?\d{2,4}\b(?=.{0,25}promo)|"  # Zahlen-Range wie "287-290" nahe "Promo"
    r"\((holo\s*rare|rare|common|uncommon|secret\s*rare|ultra\s*rare|"
    r"double\s*rare|amazing\s*rare|hyper\s*rare|promo|fixed)\b|"  # auch bei zusaetzlichem Text danach, z.B. "(Ultra Rare Full Art Holo)"
    r"\bnear\s*mint\b|"
    # lose Karten-Bundles ohne festes Sealed-Produkt ("100 Pokemon Karten",
    # "50 Pokemon Trainer Karten")
    r"\b\d{1,3}\s*pok[ée]?mon\s*(trainer\s*)?karten\b",
    re.IGNORECASE,
)

# Turnier-Tickets, Event-Anmeldungen etc. - keine physischen Produkte.
TICKET_EXCLUDE_PATTERN = re.compile(
    r"\bticket\b|prerelease|pre-release|\bturnier\b|challenge\s+\w+\s+\d{4}",
    re.IGNORECASE,
)

# Kartenhüllen/Sleeves: generische/billige Sleeves sind meist nicht
# interessant - nur Ultra Pro und Penny Sleeves sollen erhalten bleiben.
SLEEVE_PATTERN = re.compile(
    r"\bsleeve[s]?\b|kartenh[üu]lle[n]?|schutzh[üu]lle[n]?|deck\s*sleeve|"
    r"\bh[üu]lle[n]?\b",
    re.IGNORECASE,
)
SLEEVE_KEEP_EXCEPTION_PATTERN = re.compile(
    r"ultra\s*pro|\bpenny\b", re.IGNORECASE,
)

# Zubehoer-Artikel (Sleeves, Binder, Deckboxen, Toploader...) werden NICHT
# ausgeschlossen, sondern in einer eigenen Kategorie "Zubehör" gesammelt -
# unabhaengig von Sprache. Generische (nicht Ultra Pro/Penny) Sleeves durften
# vorher raus, jetzt laufen ALLE Sleeves unter Zubehör mit.
# Weitere Kategorien, die auf der Angebotsseite nicht relevant sind und
# ausgeschlossen werden (Merch/Zubehoer/andere TCGs statt Pokemon-Sealed).
CATEGORY_EXCLUDE_PATTERN = re.compile(
    r"\btasse[n]?\b|\bmug\b|\bcoin\b|\bmünze\b|\bmuenze\b|mega\s*construx|\blego\b|"
    r"acryl(ic)?\s*case|acrylcase|"
    r"ratespiel|\bmagnet\b|"
    r"spielmatte|play\s*mat|\bmatte\b|magazin|lorcana|bauset|"
    r"one\s*piece|yu-?gi-?oh|"
    r"pl[üu]sch|\bplush\b|blind\s*box|blindbox|gerahmt|rahmen|framed|poster|"
    r"\bfunko\b|pop!?\s*games\b|wasserflasche|trinkflasche|water\s*bottle|\btumbler\b|\bbecher\b|"
    r"\bteller\b|\bplates?\b|prerelease.?turnier|\bturnier\b|"
    r"\bbutton\b|individualisiert|\brepack\b|"
    # Franzoesische Produkte nicht anzeigen
    r"\(fr\)|\bfran[çc]ais\b|\bfrench\b|"
    # generische "Gemischtwaren"-Mystery-Boxen und Zufalls-Kartensets ohne
    # festen Set-Bezug
    r"mystery\s*box|zuf[äa]llig\s*(gemischt|zusammengestellt)|"
    r"\bglitzer\b|\d+er\s*los\b|\blos\s*garantie\b|"
    r"holo\s*karten\s*set|verschiedene\s*pok[ée]?man?\s*karten|"
    r"\bxxl\s*karte\b|gro[ßs]e\s*pok[ée]mon\s*karte|"
    # digitale TCG-Live-Codes sind keine physischen Produkte
    r"tcg\s*live|sammelkartenspiel.?live|\blive\s*code\b|"
    # Trainer Toolkit: braucht laut Rueckmeldung niemand mehr
    r"trainer.?s?[\s-]*toolkit|"
    # Decks aller Art, Build&Battle, Kampfakademie, Fun-/Promo-Packs,
    # Adventskalender - auf Wunsch komplett raus (keine eigene Kategorie
    # mehr, werden gar nicht mehr angezeigt).
    r"theme\s*deck|themendeck|battle\s*deck|structure\s*deck|kampfdeck|starter\s*deck|"
    r"decks?\s*bundle|"
    r"weltmeisterschaftsdeck|world\s*championship\s*deck|\bdeck\b(?!\s*box)|"
    r"build\s*(and|[&\+])?\s*battle|kampf\s*akademie|battle\s*academy|"
    r"fun\s*pack|funpack|promo\s*pack|"
    r"adventskalender|advent\s*calendar|kalender\b|\bcalendar\b|"
    # Zubehoer/Aufbewahrung: komplett raus (keine eigene Kategorie mehr) -
    # AUSSER "Mini Portfolio" (das enthaelt meist einen echten Booster,
    # wird vorher als eigene Kategorie abgefangen).
    r"\btoploader\b|\bsleeve[s]?\b|kartenh[üu]lle[n]?|schutzh[üu]lle[n]?|"
    r"deck\s*sleeve|(?<!mini\s)(?<!mini)\bh[üu]lle[n]?\b|\bpenny\b|ultra\s*pro|"
    r"\bbinder\b|9.?pocket|neun.?pocket|deck\s*box|deckbox|\bordner\b|"
    r"(?<!mini\s)\bportfolio\b|(?<!mini\s)\balbum\b|"
    # sonstiges Merchandise ohne TCG-Bezug
    r"nanoblock|nintendo|ravensburger|labyrinth\b|4d\s*build|spin\s*master|"
    r"\brucksack\b|\bt-?shirt\b|pi[nñ]ata|baseball\s*cap|"
    r"battle\s*figure|\bpanini\b|advanced\s*staks|"
    r"clip.{0,4}n.{0,4}go|schl[üu]sselanh[äa]nger|"
    r"damage\s*counter\s*case|w[üu]rfelbox|schadens\s*z[äa]hler\s*etui|"
    r"m[üu]nzw[üu]rfel|skateboard|random\s*energy\s*break|"
    r"re-?ment\b|takara\s*tomy|monster\s*collection\b|"
    r"old\s*maid\s*card\s*set|baba\s*nuki|"
    r"ohne\s*folie|ohne\s*(original-?)?verpackung|"
    r"\bb\s*&\s*b\s*box\b|build\s*(&|and)?\s*battle\s*(kit|box|stadium)|"
    r"zuf[äa]llige?\s*leere?\s*(mini-?)?tin|"
    r"k(a|ae)rtenetui|k(a|ae)rtenhalter|"
    r"(w[üu]rfel.?kissen|kissen.?w[üu]rfel|kissen.*w[üu]rfel|w[üu]rfel.*kissen)|"
    r"cookie\s*jar|\bumbrella\b|\bgiftset\b|\bcushion\b|canteen|"
    r"\bnotebook\b|mousepad|\blarge\s*glass\b|\bgl[äa]ser\b|\bgl[äa]sern?\b|"
    r"mc\s*donald.?s|\bmcdonalds\b|"
    r"\bmonopoly\b|\bbowl\b|tote\s*bag|ice\s*cube\s*tray|"
    r"trophy\s*card|"
    r"mega\s*pok[ée]mon\b(?!.*(kollektion|display|box|tin))|"
    r"\bpins?\b(?!.{0,25}(collection|kollektion))|"  # einzelne Sammel-Pins (nicht "Pin Collection"/"Pin-Kollektion")
    r"battle\s*trainer\b|starter\s*set\b|"
    r"acryl(ic)?\s*box(en)?|card\s*display\s*frame\s*stand|"
    r"[üu]berraschungsbox|battle\s*stadium|\bstadium\s*box\b|"
    r"\baog\b|\bpgs\b|\bap\s*grading\b",
    re.IGNORECASE,
)

# Puzzle/Figuren sind nur relevant, wenn tatsaechlich Booster/Karten
# enthalten sind (sonst reines Merchandise ohne TCG-Bezug).
PUZZLE_FIGURE_PATTERN = re.compile(r"\bpuzzle\b|\bfigur\b|\bfigure\b", re.IGNORECASE)
PUZZLE_FIGURE_KEEP_PATTERN = re.compile(
    r"\bbooster\b|\bkarten\b|\bcards?\b|\bpack\b|\bpacks\b", re.IGNORECASE
)

# Titel-Muster, die bei der Alarm-Suche NICHT als Treffer zaehlen sollen,
# selbst wenn ein Alarm-Stichwort (z.B. "anniversary") textlich passt -
# z.B. weil es sich um andere Jubilaeen (25th/1st Anniversary) handelt.
ALERT_NOISE_PATTERN = re.compile(
    r"25th\s*anniversary|25\.\s*jubil|1st\s*anniversary|1\.\s*jubil|paradoxrift",
    re.IGNORECASE,
)

# Eingebettetes Platzhalter-SVG (keine Netzwerkanfrage nötig, falls ein
# Produktbild einmal nicht laedt)
PLACEHOLDER_IMG = (
    "data:image/svg+xml;charset=UTF-8,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 300 300'%3E"
    "%3Crect width='300' height='300' fill='%2310142a'/%3E"
    "%3Ctext x='50%25' y='50%25' fill='%239aa0c0' font-size='16' "
    "font-family='sans-serif' text-anchor='middle' dominant-baseline='middle'%3E"
    "Kein Bild%3C/text%3E%3C/svg%3E"
)

# Manuell zusammengestellter Release-Kalender (Stand: Recherche Juli 2026).
# Dies ist eine statische Momentaufnahme - keine Live-Daten! Termine von
# Special-Sets/Chinesischen Releases sind teils noch nicht offiziell
# bestaetigt und koennen sich verschieben. Deutsche Releases erscheinen in
# der Regel zeitgleich mit dem internationalen (englischen) Release.
RELEASE_CALENDAR = [
    {"date": "2026-01-23", "set": "Nihil Zero", "lang": "JP", "status": "erschienen"},
    {"date": "2026-01-30", "set": "Mega Evolution: Ascended Heroes", "lang": "EN", "status": "erschienen"},
    {"date": "2026-01-30", "set": "Mega-Entwicklung: Erhabene Helden", "lang": "DE", "status": "erschienen"},
    {"date": "2026-02-06", "set": "Nihil Zero (lokalisiert)", "lang": "CN (TW/HK)", "status": "erschienen"},
    {"date": "2026-03-13", "set": "Ninja Spinner", "lang": "JP", "status": "erschienen"},
    {"date": "2026-03-27", "set": "Ninja Spinner (lokalisiert)", "lang": "CN (TW/HK)", "status": "erschienen"},
    {"date": "2026-03-27", "set": "Mega Evolution: Perfect Order", "lang": "EN", "status": "erschienen"},
    {"date": "2026-03-27", "set": "Mega-Entwicklung: Optimale Ordnung", "lang": "DE", "status": "erschienen"},
    {"date": "2026-03-30", "set": "First Partner Illustration Collection - Serie 1", "lang": "EN/DE", "status": "erschienen"},
    {"date": "2026-05-22", "set": "Abyss Eye", "lang": "JP", "status": "erschienen"},
    {"date": "2026-05-22", "set": "Mega Evolution: Chaos Rising", "lang": "EN", "status": "erschienen"},
    {"date": "2026-05-22", "set": "Mega-Entwicklung: Wachsendes Chaos", "lang": "DE", "status": "erschienen"},
    {"date": "2026-06-19", "set": "Erste Partner Illustrations-Kollektion - Serie 2 (Johto/Unova/Galar)", "lang": "EN/DE", "status": "erschienen"},
    {"date": "2026-07-04", "set": "Pitch Black - Prerelease (Build & Battle)", "lang": "EN", "status": "bevorstehend"},
    {"date": "2026-07-17", "set": "Mega Evolution: Pitch Black", "lang": "EN", "status": "bevorstehend"},
    {"date": "2026-07-17", "set": "Mega-Entwicklung: Dunkelnacht", "lang": "DE", "status": "bevorstehend"},
    {"date": "2026-07-31", "set": "Storm Emeralda", "lang": "JP", "status": "bevorstehend"},
    {"date": "2026-08-07", "set": "Erste Partner Illustrations-Kollektion - Serie 3 (Hoenn/Kalos/Paldea)", "lang": "EN/DE", "status": "bevorstehend"},
    {"date": "2026-09-16", "set": "30th Celebration (weltweit simultan, inkl. JP/EN/DE)", "lang": "EN/JP/DE", "status": "bevorstehend"},
    {"date": "2026-09-16", "set": "Premium Deck Set: Espeon & Umbreon", "lang": "EN/DE", "status": "bevorstehend"},
    {"date": "2026-09-ca.", "set": "Storm Emerald (English/DE, Datum noch nicht offiziell)", "lang": "EN/DE (erwartet)", "status": "erwartet"},
    {"date": "2026-11-06", "set": "Mega Evolution: Delta Reign (Mega Rayquaza ex)", "lang": "EN", "status": "bevorstehend"},
    {"date": "2026-11-27", "set": "Mega Lucario Z Set", "lang": "JP", "status": "bevorstehend"},
]

CALENDAR_CACHE_FILE = "release_calendar_cache.json"

# Titel-Muster, die im Release-Kalender von pokezentrum.de auftauchen, aber
# KEINE eigenstaendigen versiegelten TCG-Produkte sind (reine Promokarten-
# Ankuendigungen, Zubehoer, Decks, Videos/Events) - werden beim Einlesen
# aussortiert, damit der Kalender nur echte Displays/ETBs/Kollektionen/
# Tins/Boosterbundles etc. zeigt.
_CALENDAR_EXCLUDE_PATTERN = re.compile(
    r"promokarte|promo\s*card|presents\b|challenge\b|lego\b|ultra\s*pro|"
    r"kampfdeck|liga-kampfdeck|weltmeisterschaftsdeck|world\s*championship|"
    r"binder|sammelalbum|spielmatte|deckbox|kartenh[üu]lle|"
    r"turnier\b(?!.*(kollektion|box))|ai\s*battle",
    re.IGNORECASE,
)


def _parse_pokezentrum_calendar(html_text):
    """Extrahiert Release-Termine aus dem rohen HTML von pokezentrum.de.
    Struktur der Seite: pro Eintrag ein <h3>DD.MM.YY - Titel</h3>, gefolgt
    (innerhalb der naechsten ~3000 Zeichen) von "Sprache: XYZ"."""
    header_pattern = re.compile(
        r'<h3 class="elementor-heading-title[^"]*">\s*(\d{2}\.\d{2}\.\d{2})\s*-\s*(.+?)</h3>',
        re.IGNORECASE,
    )
    lang_pattern = re.compile(r"Sprache:\s*([^<\n]+)")
    headers = [(m.start(), m.group(1), m.group(2)) for m in header_pattern.finditer(html_text)]
    langs = [(m.start(), m.group(1).strip()) for m in lang_pattern.finditer(html_text)]

    today = datetime.date.today()
    entries = []
    for i, (pos, date_str, raw_title) in enumerate(headers):
        # HTML-Tags/Anfuehrungszeichen aus dem Titel entfernen
        title = re.sub(r"<[^>]+>", "", raw_title)
        title = html.unescape(title).replace('"', "").strip()
        if _CALENDAR_EXCLUDE_PATTERN.search(title):
            continue
        adapted = {"title": title, "product_type": "", "tags": []}
        if not is_sealed_or_graded_product(adapted):
            continue  # kein eigenstaendiges versiegeltes Produkt

        # naechstgelegene "Sprache:"-Angabe NACH dieser Ueberschrift suchen
        # (aber vor der naechsten Ueberschrift, sonst gehoert sie zum
        # naechsten Eintrag)
        next_pos = headers[i + 1][0] if i + 1 < len(headers) else pos + 3000
        lang = next((l for lpos, l in langs if pos < lpos < next_pos), "?")
        if lang == "/":
            lang = "?"

        try:
            dd, mm, yy = date_str.split(".")
            year_num = int(f"20{yy}")
            month_num = int(mm)
            # Die Quelle selbst enthaelt gelegentlich Tippfehler beim Jahr
            # (z.B. "30.01.25" mitten in der 2026er-Kalenderseite, obwohl
            # eindeutig 2026 gemeint ist). Ein Jahr, das genau 1 zu niedrig
            # ist UND nicht in Nov/Dez liegt (wo ein Vorjahres-Datum
            # tatsaechlich plausibel waere), wird als Tippfehler korrigiert.
            if year_num == 2025 and month_num not in (11, 12):
                year_num = 2026
            iso_date = f"{year_num}-{mm}-{dd}"
            entry_date = datetime.date(year_num, month_num, int(dd))
        except ValueError:
            continue

        status = "erschienen" if entry_date <= today else "bevorstehend"
        entries.append({"date": iso_date, "set": title, "lang": lang, "status": status})
    return entries


def fetch_release_calendar_update():
    """Holt aktuelle Release-Termine von pokezentrum.de (cardmarket.com ist
    leider durch fortgeschrittenen Cloudflare-Bot-Schutz gesperrt und wird
    bewusst NICHT umgangen). Gibt eine Liste von Kalendereintraegen zurueck,
    oder None bei Fehlern (dann bleibt die zuletzt bekannte/statische Liste
    unveraendert bestehen)."""
    url = "https://pokezentrum.de/pokemon-karten-news/pokemon-sammelkartenspiel-release-kalender-2026/"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as resp:
            html_text = resp.read().decode("utf-8", errors="ignore")
        return _parse_pokezentrum_calendar(html_text)
    except Exception as exc:  # noqa: BLE001 - Kalender-Update darf den Scan nie abbrechen
        print(f"Release-Kalender-Update fehlgeschlagen: {exc}")
        return None


def get_release_calendar():
    """Liefert den aktuellen Release-Kalender - einmal taeglich automatisch
    von pokezentrum.de aktualisiert (nicht bei jedem 5-Minuten-Hintergrund-
    Scan, um die Seite nicht unnoetig oft abzufragen). Neue/aktualisierte
    Eintraege werden mit der handkuratierten Liste oben zusammengefuehrt
    (per Datum+Set-Name dedupliziert, gescrapte Daten haben Vorrang bei
    Konflikten, da sie aktueller sind)."""
    cached = {}
    try:
        with open(CALENDAR_CACHE_FILE, "r", encoding="utf-8") as f:
            cached = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cached = {}

    today_str = datetime.date.today().isoformat()
    if cached.get("fetched_on") == today_str and cached.get("entries"):
        scraped = cached["entries"]
    else:
        print("Aktualisiere Release-Kalender von pokezentrum.de ...")
        scraped = fetch_release_calendar_update()
        if scraped is not None:
            try:
                with open(CALENDAR_CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump({"fetched_on": today_str, "entries": scraped}, f, ensure_ascii=False)
                print(f"Release-Kalender aktualisiert: {len(scraped)} Eintraege von pokezentrum.de.")
            except OSError:
                pass
        else:
            scraped = cached.get("entries", [])

    # Zusammenfuehren: gescrapte Eintraege + statische Liste, dedupliziert
    # nach (Datum, normalisierter Set-Name). Gescrapte Daten haben Vorrang.
    merged = {}
    for entry in RELEASE_CALENDAR:
        key = (entry["date"], re.sub(r"\W+", "", entry["set"].lower())[:30])
        merged[key] = entry
    for entry in scraped:
        key = (entry["date"], re.sub(r"\W+", "", entry["set"].lower())[:30])
        merged[key] = entry  # ueberschreibt ggf. den statischen Eintrag
    # Koreanische Releases komplett ausblenden - konsistent zu den
    # Produkt-Scannern, die koreanische Artikel ebenfalls aussortieren
    # (fuer den Nutzer irrelevanter Markt).
    return [
        e for e in merged.values()
        if not re.search(r"koreanisch|korean|\bkr\b", str(e.get("lang", "")), re.IGNORECASE)
    ]


# -- Bedingte Anfragen (ETag / Last-Modified) -------------------------------
# Damit haeufiges Scannen moeglich ist, OHNE jedes Mal die kompletten
# Produktlisten neu herunterzuladen (und dadurch eine IP-Sperre zu
# riskieren): Beim ersten Abruf merkt sich das Skript den vom Shop
# gelieferten ETag/Last-Modified-Wert. Beim naechsten Abruf derselben URL
# wird dieser Wert mitgeschickt - hat sich nichts geaendert, antwortet der
# Server mit einem winzigen "304 Not Modified" (kein erneuter Download der
# ganzen Liste). Das reduziert Datenmenge UND Anfrage-Last drastisch, weil
# sich zwischen zwei Scans meist nur wenige Shops ueberhaupt aendern.
# Persistiert in einer Datei, damit die Ersparnis auch ueber Neustarts
# hinweg wirkt.
HTTP_CACHE_FILE = "http_cache.json"
_http_cache_lock = threading.Lock()
_HTTP_VALIDATORS = None  # {url: {"etag":, "last_modified":}} - lazy geladen


def _load_http_validators():
    global _HTTP_VALIDATORS
    if _HTTP_VALIDATORS is None:
        with _http_cache_lock:
            if _HTTP_VALIDATORS is None:
                try:
                    with open(HTTP_CACHE_FILE, "r", encoding="utf-8") as f:
                        _HTTP_VALIDATORS = json.load(f)
                except (FileNotFoundError, json.JSONDecodeError):
                    _HTTP_VALIDATORS = {}
    return _HTTP_VALIDATORS


def _save_http_validator(url, etag, last_modified):
    if not etag and not last_modified:
        return
    validators = _load_http_validators()
    with _http_cache_lock:
        validators[url] = {"etag": etag or "", "last_modified": last_modified or ""}
        try:
            with open(HTTP_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(validators, f, ensure_ascii=False)
        except OSError:
            pass


# Sentinel-Rueckgabewert von fetch_json, wenn der Server "304 Not Modified"
# meldet - die Daten sind unveraendert, der Aufrufer nutzt weiter seinen
# zuletzt bekannten Stand (bzw. bricht die Seiten-Schleife ab).
NOT_MODIFIED = object()


class BotChallengeError(ValueError):
    """Ein Shop hat statt JSON eine HTML-Bot-/Sicherheitspruefung geliefert
    (HTTP 200, aber kein verwertbarer Inhalt). Erbt von ValueError, damit
    die vorhandenen 'except ... ValueError'-Handler in scan_shop es wie
    einen normalen Scan-Fehler behandeln - nur mit klarer Meldung statt
    eines kryptischen JSON-Parse-Fehlers."""


# Roh-Produktlisten pro Shop-Seite (URL) - wird bei einer 304-Antwort
# ("nichts geaendert") wiederverwendet, damit die Artikel trotzdem
# angezeigt werden koennen, ohne sie erneut herunterzuladen.
SHOP_PAGE_CACHE_FILE = "shop_pages_cache.json"
_shop_page_lock = threading.Lock()
_SHOP_PAGE_CACHE = None

# Sammelt alle products.json-Seiten-URLs, die im AKTUELLEN Scan tatsaechlich
# abgefragt wurden - damit _prune_caches am Ende verwaiste Cache-Eintraege
# entfernen kann. Wird zu Beginn jedes Scans zurueckgesetzt.
_seen_urls_lock = threading.Lock()
_SEEN_SHOP_URLS = set()


def _reset_seen_urls():
    with _seen_urls_lock:
        _SEEN_SHOP_URLS.clear()


def _note_seen_url(url):
    with _seen_urls_lock:
        _SEEN_SHOP_URLS.add(url)


def _get_seen_urls():
    with _seen_urls_lock:
        return set(_SEEN_SHOP_URLS)


def _load_shop_page_cache():
    global _SHOP_PAGE_CACHE
    if _SHOP_PAGE_CACHE is None:
        with _shop_page_lock:
            if _SHOP_PAGE_CACHE is None:
                try:
                    with open(SHOP_PAGE_CACHE_FILE, "r", encoding="utf-8") as f:
                        _SHOP_PAGE_CACHE = json.load(f)
                except (FileNotFoundError, json.JSONDecodeError):
                    _SHOP_PAGE_CACHE = {}
    return _SHOP_PAGE_CACHE


def _load_cached_shop_page(url):
    """Zuletzt gespeicherte Produktliste dieser Seiten-URL (oder None)."""
    return _load_shop_page_cache().get(url)


def _save_cached_shop_page(url, products):
    cache = _load_shop_page_cache()
    with _shop_page_lock:
        cache[url] = products
        try:
            with open(SHOP_PAGE_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False)
        except OSError:
            pass


def _prune_caches(seen_urls):
    """Entfernt aus beiden Cache-Dateien alle URLs, die im letzten Scan NICHT
    mehr abgerufen wurden (z.B. weil ein Shop weniger Seiten hat oder aus der
    Liste geflogen ist). Verhindert, dass die Cache-Dateien mit der Zeit
    unbegrenzt wachsen - v.a. shop_pages_cache.json, das die kompletten
    Produkt-Rohdaten haelt. Wird am Ende von run_scan aufgerufen."""
    seen = set(seen_urls)
    if not seen:
        return  # Sicherheitsnetz: bei leerem Scan (alles blockiert) nichts loeschen
    for cache_file, cache_obj, lock in (
        (HTTP_CACHE_FILE, _load_http_validators(), _http_cache_lock),
        (SHOP_PAGE_CACHE_FILE, _load_shop_page_cache(), _shop_page_lock),
    ):
        with lock:
            stale = [u for u in cache_obj if u not in seen]
            if not stale:
                continue
            for u in stale:
                cache_obj.pop(u, None)
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(cache_obj, f, ensure_ascii=False)
            except OSError:
                pass


def fetch_json(url, retries=3, use_cache=False):
    """Laedt JSON von url. Mit use_cache=True werden bedingte Anfragen
    genutzt: hat sich seit dem letzten Abruf nichts geaendert, gibt die
    Funktion das Sentinel NOT_MODIFIED zurueck statt die (unveraenderten)
    Daten erneut herunterzuladen."""
    headers = {"User-Agent": USER_AGENT}
    if use_cache:
        cached = _load_http_validators().get(url)
        if cached:
            if cached.get("etag"):
                headers["If-None-Match"] = cached["etag"]
            if cached.get("last_modified"):
                headers["If-Modified-Since"] = cached["last_modified"]

    req = urllib.request.Request(url, headers=headers)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
                if use_cache:
                    _save_http_validator(
                        url, resp.headers.get("ETag"), resp.headers.get("Last-Modified")
                    )
                raw = resp.read()
                text = raw.decode("utf-8-sig")
                stripped = text.lstrip()
                # Manche Shops liefern statt JSON eine HTML-"Sicherheits-
                # pruefung" (JavaScript-Bot-Challenge, z.B. Zenit/ZPG). Das
                # ist HTTP 200, aber eben kein JSON - ohne diese Pruefung
                # wuerde json.loads mit dem kryptischen "Expecting value:
                # line 1 column 1" scheitern, und im schlimmsten Fall
                # rutschte die Challenge-Seite als "Produkt" durch.
                if stripped[:1] in ("<",) or "<html" in stripped[:400].lower():
                    low = stripped[:1500].lower()
                    if any(m in low for m in (
                        "sicherheitspruefung", "sicherheitsprüfung", "security check",
                        "captcha", "just a moment", "cf-browser-verification",
                        "checking your browser", "zpg", "zenit",
                    )):
                        raise BotChallengeError(
                            "Shop zeigt eine Bot-/Sicherheitspruefung statt der "
                            "Produktliste (per einfachem Scan nicht abrufbar)"
                        )
                    raise BotChallengeError(
                        "Shop lieferte HTML statt JSON (products.json vermutlich "
                        "gesperrt oder nicht vorhanden)"
                    )
                return json.loads(text)
        except urllib.error.HTTPError as exc:
            if exc.code == 304:
                return NOT_MODIFIED  # unveraendert - kein Neu-Download noetig
            if exc.code in (429, 503) and attempt < retries - 1:
                wait = 3 * (attempt + 1)
                print(f"   {exc.code} - warte {wait}s und versuche erneut ...")
                time.sleep(wait)
                continue
            raise


OTHER_TCG_PATTERN = re.compile(
    r"dragon\s*ball|digimon|magic\s*the\s*gathering|\bmtg\b|"
    r"flesh\s*and\s*blood|star\s*wars\s*unlimited|final\s*fantasy\s*tcg|"
    r"union\s*arena|gundam|weiss\s*schwarz|weiß\s*schwarz|"
    r"cardfight.?vanguard|marvel\s*champions|zatch\s*bell|shadowverse",
    re.IGNORECASE,
)


def is_pokemon_product(product):
    # WICHTIG: Das "vendor"-Feld wird bewusst NICHT mehr geprueft - manche
    # Shops setzen es fehlerhaft/pauschal auf "Pokemon" fuer ALLE Produkte
    # (auch fuer andere TCGs wie Dragon Ball, Magic etc.), unabhaengig vom
    # tatsaechlichen Inhalt. Titel/Typ/Tags sind zuverlaessiger.
    haystack = " ".join([
        product.get("title", ""),
        product.get("product_type", ""),
        " ".join(product.get("tags", []) or []),
    ])
    if OTHER_TCG_PATTERN.search(haystack):
        return False  # explizit ein anderes Sammelkartenspiel -> nie Pokemon
    return bool(POKEMON_PATTERN.search(haystack))


def is_preorder_product(product):
    # Nur der Produkttitel wird geprueft. Der Handle (URL-Slug) wird bei
    # vielen Shops beim Erstellen einmalig festgelegt und bleibt oft auch
    # nach Ablauf der Vorbestellphase auf "...-preorder" stehen - das fuehrt
    # sonst zu veralteten Treffern. Der Titel wird dagegen aktiv gepflegt.
    return bool(PREORDER_PATTERN.search(product.get("title", "")))


def is_graded_product(product):
    """True, wenn es sich um eine gegradete Karte handelt (PSA/BGS/CGC/...).
    Diese werden NICHT ausgeschlossen, sondern als eigene Kategorie ohne
    Sprachfilter gefuehrt."""
    haystack = " ".join([
        product.get("title", ""),
        product.get("product_type", ""),
        " ".join(product.get("tags", []) or []),
    ])
    return bool(GRADED_PATTERN.search(haystack))



def is_sealed_or_graded_product(product):
    """True, wenn das Produkt entweder ein versiegeltes Pokemon-TCG-Produkt,
    Zubehoer, ODER eine gegradete Karte ist - also alles ausser: ungegradete
    Einzelkarten, Turnier-Tickets, und irrelevante Merch-Kategorien."""
    haystack = " ".join([
        product.get("title", ""),
        product.get("product_type", ""),
        " ".join(product.get("tags", []) or []),
    ])
    if TICKET_EXCLUDE_PATTERN.search(haystack):
        return False
    if CATEGORY_EXCLUDE_PATTERN.search(haystack):
        return False
    if PUZZLE_FIGURE_PATTERN.search(haystack) and not PUZZLE_FIGURE_KEEP_PATTERN.search(haystack):
        return False  # reines Merchandise ohne Booster/Karten -> raus
    if is_graded_product(product):
        return True  # gegradete Karten immer durchlassen (eigene Kategorie)
    if SINGLE_CARD_EXCLUDE_PATTERN.search(haystack):
        return False  # ungegradete Einzelkarte -> raus
    return True


def normalize_title(title):
    """Normalisiert einen Produkttitel, um identische/aehnliche Artikel
    aus verschiedenen Shops fuer den Preisvergleich zu gruppieren."""
    t = title.lower()
    t = t.replace("pokémon", "pokemon").replace("pokèmon", "pokemon").replace("é", "e").replace("è", "e")
    t = re.sub(r"[^a-z0-9]+", " ", t)  # nur Buchstaben/Ziffern behalten
    t = re.sub(r"\s+", " ", t).strip()
    return t


# Fuellwoerter, die beim Token-Vergleich ignoriert werden, weil sie nichts
# zur eigentlichen Produktidentitaet beitragen (Sprache wird separat schon
# erkannt, generische Marketing-/Shop-Woerter bringen nur Rauschen rein).
_TITLE_STOPWORDS = {
    "pokemon", "tcg", "karten", "sammelkarten", "trading", "card", "cards",
    "game", "spiel", "de", "deu", "en", "eng", "engl", "jp", "jap", "jpn", "cn", "chn",
    "kr", "kor", "s", "ch", "info", "beachten", "neu", "ovp", "sealed",
    "the", "and", "of", "der", "die", "das", "für", "fuer", "mit", "und",
    "a", "an", "in", "im", "auf", "zu", "mit",
    # Serien-/Generationsnamen: werden von manchen Shops als Praefix vor den
    # eigentlichen Set-Namen geschrieben, von anderen weggelassen - das
    # verwaessert sonst den Aehnlichkeitsvergleich zwischen Shops erheblich
    # (z.B. "Schwert & Schild Strahlende Sterne" vs. nur "Strahlende Sterne").
    "schwert", "schild", "sword", "shield", "karmesin", "purpur", "scarlet",
    "violet", "sonne", "mond", "sun", "moon", "schwarz", "weiss", "weiß",
    "black", "white", "diamant", "perl", "diamond", "pearl",
    # Ausgeschriebene Sprachnamen sind redundant, da Sprache schon separat
    # als hartes Kriterium (gleicher Bucket) geprueft wird - nur Rauschen.
    "deutsch", "englisch", "japanisch", "chinesisch", "koreanisch",
    "german", "japanese", "chinese", "korean", "english",
    # generische Verpackungs-Fuellwoerter
    "pack", "packs", "packung",
    # Produkt-TIER-Woerter (nicht die spezifische Karte/das Pokemon!) sind
    # redundant und fuehren sonst zu falschen Treffern zwischen komplett
    # unterschiedlichen Produkten, die zufaellig beide "Premium"/"Ultra"
    # im Namen tragen (z.B. "Terapagos ex Ultra Premium Kollektion" haette
    # sonst mit "Glurak Ultra-Premium-Kollektion" ueber die gemeinsamen
    # Woerter "ultra"+"premium" gematcht, obwohl es zwei verschiedene
    # Pokemon/Produkte sind).
    "premium", "ultra", "super", "gift", "center", "special", "spezial", "mini", "portfolio", "sommer",
    "herbst", "winter", "fruehling", "fall", "chest", "collector", "sammelkoffer",
    "simplified", "traditional", "laden", "enhanced", "original", "ovp", "sammler", "edition",
    "kaufen", "promo", "absolute", "raritaet", "promokarte", "vollbild",
    "zubehoer", "boosterpacks", "alola", "stueck",
    # Produktart-Woerter sind redundant, weil Angebote nur INNERHALB der
    # gleichen erkannten Kategorie (z.B. "Display") verglichen werden -
    # das Wort "display" traegt dort nichts zur Unterscheidung bei und
    # verwaessert sonst den Vergleich zwischen leicht unterschiedlich
    # formulierten Shop-Titeln fuer das gleiche Set.
    "display", "booster", "box", "tin", "deck", "collection", "kollektion",
    "elite", "trainer", "top", "blister", "bundle", "sleeve", "sleeves",
    "kartenhülle", "kartenhuelle", "hülle", "huelle", "hüllen", "huellen",
    "etb", "ttb", "set", "sets",
}


# Manche Shops schreiben Set-Namen auf Englisch, andere auf Deutsch - ohne
# Uebersetzungstabelle haetten diese Titel NIE ein gemeinsames Wort und
# koennten nie als "gleiches Produkt" erkannt werden. Bei jedem Treffer wird
# ein gemeinsames canonical_tag zu den Tokens hinzugefuegt, unabhaengig
# davon in welcher Sprache der Titel geschrieben ist.
SET_NAME_ALIASES_RAW = [
    (r"journey\s*together", r"reisegef(ä|ae)hrten", "csetjourneytogether"),
    (r"destined\s*rivals", r"ewige\s*rivalen", "csetdestinedrivals"),
    (r"twilight\s*masqu[ae]rade", r"maskerade\s*im\s*zwielicht", "csettwilightmasquerade"),
    (r"illumina\s*city|lumiose\s*city", None, "csetilluminacity"),
    (r"shrouded\s*fable", r"nebel\s*der\s*sagen", "csetshroudedfable"),
    (r"stellar\s*crown", r"stellarkrone", "csetstellarcrown"),
    (r"surging\s*sparks", r"st(ü|ue)rmische\s*funken", "csetsurgingsparks"),
    (r"prismatic\s*evolutions?", r"prismatische\s*entwicklung(en)?", "csetprismaticevolutions"),
    (r"paradox\s*rift", r"paradoxrift", "csetparadoxrift"),
    (r"obsidian\s*flames", r"obsidian\s*flammen", "csetobsidianflames"),
    (r"paldea\s*evolved", r"entwicklungen\s*in\s*paldea", "csetpaldeaevolved"),
    (r"silver\s*tempest", r"silberne\s*sturmwinde", "csetsilvertempest"),
    (r"lost\s*origin", r"verlorener\s*ursprung", "csetlostorigin"),
    (r"astral\s*radiance", r"astralglanz", "csetastralradiance"),
    (r"brilliant\s*stars", r"strahlende\s*sterne", "csetbrilliantstars"),
    (r"fusion\s*strike", r"fusionsangriff", "csetfusionstrike"),
    (r"darkness\s*ablaze", r"nacht\s*in\s*flammen", "csetdarknessablaze"),
    (r"vivid\s*voltage", r"farbenschock", "csetvividvoltage"),
    (r"rebel\s*clash", r"shcksalhafte?\s*kollision|schicksalhafte\s*kollision", "csetrebelclash"),
    (r"ascended\s*heroes", r"erhabene\s*helden", "csetascendedheroes"),
    (r"perfect\s*order", r"optimale\s*ord(n)?ung", "csetperfectorder"),
    (r"chaos\s*rising", r"wachsendes\s*chaos", "csetchaosrising"),
    (r"pitch\s*black", r"dunkelnacht", "csetpitchblack"),
    (r"black\s*bolt", r"schwarze\s*blitze", "csetblackbolt"),
    (r"white\s*flare", None, "csetwhiteflare"),
    # "GO" ist in beiden Sprachen identisch geschrieben - kein Uebersetzungs-
    # paar noetig, aber trotzdem als eigener Alias, damit "GO Top-Trainer-
    # Box - DE" und "GO Elite Trainer Box - EN" ueber die Sprachsperre hinweg
    # als gleiches Produkt erkannt werden. Bewusst NICHT bloßes "\bgo\b"
    # (zu unspezifisch, z.B. "Let's Go Pikachu"), sondern nur zusammen mit
    # einem erkennbaren Produkttyp-Wort direkt danach.
    (r"\bgo[\s:-]*(top[\s-]*trainer|elite[\s-]*trainer|tin|booster|display)",
     r"\bgo[\s:-]*(top[\s-]*trainer|elite[\s-]*trainer|tin|booster|display)",
     "csetpokemongo"),
    (r"paldean\s*fates", r"paldeas\s*schicksale", "csetpaldeanfates"),
    (r"nihil\s*zero", r"munix\s*zero", "csetnihilzero"),
    (r"hidden\s*fates", r"verborgen(es|e)?\s*schicksal", "csethiddenfates"),
    (r"phantasmal\s*flames", r"fatale\s*flammen", "csetphantasmalflames"),
    (r"crown\s*zenith", r"zenit\s*der\s*koenige", "csetcrownzenith"),
    (r"shining\s*fates", r"glaenzendes\s*schicksal", "csetshiningfates"),
    (r"darkness\s*ablaze", r"flammende\s*finsternis", "csetdarknessablaze"),
    (r"ancient\s*martial\s*arts|primordial\s*arts", None, "csetancientmartialarts"),
    (r"polychromatic\s*gathering|nine\s*colors\s*gathering", None, "csetninecolorsgathering"),
    (r"30th\s*anniversary\s*(partner\s*special\s*illustration|first\s*partner)\s*card\s*set", None, "cset30thannipartner"),
    (r"bonus\s*round|reward\s*round", None, "csetbonusround"),
    # HINWEIS: Ein "151"-Alias wurde bewusst NICHT aufgenommen - das ist zu
    # generisch (praktisch jedes "151"-Produkt, egal welches Pokemon/welche
    # Sprache, haette sonst automatisch gematcht - das war eine echte
    # Fehlgruppierungsursache).
    (r"scarlet\s*(&|\+)?\s*violet[\s-]+((sv|kp)\d{1,3}[\s-]+|(?!151\b)\d+\w*[\s-]+)?(display|booster|tin|etb|elite|top|box)",
     r"karmesin\s*(&|\+|und)?\s*purpur[\s-]+((sv|kp)\d{1,3}[\s-]+|(?!151\b)\d+\w*[\s-]+)?(display|booster|tin|etb|elite|top|box)",
     "csetbaseset"),
    (None, r"\bbaseset\b|\bbase\s*set\b|\bgrundset\b", "csetbaseset"),
    # Japanische Basisset-Ausgaben heissen oft nur "Violet ex" ODER
    # "Scarlet ex" (nur EINE der beiden Starterfarben, nicht die
    # kombinierte "Scarlet & Violet"-Bezeichnung wie im Westen).
    (None, r"\b(scarlet|violet)\s*ex\s+((sv\d{1,3}[a-z]?|\d+\w*)\s+)?(display|booster|tin|etb|elite|top|box)", "csetbaseset"),
    # Schwert & Schild (Sword & Shield) Basisset - EIGENER Tag, nicht
    # csetbaseset, sonst wuerde es faelschlich mit dem Karmesin & Purpur/
    # Scarlet & Violet Basisset (andere Generation!) vermischt.
    (r"sword\s*(&|\+)?\s*shield[\s-]+((display|booster|base)\s*)*(display|booster)",
     r"schwert\s*(&|\+|und)?\s*schild[\s-]+((display|booster|base)\s*)*(display|booster)",
     "csetswshbaseset"),
]

# Pokemon-Namen (DE/EN): NICHT als kuratierten Bypass-Tag (wie Set-Namen),
# sondern als einfache WORT-NORMALISIERUNG - der gemeinsame Pokemon-Name
# zaehlt dann als EIN ganz normales Token, das (zusammen mit allen anderen
# Woertern) in die normale Jaccard/Containment-Berechnung eingeht, statt
# automatisch einen sicheren Treffer auszuloesen. Grund: die selbe Figur
# (z.B. Glurak/Charizard) taucht in dutzenden voellig unterschiedlichen
# Produkten auf (File Set, VMAX Battle Box, UPC, Tin, ...) - ein reiner
# Namens-Treffer allein ist KEIN verlaesslicher Beleg fuer "gleiches
# Produkt", im Gegensatz zu einem vollen, spezifischen Set-Namen.
POKEMON_NAME_NORMALIZE = [
    (re.compile(r"\bcharizard\b", re.IGNORECASE), "glurak"),
    (re.compile(r"\bblastoise\b", re.IGNORECASE), "turtok"),
    (re.compile(r"\bvenusaur\b", re.IGNORECASE), "bisaflor"),
    (re.compile(r"\bmewtwo\b", re.IGNORECASE), "mewtu"),
    (re.compile(r"\beevee\b", re.IGNORECASE), "evoli"),
    (re.compile(r"\bumbreon\b", re.IGNORECASE), "nachtara"),
    (re.compile(r"\bespeon\b", re.IGNORECASE), "psiana"),
    (re.compile(r"\bsylveon\b", re.IGNORECASE), "feelinara"),
    (re.compile(r"\bvaporeon\b", re.IGNORECASE), "aquana"),
    (re.compile(r"\bjolteon\b", re.IGNORECASE), "blitza"),
    (re.compile(r"\bflareon\b", re.IGNORECASE), "flamara"),
    (re.compile(r"\bglaceon\b", re.IGNORECASE), "firnontor"),
    (re.compile(r"\bleafeon\b", re.IGNORECASE), "folipurba"),
    (re.compile(r"\bdragonite\b", re.IGNORECASE), "dragoran"),
    (re.compile(r"\bgarchomp\b", re.IGNORECASE), "knakrack"),
    (re.compile(r"\bknackrack\b", re.IGNORECASE), "knakrack"),  # haeufiger Rechtschreibfehler
    (re.compile(r"\bcynthia['’]?s\b", re.IGNORECASE), "cynthias"),  # Apostroph-S uneinheitlich verwendet (auch Unicode-Apostroph)
    (re.compile(r"\bgreninja\b", re.IGNORECASE), "quajutsu"),
    (re.compile(r"\bsnorlax\b", re.IGNORECASE), "relaxo"),
    (re.compile(r"\bhoundstone\b", re.IGNORECASE), "friedwuff"),
    (re.compile(r"\bpalafin\b", re.IGNORECASE), "delfinator"),
    (re.compile(r"\bskeledirge\b", re.IGNORECASE), "skelokrok"),
    (re.compile(r"\bwalking\s*wake\b", re.IGNORECASE), "windewoge"),
    (re.compile(r"\biron\s*leaves\b", re.IGNORECASE), "eisenblatt"),
]

# Kombinierte Liste (fuer die Produkt-Aehnlichkeit - Sprache egal, Hauptsache
# das gleiche Set wird erkannt) und getrennte EN-/DE-Listen (um aus einem
# bekannten Set-Namen die Sprache abzuleiten - siehe detect_language()).
SET_NAME_ALIASES = []
SET_NAME_EN_PATTERNS = []
SET_NAME_DE_PATTERNS = []
for en, de, tag in SET_NAME_ALIASES_RAW:
    parts = [p for p in (en, de) if p]
    SET_NAME_ALIASES.append((re.compile("|".join(parts), re.IGNORECASE), tag))
    if en:
        SET_NAME_EN_PATTERNS.append(re.compile(en, re.IGNORECASE))
    if de:
        SET_NAME_DE_PATTERNS.append(re.compile(de, re.IGNORECASE))


def title_tokens(title):
    """Zerlegt einen Titel in eine Menge bedeutungstragender Woerter
    (Setname, Edition, Zahlen etc.), Fuellwoerter/Sprachkuerzel raus.
    Erkannte Set-Namen (auch ueber Sprachgrenzen hinweg, z.B. "Journey
    Together" = "Reisegefährten") werden zusaetzlich als canonical Tag
    hinzugefuegt. Zustand (B-Ware) und "zufaellige Auswahl" werden als
    eigene, IMMER erhaltene Merkmale behandelt - ein B-Ware-Artikel darf
    nie mit einem neuwertigen zusammengefasst werden, und eine zufaellige
    Variante nie mit einer fest gewaehlten."""
    t = title.lower().replace("pokémon", "pokemon").replace("pokèmon", "pokemon").replace("é", "e").replace("è", "e")
    # WICHTIG: HTML-Reste (z.B. "<br>" von God of Cards) muessen VOR der
    # Set-Namen-Erkennung entfernt werden - sonst z.B. "Violet <br> 36er
    # Display" nicht als "Violet ... Display" erkannt, weil das Tag
    # zwischen den Woertern steht und die Regex blockiert.
    t = re.sub(r"<br\s*/?>", " ", t)
    # WICHTIG: Umlaute NORMALISIEREN statt einfach zu entfernen - sonst wird
    # z.B. "reisegefährten" durch die spaetere Regex in "reisegef" + "hrten"
    # zerrissen (das "ä" faellt komplett weg), was den Vergleich zwischen
    # Shops mit dem gleichen deutschen Set-Namen kaputt macht.
    t = t.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    # Katalog-/Referenznummern ("Tin #128", "#122") sind reine interne
    # Nummerierungen des Shops, keine unterscheidende Produktinfo - werden
    # entfernt, damit sie nicht faelschlich als eigenstaendiges
    # Unterscheidungsmerkmal gezaehlt werden.
    t = re.sub(r"\btin\s*#\s*\d{1,4}\b", "tin", t)
    t = re.sub(r"#\s*\d{1,4}\b", " ", t)
    # WICHTIG: Boosteranzahl ZUERST erkennen, bevor irgendeine Set-Namen-
    # Phrase entfernt wird - die Baseset-Erkennung z.B. erlaubt "18er" als
    # Teil ihrer Bruecke ("Karmesin & Purpur 18er Display") und wuerde beim
    # Entfernen der Phrase "18er" gleich mitverschlucken, wodurch die
    # Boosteranzahl-Pruefung unten nie etwas zu sehen bekommt.
    count_match_early = re.search(
        r"\b(18|20|30)\s*(?:er\b|-?er\b|\s*booster|\s*st(ü|ue)ck|\s*packs?)", t
    )
    _early_boostercount_tag = f"boostercount{count_match_early.group(1)}" if count_match_early else None
    # "N-Pack Blister" (2-Pack vs. 3-Pack etc.) - unterschiedliche
    # Kartenanzahl im Blister ist ein anderes physisches Produkt, genau wie
    # bei der Boosteranzahl bei Displays.
    packcount_match = re.search(r"\b(\d)[\s-]*pack\s*blister\b|\b(\d)er\s*booster\s*blister\b", t)
    _packcount_num = packcount_match.group(1) or packcount_match.group(2) if packcount_match else None
    _early_packcount_tag = f"packcount{_packcount_num}" if _packcount_num else None
    # Kollektion-Stufe (Spezial/Premium/Super Premium) - bei "normalen"
    # Spezial-Kollektionen (nicht den grossen benannten UPC-Sets) sind das
    # tatsaechlich UNTERSCHIEDLICHE Produkte mit unterschiedlichem Inhalt/
    # Preis, kein reines Fuellwort. Nur wenn EXPLIZIT genannt (nicht bei
    # Fehlen einer Stufenangabe) - sonst wuerde eine generische "Kollektion"
    # ohne Stufenangabe faelschlich blockieren.
    _tier_match = re.search(r"(?<!ultra[\s-])\b(super[\s-]*premium|premium|spezial|special)[\s-]*(kollektion|collection)\b", t)
    if _tier_match:
        _tier_raw = _tier_match.group(1).replace(" ", "").replace("-", "")
        _tier_raw = _tier_raw.replace("spezial", "special")  # DE/EN gleicher Tier-Wert
        _early_tier_tag = f"tier{_tier_raw}"
    else:
        _early_tier_tag = None
    # Japanische Einzelstarter-Ausgabe ("Scarlet ex"/"Violet ex" - NICHT
    # die kombinierte "Scarlet & Violet"-Form) fruehzeitig erfassen, bevor
    # die Phrase weiter unten entfernt wird - sonst geht die Information
    # verloren, WELCHER der beiden Starter gemeint ist.
    _starter_match = re.search(r"\b(scarlet|violet)\s*ex\b(?!\s*&)", t)
    _early_starter_tag = f"starter{_starter_match.group(1)}" if (
        _starter_match and not re.search(r"scarlet\s*(&|\+)\s*violet", t)
    ) else None
    # WICHTIG: Erst ALLE Tags anhand des UNVERAENDERTEN Texts erkennen,
    # dann ERST die Phrasen entfernen (zwei getrennte Durchgaenge!) - sonst
    # koennte das Entfernen einer spezifischen Phrase (z.B.
    # "Obsidianflammen") den Text so aussehen lassen, als waere er ein
    # generisches Baseset-Produkt ("Karmesin & Purpur ... Top Trainer
    # Box" OHNE den spezifischen Set-Namen dazwischen) und faelschlich
    # zusaetzlich den csetbaseset-Tag ausloesen.
    canonical_tags = {tag for pattern, tag in SET_NAME_ALIASES if pattern.search(t)}
    if _early_boostercount_tag:
        canonical_tags.add(_early_boostercount_tag)
    if _early_packcount_tag:
        canonical_tags.add(_early_packcount_tag)
    if _early_tier_tag:
        canonical_tags.add(_early_tier_tag)
    if _early_starter_tag:
        canonical_tags.add(_early_starter_tag)
    for pattern, tag in SET_NAME_ALIASES:
        if tag in canonical_tags:
            # Die erkannte Set-Namen-Phrase auch aus dem Text entfernen -
            # sie wird ja bereits durch den canonical Tag repraesentiert.
            # Bleibt sie als literale Woerter (z.B. "verborgenes",
            # "schicksal") stehen, verwaessert das spaetere Ein-Wort-
            # Sicherheitspruefungen, wenn nur EINE Seite den Set-Namen
            # ausschreibt (siehe "Verborgenes Schicksal: Glurak GX Tin"
            # vs. einfach "Glurak-GX Tin Box" - beide sind dasselbe
            # Produkt, nur einer nennt den Set-Namen explizit dazu).
            t = pattern.sub(" ", t)
    # Zustand: B-Ware/Gebraucht sind ein ANDERES Produkt als "Neu" - als
    # eigenen, nicht entfernbaren Marker-Token erhalten (statt z.B. "b-ware"
    # durch die Tokenisierung ins bedeutungslose Einzelzeichen "b" + "ware"
    # zu zerlegen, wo "b" durch die Mindestlaenge sowieso wegfaellt).
    if re.search(r"\bb-?ware\b", t):
        canonical_tags.add("condbware")
        t = re.sub(r"\bb-?ware\b", " ", t)
    if re.search(r"\bgebraucht\b|\bused\b|\bopened\b|\bopen\s*box\b", t):
        canonical_tags.add("condused")
        t = re.sub(r"\bgebraucht\b|\bused\b|\bopened\b|\bopen\s*box\b", " ", t)
    # Zufaellige Auswahl aus mehreren INHALTLICH unterschiedlichen Varianten
    # ist ein ANDERES Produkt als eine fest gewaehlte einzelne Variante.
    # "Zufaelliges Design/Motiv" dagegen betrifft nur die kosmetische
    # Verpackungsgestaltung (gleicher Inhalt, nur die Box sieht anders
    # aus) - das ist NICHT das gleiche wie eine inhaltliche Zufallsauswahl.
    if re.search(r"zuf(ä|ae)llige?s?\s*design|zuf(ä|ae)llige?s?\s*motiv|random\s*design", t):
        pass  # bewusst KEIN condrandom - nur kosmetische Verpackungsvarianz
    elif re.search(r"zuf(ä|ae)llige?s?\s*(auswahl|variante)?|random\s*(selection|variant)?|"
                 r"\d\s*von\s*\d\s*zuf(ä|ae)llige?", t):
        canonical_tags.add("condrandom")
    # "Mega" ist zweideutig: entweder Teil des aktuellen Serien-Namens
    # ("Mega-Entwicklung"/"Mega Evolution" - redundant, betrifft fast jedes
    # Produkt der aktuellen Aera) ODER Teil des konkreten Pokemon-Namens
    # ("Mega Glurak X" = ein ANDERES Pokemon/Karte als normales "Glurak"!).
    # Die Serien-Phrase wird gezielt entfernt, ein danach noch uebrig
    # bleibendes "mega" (vor einem Pokemon-Namen) bleibt als hartes
    # Unterscheidungsmerkmal erhalten.
    t, _mega_evo_count = re.subn(r"\bmega\s*-?\s*(entwicklung(en)?|evolution)\b", " ", t)
    had_mega_evolution_phrase = _mega_evo_count > 0
    if re.search(r"\bmega\b", t):
        canonical_tags.add("modmega")
    # "Pokemon Center [Elite/Top] Trainer Box" ist eine SONDERVARIANTE
    # (exklusiv nur im Pokemon Center verkauft, meist deutlich teurer/mit
    # anderem Inhalt) - eine GANZ ANDERE physische Box als die normale
    # Elite Trainer Box vom selben Set, auch wenn "center" sonst als
    # generisches Fuellwort behandelt wird (z.B. bei Staedte-Boxen).
    if re.search(r"center\s*(elite|top)?\s*[-]?\s*trainer\s*box|center\s*(e|t)tb\b", t):
        canonical_tags.add("modcenteretb")
    # "Vol. 1" / "Vol. 4" / "Volume 3" etc. - unterschiedliche Volumes vom
    # SELBEN Reihen-Namen (z.B. "Gem Pack Vol. 1" bis "Vol. 5") sind
    # unterschiedliche Produkte mit unterschiedlichem Inhalt/Preis, teilen
    # sich aber sonst fast alle Woerter ("gem", "pack", "box"...). Die
    # konkrete Volume-Nummer wird deshalb als eigenes Merkmal erfasst und
    # weiter unten als harte Sperre bei UNTERSCHIEDLICHER Nummer genutzt.
    # WICHTIG: manche Shops lassen "Vol."/"Volume" einfach weg und schreiben
    # nur "Gem Pack 2" statt "Gem Pack Vol. 2" - das ist trotzdem dieselbe
    # Nummerierung und muss den gleichen Marker bekommen. Genauso zaehlen
    # "V1"/"V2" (ohne "Vol.") und "Serie 1"/"Serie 2" als GLEICHWERTIGE
    # Versions-Kennzeichnung (z.B. "Erste Partner Kollektion V1" = "...
    # Serie 1") - beide muessen denselben volnum-Marker bekommen, damit
    # Serie 1 nie mit Serie 2 verwechselt wird, aber "V1" und "Serie 1"
    # trotzdem als dieselbe Version gelten.
    vol_match = re.search(
        r"\bvol(?:ume)?\.?\s*(\d+)\b|\bgem\s*pack\s*(?:vol(?:ume)?\.?\s*)?(\d+)\b|"
        r"(?<![a-z])v(\d)\b|\bseries?\s*(\d+)\b",
        t,
    )
    if vol_match:
        vol_num = next(g for g in vol_match.groups() if g)
        canonical_tags.add(f"volnum{vol_num}")
        # Die erkannte Phrase selbst entfernen - sonst bleiben je nach
        # Schreibweise unterschiedliche Reste uebrig (z.B. "vol" bei
        # "Vol. 1" vs. "v1" bei "V1"), die sich nicht gegenseitig als
        # Uebereinstimmung zaehlen und die Erkennung verwaessern.
        t = t[:vol_match.start()] + " " + t[vol_match.end():]
    elif re.search(r"(erste[\s-]*partner|first[\s-]*partner)", t):
        # Ohne explizite Seriennummer war es die urspruengliche (erste)
        # Ausgabe - erst spaetere Ausgaben bekamen "Serie 2"/"Serie 3" im
        # Namen dazu. Verhindert, dass eine unnummerierte "Erste-Partner-
        # Kollektion" faelschlich mit einer explizit als "Serie 2"
        # benannten Ausgabe zusammengefuehrt wird.
        canonical_tags.add("volnum1")
    # Jahreszahl (z.B. "Back to School Collectors Chest 2024" vs. "...
    # 2023") ist bei jaehrlich wiederkehrenden Sonderprodukten oft die
    # EINZIGE Unterscheidung zwischen zwei sonst fast identisch benannten,
    # aber unterschiedlichen Produkten (andere Box-Gestaltung pro Jahr). Wird
    # als eigenes Merkmal erfasst und weiter unten als harte Sperre bei
    # UNTERSCHIEDLICHEM Jahr genutzt (nur wenn beide Seiten explizit ein
    # Jahr nennen).
    year_match = re.search(r"\b(20[12]\d)\b", t)
    if year_match:
        canonical_tags.add(f"year{year_match.group(1)}")
    # "Enhanced" (EN) und "Aufgewertet(e/er)" (DE) sind das gleiche Konzept -
    # als Synonym behandeln, damit sie sich nicht gegenseitig ausschliessen.
    t = re.sub(r"\baufgewertete?r?\b", "enhanced", t)
    t = re.sub(r"\b(booster\s*box)\b", "display", t)  # Synonym fuer Display
    t = re.sub(r"\bheroes\b", "helden", t)  # DE/EN Synonym (z.B. "Mega Heroes"="Mega Helden")
    t = re.sub(r"\brockets\b", "rocket", t)  # Team Rocket(s) - manche Shops haengen ein "s" an
    t = re.sub(r"\bevolutions\b", "evolution", t)  # "XY Evolutions" vs. "XY Evolution" - manche Shops lassen das "s" weg
    t = re.sub(r"\bfirst\b", "erste", t)  # DE/EN Synonym (z.B. "First Partner"="Erste Partner")
    t = re.sub(r"\bseries?\b", "serie", t)  # DE/EN Synonym (Series/Serie)
    t = re.sub(r"\bpartners\b", "partner", t)  # First Partners/Erste Partner - Plural uneinheitlich
    t = re.sub(r"\bfiguren\b", "figure", t)  # DE/EN Synonym (Figuren/Figure)
    t = re.sub(r"\btins\b", "tin", t)  # Plural uneinheitlich verwendet
    t = re.sub(r"\bparadox\s*clash\b", "", t)  # keine offizielle Set-Bezeichnung, nur Beiwerk bei manchen Shops
    t = re.sub(r"\btournament\s*(kollektion|collection)\b", "turnierkollektion", t)  # DE/EN Synonym
    # Pokemon-Namen (EN) auf die deutsche Schreibweise normalisieren, damit
    # sie als EIN gemeinsames, ganz normales Token zaehlen (siehe
    # POKEMON_NAME_NORMALIZE oben - bewusst KEIN automatischer Bypass).
    for pattern, replacement in POKEMON_NAME_NORMALIZE:
        t = pattern.sub(replacement, t)
    t = re.sub(r"<br\s*/?>", " ", t)  # HTML-Reste (z.B. von God of Cards) entfernen
    t = re.sub(r"[^a-z0-9]+", " ", t)
    words = [w for w in t.split() if len(w) > 1 and w not in _TITLE_STOPWORDS]
    # "Mega Evolution"/"Mega-Entwicklung" ist bei EINIGEN Produkten der
    # tatsaechliche, EIGENSTAENDIGE Set-Name (nicht nur ein Praefix vor
    # einem spezifischeren Set wie "Mega-Entwicklung Wachsendes Chaos") -
    # z.B. "Mega Evolution Display" (EN) und "Mega-Entwicklung Booster
    # Display" (DE) OHNE weiteren Set-Namen sind dasselbe Produkt. Nur
    # WENN nach der ganzen Bereinigung sonst NICHTS Aussagekraeftiges mehr
    # uebrig ist, wird die Phrase als kuratierter Set-Tag nachgetragen -
    # sonst wuerde z.B. "Mega-Entwicklung Wachsendes Chaos" faelschlich
    # mit "Mega-Entwicklung Erhabene Helden" (anderes Set!) zusammengefuehrt.
    # nur "echte" Woerter zaehlen - kurze Zahlen (Boosteranzahl wie "36")
    # sollen nicht verhindern, dass "Mega Evolution"/"Mega-Entwicklung" als
    # eigenstaendiger Set-Name erkannt wird (siehe unten).
    _non_trivial_words = [
        w for w in words
        if not (w.isdigit() and len(w) <= 2)
        and not re.match(r"^\d{1,3}er$", w)
    ]
    _has_other_cset_tag = any(tag.startswith("cset") for tag in canonical_tags)
    if had_mega_evolution_phrase and not _non_trivial_words and not _has_other_cset_tag:
        canonical_tags.add("csetmegaevolution")
    return set(words) | canonical_tags


def image_tokens(image_url):
    """Extrahiert Schlagwoerter aus dem Bild-Dateinamen (falls vorhanden) -
    Shops nutzen fuer offizielle Produktbilder oft aehnliche/identische
    Dateinamen, das ist ein zusaetzliches Signal fuer 'gleiches Produkt'."""
    if not image_url:
        return set()
    path = image_url.split("?")[0]
    name = path.rsplit("/", 1)[-1]
    name = re.sub(r"\.(jpe?g|png|webp|gif)$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[^a-z0-9]+", " ", name.lower())
    return {w for w in name.split() if len(w) > 2}


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _containment(a, b):
    """Anteil der KLEINEREN Token-Menge, der in der groesseren enthalten
    ist. Wichtig, weil nach der starken Stopwort-Bereinigung oft nur noch
    1-2 Kern-Woerter (der eigentliche Setname) uebrig bleiben - ein Shop,
    der zusaetzlich eine Set-Nummer wie "KP09" oder die Boosterzahl "36"
    im Titel hat, soll trotzdem als gleiches Produkt erkannt werden, wenn
    der Kern-Setname vollstaendig uebereinstimmt."""
    if not a or not b:
        return 0.0
    smaller, larger = (a, b) if len(a) <= len(b) else (b, a)
    return len(smaller & larger) / len(smaller)


# Regionaler Standard fuer die Boosteranzahl eines Hauptset-Displays, falls
# ein Titel keine explizite Anzahl nennt - wird in product_similarity als
# Annahme genutzt, um "stille" Titel trotzdem korrekt gegen Titel mit
# einer EXPLIZIT abweichenden Anzahl abzugrenzen (z.B. 18er vs. 36er).
DEFAULT_BOOSTER_COUNT_BY_LANG = {
    "Deutsch": "36",
    "Englisch": "36",
}


def product_similarity(a, b):
    """Kombinierter Aehnlichkeits-Score (0-1) aus Titel-Schlagwoertern und
    - falls vorhanden - Bild-Dateinamen. Sprache und Produktart muessen
    schon vorher uebereinstimmen (separate Kriterien), hier geht es nur
    noch um die Feinunterscheidung innerhalb dieser Gruppe.

    WICHTIG: Shops verwenden fuer das gleiche offizielle Produkt oft voellig
    unterschiedliche eigene Bild-Dateinamen (kein einheitliches Format) -
    das Bild darf einen ohnehin starken Titel-Treffer daher nur zusaetzlich
    BOOSTEN (bei Grenzfaellen), aber niemals einen eindeutigen Titel-Match
    kaputt-mitteln, nur weil die Bildnamen zufaellig nicht uebereinstimmen.
    """
    # Manuelle Nutzer-Korrektur (per "🚫 Falsch verglichen?"-Button
    # gemeldet) hat IMMER Vorrang vor jeder automatischen Erkennung - wird
    # ganz am Anfang geprueft, noch vor allen anderen Regeln.
    if frozenset((a.get("url"), b.get("url"))) in get_blocked_pairs():
        return 0.0

    # Token-Bereinigung: entfernt reine Zustands-/Mengen-/Jahres-Marker
    # (condbware, volnumX, boostercountX, kurze Zahlen, Jahreszahlen,
    # generische Karten-Suffixe wie "ex"/"gx") - das sind Metadaten, keine
    # Produkt-Identitaet, und sollen daher STRENGE Jaccard-Pruefungen (bei
    # nur einem gemeinsamen Wort ODER sprachuebergreifenden Vergleichen)
    # nicht verfaelschen. Ein B-Ware-Marker oder ein Erscheinungsjahr macht
    # ein Produkt nicht automatisch "unaehnlicher". Frueh definiert, weil
    # sowohl die Sprachsperre weiter unten als auch das spaetere
    # Sicherheitsnetz das brauchen.
    _GENERIC_CARD_SUFFIXES = {"ex", "gx", "v", "vmax", "vstar", "ex1"}
    _NON_DISTINGUISHING_PREFIXES = ("cond", "boostercount", "year", "cset")
    # Japanische/chinesische Set-Codes (sv2a, s11, m2a, cs3a, cbb4c...) -
    # verschiedene Shops schreiben sie unterschiedlich konsequent dazu (der
    # eine "20er Display", der andere "SV2A Display" fuer das GLEICHE
    # Produkt) - sie duerfen die strenge Pruefung daher nicht verwaessern.
    _SET_CODE_PATTERN = re.compile(r"^(sv|sm|swsh|s|m|cs|csv|cbb|kp)\d{1,2}(\.\d+)?[a-z]?c?$")
    _COUNT_WORD_PATTERN = re.compile(r"^\d{1,3}er$")  # "20er", "36er" - deutsche Mengenangabe

    def _meaningful(tokens):
        return {
            w for w in tokens
            if not (w.isdigit() and (len(w) <= 2 or 2015 <= int(w) <= 2035))
            and w not in _GENERIC_CARD_SUFFIXES
            and not w.startswith(_NON_DISTINGUISHING_PREFIXES)
            and not _SET_CODE_PATTERN.match(w)
            and not _COUNT_WORD_PATTERN.match(w)
        }

    # Harte Sperre: Zustand (B-Ware/gebraucht) und "zufaellige Auswahl" vs.
    # feste Variante sind NIE das gleiche Produkt, selbst wenn sonst alles
    # uebereinstimmt. Das muss VOR jeder Jaccard/Containment-Berechnung
    # geprueft werden, weil sonst ein Artikel mit mehr Tokens (z.B. inkl.
    # "condbware") den Artikel OHNE dieses Merkmal per Containment trotzdem
    # "enthalten" wuerde und faelschlich zusammengefuehrt wird.
    # B-Ware/gebraucht sperrt NICHT mehr hart - wird stattdessen als Badge
    # an der jeweiligen Zeile angezeigt (siehe entry_condition_badge), damit
    # man B-Ware/Neu direkt im Preisvergleich sieht statt es zu verstecken.
    # Zufaellige Auswahl und "Mega"-Variante bleiben harte Sperren, weil das
    # tatsaechlich ein anderes Produkt ist (nicht nur ein Zustand).
    # Fruehzeitig berechnen (wird unten mehrfach gebraucht): ein
    # gemeinsamer kuratierter Set-Tag ist ein so starkes Signal, dass er
    # sogar die "Mega"-Asymmetrie-Sperre aushebeln darf (z.B. "Nihil Zero"
    # ohne "Mega" im Namen vs. "MEGA Munix Zero (M3)" mit - beide meinen
    # dasselbe Set, manche Shops lassen "Mega" im Titel einfach weg).
    # "condrandom" und "modcenteretb" bleiben davon UNBERUEHRT - eine
    # zufaellige Auswahl oder eine Pokemon-Center-Sondervariante ist immer
    # ein anderes physisches Produkt, unabhaengig vom Set-Namen.
    _shared_canonical_early = {t for t in (a["_tokens"] & b["_tokens"]) if t.startswith("cset")}
    for cond_tag in ("condrandom", "modmega", "modcenteretb"):
        if cond_tag == "modmega" and _shared_canonical_early:
            continue
        if (cond_tag in a["_tokens"]) != (cond_tag in b["_tokens"]):
            return 0.0

    # "Vol. 1" vs. "Vol. 4" etc. - wenn BEIDE eine Volume-Nummer haben und
    # diese unterschiedlich ist, ist es garantiert ein anderes Produkt
    # (z.B. "Gem Pack Vol. 1" bis "Vol. 5" teilen sich fast alle Woerter).
    vol_a = {t for t in a["_tokens"] if t.startswith("volnum")}
    vol_b = {t for t in b["_tokens"] if t.startswith("volnum")}
    if vol_a and vol_b and vol_a != vol_b:
        return 0.0

    # Jahreszahl: nur sperren, wenn BEIDE Seiten explizit ein Jahr nennen
    # UND es unterschiedlich ist (z.B. "Collectors Chest 2023" vs. "...
    # 2024" - jaehrliches Sondermerch mit unterschiedlichem Design pro
    # Jahr). Nennt nur eine Seite ein Jahr, wird NICHT gesperrt (viele
    # Set-Produkte nennen ein Erscheinungsjahr rein beschreibend, ohne dass
    # es eine andere Version bedeutet).
    year_a = {t for t in a["_tokens"] if t.startswith("year")}
    year_b = {t for t in b["_tokens"] if t.startswith("year")}
    if year_a and year_b and year_a != year_b:
        return 0.0

    # Boosteranzahl (18er vs. 36er Display etc.) - MUSS auch eine kuratierte
    # Set-Uebersetzung (z.B. Darkness Ablaze = Nacht in Flammen) aushebeln
    # koennen, sonst wird ein 18er-Display faelschlich mit einem 36er-
    # Display desselben Sets zusammengefuehrt, nur weil die Set-Namen als
    # gleich erkannt wurden. Nennt eine Seite KEINE Anzahl, wird der
    # REGIONALE STANDARD angenommen (DE/EN Hauptsets ueblicherweise 36,
    # JP/CN ueblicherweise 30) statt die Pruefung einfach zu ignorieren -
    # das faengt z.B. "Darkness Ablaze 18 Booster (EN)" vs. "Nacht in
    # Flammen [keine Angabe -> angenommen 36] (DE)" korrekt als Konflikt ab,
    # laesst aber "Mask of Change [keine Angabe -> angenommen 30] (JP)" vs.
    # "... 30 Booster Packs (JP)" weiterhin zusammen (30 == 30).
    def _effective_count(entry):
        explicit = {t for t in entry["_tokens"] if t.startswith("boostercount")}
        if explicit:
            return explicit
        default = DEFAULT_BOOSTER_COUNT_BY_LANG.get(entry.get("language"))
        return {f"boostercount{default}"} if default else set()

    count_a = _effective_count(a)
    count_b = _effective_count(b)
    if count_a and count_b and count_a != count_b:
        return 0.0

    pc_a = {t for t in a["_tokens"] if t.startswith("packcount")}
    pc_b = {t for t in b["_tokens"] if t.startswith("packcount")}
    if pc_a and pc_b and pc_a != pc_b:
        return 0.0

    tier_a = {t for t in a["_tokens"] if t.startswith("tier")}
    tier_b = {t for t in b["_tokens"] if t.startswith("tier")}
    if tier_a and tier_b and tier_a != tier_b:
        return 0.0

    # Ein gemeinsamer "canonical" Set-Tag (siehe SET_NAME_ALIASES) ist ein
    # sehr starkes, kuratiertes Signal - z.B. "Journey Together" (EN) und
    # "Reisegefährten" (DE) sind DAS GLEICHE Set, teilen sich aber sonst
    # kein einziges Wort. Ein solcher Treffer zaehlt daher als sicherer
    # Match, auch wenn drumherum wegen der Sprachdifferenz viel "Rauschen"
    # (die jeweils andersprachigen Woerter) uebrig bleibt.
    #
    # AUSNAHME von der Ausnahme: Chinesische Produkte werden NIEMALS mit
    # einer anderen Sprache zusammengefuehrt, auch nicht ueber einen
    # kuratierten Set-Tag - chinesische Ausgaben sind eigenstaendige
    # Produkte (oft von komplett anderen Herstellern/Vertrieben, z.B.
    # "Nine Colors Gathering" ist trotz englischer Referenz "(Fusion
    # Strike)" im Titel ein eigenes chinesisches Produkt, kein Fusionsangriff-
    # Aequivalent).
    lang_a_pre = a.get("language", "Unbekannt")
    lang_b_pre = b.get("language", "Unbekannt")
    if "Chinesisch" in (lang_a_pre, lang_b_pre) and lang_a_pre != lang_b_pre:
        return 0.0

    shared_canonical = _shared_canonical_early
    if shared_canonical:
        # AUSNAHME: der csetbaseset-Tag (Karmesin&Purpur/Scarlet&Violet
        # Basisset) wird ueber verschiedene THEMATISCHE ETB-Varianten
        # hinweg vergeben (z.B. "KP01 ETB Koraidon" UND "KP01 ETB
        # Miraidon" matchen beide das Muster) - das sind aber
        # UNTERSCHIEDLICHE physische Produkte (anderes Box-Artwork).
        # Nennt jede Seite ein ANDERES der beiden Basis-Legendaries
        # explizit, darf der gemeinsame Tag das nicht ueberstimmen.
        _base_legendaries = {"koraidon", "miraidon"}
        leg_a = a["_tokens"] & _base_legendaries
        leg_b = b["_tokens"] & _base_legendaries
        if leg_a and leg_b and leg_a != leg_b:
            return 0.0
        # AUSNAHME 1b: der csetbaseset-Tag darf Japanisch NICHT mit
        # Deutsch/Englisch mischen - die japanische Ausgabe des Basissets
        # heisst "Scarlet ex"/"Violet ex" (getrennte Einzelprodukte) und
        # ist ein eigenstaendiges, anderes physisches Produkt als das
        # westliche kombinierte "Scarlet & Violet"-Basisset.
        if "csetbaseset" in shared_canonical:
            _lang_a_bs = a.get("language", "Unbekannt")
            _lang_b_bs = b.get("language", "Unbekannt")
            if "Japanisch" in (_lang_a_bs, _lang_b_bs) and _lang_a_bs != _lang_b_bs:
                return 0.0
            # "Scarlet ex" und "Violet ex" sind in Japan die ZWEI
            # getrennten Einzelausgaben (wie Koraidon/Miraidon im Westen) -
            # unterschiedliche physische Produkte, nicht austauschbar.
            _st_a = {t for t in a["_tokens"] if t.startswith("starter")}
            _st_b = {t for t in b["_tokens"] if t.startswith("starter")}
            if _st_a and _st_b and _st_a != _st_b:
                return 0.0
        # AUSNAHME 2: unterschiedliche explizite Boosteranzahl (z.B. "18er"
        # vs. "36er" Display) ist IMMER ein anderes Produkt, auch wenn
        # beide sonst als dasselbe Basisset erkannt wurden.
        bc_a = {t for t in a["_tokens"] if t.startswith("boostercount")}
        bc_b = {t for t in b["_tokens"] if t.startswith("boostercount")}
        if bc_a and bc_b and bc_a != bc_b:
            return 0.0
        _tier_a = {t for t in a["_tokens"] if t.startswith("tier")}
        _tier_b = {t for t in b["_tokens"] if t.startswith("tier")}
        if _tier_a and _tier_b and _tier_a != _tier_b:
            return 0.0
        # AUSNAHME 3: "Surprise Box"/"Mystery Box" (zufaellige Auswahl,
        # anderes physisches Produkt als eine feste ETB/Kollektion vom
        # gleichen Set) darf ebenfalls nicht durch den gemeinsamen Tag
        # ueberstimmt werden.
        _surprise_words = {"surprise", "mystery", "ueberraschung", "ueberraschungsbox"}
        surprise_a = bool(a["_tokens"] & _surprise_words)
        surprise_b = bool(b["_tokens"] & _surprise_words)
        if surprise_a != surprise_b:
            return 0.0
        # AUSNAHME 4: Zubehoer-Beutel/-Pouch (reines Zubehoer, keine
        # eigentliche Kollektion mit Karten vom gleichen Set) auf nur EINER
        # Seite darf den gemeinsamen Set-Tag ebenfalls nicht ueberstimmen.
        _accessory_words = {"beutel", "pouch", "accessory"}
        acc_a = bool(a["_tokens"] & _accessory_words)
        acc_b = bool(b["_tokens"] & _accessory_words)
        if acc_a != acc_b:
            return 0.0
        # ALLGEMEINE AUSNAHME (ersetzt viele Einzelfall-Regeln): haben
        # BEIDE Seiten noch eigene, nicht geteilte Woerter UEBER den
        # gemeinsamen Tag hinaus (z.B. "Impergator" vs. "Flambirex" bei
        # zwei verschiedenen "Ascended Heroes"-Kollektionen), ist das ein
        # Hinweis auf unterschiedliche THEMATISCHE VARIANTEN desselben
        # Sets - dann NICHT automatisch 0.95 zurueckgeben, sondern normal
        # anhand des Wortueberlapps weiterrechnen (faellt durch bis zur
        # regulaeren Jaccard/Containment-Pruefung unten).
        _meaningful_a_early = (a["_tokens"] - shared_canonical) - {"mega", "modmega", "csetmegaevolution", "sv", "kp"}
        _meaningful_b_early = (b["_tokens"] - shared_canonical) - {"mega", "modmega", "csetmegaevolution", "sv", "kp"}
        _light_exclude = ("cond", "boostercount", "year")
        _meaningful_a_early = {
            w for w in _meaningful_a_early
            if not (w.isdigit() and len(w) <= 2)
            and not w.startswith(_light_exclude)
            and not _COUNT_WORD_PATTERN.match(w)
            and not _SET_CODE_PATTERN.match(w)
        }
        _meaningful_b_early = {
            w for w in _meaningful_b_early
            if not (w.isdigit() and len(w) <= 2)
            and not w.startswith(_light_exclude)
            and not _COUNT_WORD_PATTERN.match(w)
            and not _SET_CODE_PATTERN.match(w)
        }
        _unique_a = _meaningful_a_early - _meaningful_b_early
        _unique_b = _meaningful_b_early - _meaningful_a_early
        _has_other_cset_ref = any(w.startswith("cset") for w in (_unique_a | _unique_b))
        if (_unique_a and _unique_b) or _has_other_cset_ref:
            pass  # nicht automatisch zurueckgeben - unten normal weiterpruefen
        else:
            return 0.95

    # Harte Sperre: OHNE einen kuratierten Set-Tag-Treffer (oben) duerfen
    # unterschiedliche Sprachen NIEMALS als gleiches Produkt gelten -
    # normale Wort-Aehnlichkeit ist dafuer nicht zuverlaessig genug (z.B.
    # generische Reihen-Namen wie "Collect The First Partner" tauchen bei
    # voellig unterschiedlichen Pokemon/Sprachen auf und wuerden sonst
    # faelschlich zusammengefuehrt werden). Welche Sprache ein Eintrag hat,
    # wird stattdessen an der Karte als Flagge angezeigt.
    #
    # AUSNAHME: stimmen nach Wort-Normalisierung (inkl. Pokemon-Namen)
    # praktisch ALLE Woerter ueberein (nicht nur eines zufaellig), ist das
    # ein sehr starkes Signal fuer "gleiches Produkt, nur andere Sprache" -
    # z.B. "Premium Collection Ogerpon ex" (EN) und "Premium-Kollektion
    # Ogerpon ex" (DE) reduzieren sich beide auf {ogerpon, ex}. Das ist
    # etwas anderes als ein einzelnes zufaelliges Treffer-Wort in einem
    # ansonsten sehr unterschiedlichen Titelpaar (siehe Jaccard-Pruefung
    # weiter unten) - hier MUSS praktisch der GESAMTE Inhalt beider Seiten
    # uebereinstimmen (Jaccard >= 0.9), nicht nur enthalten sein.
    lang_a = a.get("language", "Unbekannt")
    lang_b = b.get("language", "Unbekannt")
    if lang_a != lang_b and a["_tokens"] != b["_tokens"]:
        cross_lang_ok = _jaccard(_meaningful(a["_tokens"]), _meaningful(b["_tokens"])) >= 0.9
        # Weitere Ausnahme: beide Seiten sind explizit eine "Mega [Pokemon]"-
        # Variante (modmega-Tag) UND nennen das GLEICHE (normalisierte)
        # Pokemon - z.B. "Mega Glurak X" (DE) und "Mega Charizard ex" (EN)
        # sind das gleiche Produkt, auch wenn der Shop unterschiedliche
        # Zusatz-Woerter (Set-Name, Suffix X/ex) verwendet. modmega+Name
        # ist bei "Mega"-Sonderprodukten spezifisch genug (im Gegensatz zu
        # einem Pokemon-Namen allein, siehe POKEMON_NAME_NORMALIZE oben).
        if not cross_lang_ok and "modmega" in a["_tokens"] and "modmega" in b["_tokens"]:
            _generic = {"ex", "gx", "v", "vmax", "vstar", "ex1"}
            pokemon_a = a["_tokens"] - {"mega", "modmega"} - _generic
            pokemon_b = b["_tokens"] - {"mega", "modmega"} - _generic
            # nur die eigentlichen Pokemon-Namens-Token vergleichen (nicht
            # Fuellwoerter wie Set-Namen) - daher Containment statt Jaccard
            if pokemon_a and pokemon_b and (pokemon_a & pokemon_b):
                cross_lang_ok = True
        if not cross_lang_ok:
            return 0.0

    # WICHTIG: Containment (= "ist die kleinere Wortmenge fast komplett in
    # der groesseren enthalten?") ist nur dann ein sinnvolles Signal, wenn
    # eine Seite wirklich nur eine kuerzere/knappere Beschreibung derselben
    # Sache ist. Haben dagegen BEIDE Seiten eigene, nicht geteilte Woerter
    # (z.B. "Zacian" auf der einen, "Koraidon" auf der anderen Seite -
    # unterschiedliche Pokemon im selben Tin-Sortiment "Schlagkraeftige
    # Legenden"), darf Containment das nicht schoenrechnen - dann zaehlt
    # nur die strengere Jaccard-Berechnung (die den nicht geteilten Rest
    # auf BEIDEN Seiten mit einbezieht).
    _meaningful_a = _meaningful(a["_tokens"])
    _meaningful_b = _meaningful(b["_tokens"])
    # Ausnahme: haben BEIDE Seiten dieselbe Volume-Nummer (z.B. "Vol. 4" auf
    # beiden Seiten, siehe vol_a/vol_b oben), ist das ein verlaessliches
    # Signal fuer "gleiches nummeriertes Produkt", selbst wenn daneben noch
    # unterschiedliche Produktcodes stehen (z.B. ein Shop schreibt "CBB4C",
    # ein anderer tippt sich zu "CBB3C" - beide meinen aber "Vol. 4").
    _both_have_unique_content = (
        bool(_meaningful_a - _meaningful_b) and bool(_meaningful_b - _meaningful_a)
        and not (vol_a and vol_b and vol_a == vol_b)
    )
    if _both_have_unique_content:
        title_sim = _jaccard(a["_tokens"], b["_tokens"])
    else:
        title_sim = max(
            _jaccard(a["_tokens"], b["_tokens"]),
            _containment(a["_tokens"], b["_tokens"]),
        )
    # Sicherheitsnetz: nach der starken Stopwort-Bereinigung kann es
    # vorkommen, dass von einem Titel nur noch eine reine Zahl (z.B. die
    # Boosteranzahl "36") als Token uebrig bleibt. Eine Uebereinstimmung
    # NUR auf Basis einer kurzen Verpackungs-Zahl (36, 18, 20, 30, 10, 6...)
    # ist bedeutungslos (fast jedes Display hat "36") und darf niemals
    # allein einen Match ausloesen. WICHTIG: das gilt NICHT fuer laengere,
    # spezifische Zahlen wie "151" - das ist ein offizieller, eigenstaendiger
    # Set-Name (Pokemon 151), keine Verpackungsgroesse, und zaehlt daher
    # als vollwertiges Merkmal. Das Gleiche gilt fuer generische Pokemon-
    # Karten-Suffixe wie "ex", "gx", "v", "vmax", "vstar" - die stehen auf
    # FAST JEDEM Produkt (jede moderne Karte ist "ex" o.ae.) und sind daher
    # GENAUSO bedeutungslos wie eine kurze Verpackungszahl, wenn sie das
    # EINZIGE gemeinsame Wort sind. Ist es nur EIN gemeinsames (echtes)
    # Wort, ist das Risiko eines Zufallstreffers bei sehr kurzen/
    # generischen Titeln trotzdem hoch - dann wird ein sehr hoher Score
    # verlangt (praktisch vollstaendige Uebereinstimmung), nicht nur die
    # normale Schwelle.
    shared_words = _meaningful(a["_tokens"] & b["_tokens"])
    # Ausnahme 1: sind die rohen Token-Mengen komplett IDENTISCH (z.B. beide
    # nur {ex, 30er, boostercount30}), ist das der staerkste denkbare
    # Beleg fuer "gleiches Produkt" - auch wenn nach der Bereinigung
    # (Boosteranzahl, generische Suffixe...) rechnerisch "nichts
    # Bedeutungsvolles" uebrig bleibt.
    # Ausnahme 2: teilen sich beide Seiten einen kuratierten Set-Tag (siehe
    # SET_NAME_ALIASES), ist das ebenfalls ein starker Beleg - auch wenn
    # dieser Tag selbst aus der "bedeutungsvoll"-Zaehlung herausgefiltert
    # wird (cset-Tags zaehlen bewusst nicht als "Wort" fuer diese Zaehlung,
    # sollen die Erkennung aber trotzdem nicht komplett blockieren).
    if not shared_words and a["_tokens"] != b["_tokens"] and not shared_canonical:
        return 0.0
    img_sim = _jaccard(a["_img_tokens"], b["_img_tokens"])
    final_score = max(title_sim, title_sim * 0.7 + img_sim * 0.3) if img_sim > 0 else title_sim
    if len(shared_words) == 1:
        # WICHTIG: bei nur einem gemeinsamen Wort NICHT das Containment
        # verwenden, um zu pruefen ob der Treffer "stark genug" ist -
        # Containment eines einzelnen Wortes ist IMMER 1.0 (das eine Wort
        # ist ja trivialerweise in der anderen Menge enthalten), das macht
        # die Pruefung wirkungslos. Z.B. "Glurak" (1 Token uebrig) vs.
        # "Glurak Feuersturm Box 2016 ex" (5 Token) haette per Containment
        # 1.0 ergeben, obwohl komplett unterschiedliche Produkte. Der
        # JACCARD-Wert (Verhaeltnis zur GESAMTEN Wortmenge beider Seiten)
        # deckt das zuverlaessig auf, da er den grossen "Rest" der
        # laengeren Seite mit einbezieht. Verwendet wird dabei die
        # BEREINIGTE Wortmenge (siehe _meaningful oben), damit z.B. ein
        # B-Ware-Marker oder eine Jahreszahl nicht faelschlich als
        # "zusaetzlicher Unterschied" gewertet wird.
        jaccard_only = _jaccard(_meaningful(a["_tokens"]), _meaningful(b["_tokens"]))
        if jaccard_only < 0.9:
            return 0.0
        # Die Pruefung ist bestanden (jaccard_only >= 0.9) - der
        # zurueckgegebene Score muss das auch widerspiegeln. Der rohe
        # title_sim kann trotzdem niedrig sein (z.B. durch Set-Codes wie
        # "SV2A" auf nur einer Seite, die oben absichtlich ignoriert
        # wurden), daher hier den hohen bereinigten Wert verwenden.
        return max(final_score, jaccard_only)
    return final_score


SIMILARITY_THRESHOLD = 0.6


# Reihenfolge, in der Sprachen bei Alarmen gruppiert/angezeigt werden.
LANGUAGE_ORDER = ["Deutsch", "Englisch", "Japanisch", "Chinesisch", "Koreanisch", "Unbekannt"]

# Index, ab dem eine Sprache als "niedrige Prioritaet" gilt und in allen
# Listen (Angebote, Vorbestellungen, Alle Produkte) ganz nach UNTEN
# sortiert wird - Deutsch/Englisch/Japanisch haben Vorrang, Chinesisch
# (und alles danach) kommt immer zuletzt, egal welche Kategorie.
_LOW_PRIO_LANG_INDEX = LANGUAGE_ORDER.index("Chinesisch")


def _language_priority(lang):
    """Sortier-Index einer Sprache gemaess LANGUAGE_ORDER (unbekannte
    Werte ganz hinten)."""
    return LANGUAGE_ORDER.index(lang) if lang in LANGUAGE_ORDER else len(LANGUAGE_ORDER)


def _is_low_prio_group(entries):
    """True, wenn ALLE Eintraege einer Gruppe eine Niedrig-Prioritaets-
    Sprache (Chinesisch oder spaeter) haben - solche Gruppen wandern in
    jeder Liste ans Ende. Gemischte Gruppen (z.B. DE+CN-Vergleichskarte)
    behalten die Prioritaet ihrer besten Sprache."""
    return min(_language_priority(e.get("language", "Unbekannt")) for e in entries) >= _LOW_PRIO_LANG_INDEX

LANGUAGE_FLAGS = {
    "Deutsch": "🇩🇪",
    "Englisch": "🇬🇧",
    "Japanisch": "🇯🇵",
    "Chinesisch": "🇨🇳",
    "Koreanisch": "🇰🇷",
    "Unbekannt": "❓",
}

# Kurzcode + CSS-Klasse fuer farbige Sprach-Badges (zuverlaessiger als
# Flaggen-Emoji, die z.B. unter Windows oft nur als Text "DE"/"GB" ohne
# jede farbliche/visuelle Unterscheidung angezeigt werden).
LANGUAGE_BADGE = {
    "Deutsch": ("DE", "lang-de"),
    "Englisch": ("EN", "lang-en"),
    "Japanisch": ("JP", "lang-jp"),
    "Chinesisch": ("CN", "lang-cn"),
    "Koreanisch": ("KR", "lang-kr"),
    "Unbekannt": ("?", "lang-unbekannt"),
}


def lang_badge_html(esc_fn, language):
    code, css_class = LANGUAGE_BADGE.get(language, ("?", "lang-unbekannt"))
    return f'<span class="lang-badge {css_class}">{esc_fn(code)}</span>'


CASE_TITLE_PATTERN = re.compile(r"\bsealed\s*case\b|\bcase\b", re.IGNORECASE)
BWARE_TITLE_PATTERN = re.compile(r"\bb-?ware\b|\bgebraucht\b|\bused\b", re.IGNORECASE)
INFO_TITLE_PATTERN = re.compile(r"info\s*beachten", re.IGNORECASE)


def entry_condition_badges(esc_fn, title):
    """Kleine Zusatz-Badges fuer Besonderheiten, die man direkt an der
    Zeile/Karte erkennen soll (nicht erst im Titel-Text lesen muss):
    'CASE' = ganzes Case mit mehreren Displays (viel teurer als 1 Display!),
    'B-WARE' = B-Ware/gebraucht statt neu, 'INFO' = Shop weist auf eine
    Besonderheit hin, die man vor dem Kauf beachten sollte."""
    badges = []
    if CASE_TITLE_PATTERN.search(title):
        badges.append('<span class="cond-badge cond-case" title="Ganzes Case (mehrere Displays), nicht nur 1 Display!">📦 CASE</span>')
    if BWARE_TITLE_PATTERN.search(title):
        badges.append('<span class="cond-badge cond-bware" title="B-Ware/gebraucht, nicht neu">B-WARE</span>')
    if INFO_TITLE_PATTERN.search(title):
        badges.append('<span class="cond-badge cond-info" title="Shop weist im Titel auf eine Besonderheit hin - vor dem Kauf pruefen">ℹ️ INFO</span>')
    return "".join(badges)


_POKEMON_WORD_PATTERN = re.compile(r"^\s*pok[ée]mon\s*[-–:]?\s*", re.IGNORECASE)
_LEADING_PUNCT_PATTERN = re.compile(r"^[\s\-–:]+")


def short_title_html(title):
    """Entfernt das fuehrende Wort 'Pokemon'/'Pokémon' (steht in JEDEM
    Titel und traegt hier keine Information bei) fuer eine kompaktere,
    besser lesbare Darstellung in der Alarm-Liste."""
    t = _POKEMON_WORD_PATTERN.sub("", title)
    t = _LEADING_PUNCT_PATTERN.sub("", t)
    return t or title


def slugify(text):
    """Erzeugt eine URL-/ID-sichere Kurzform (fuer Anker-Links in der
    Schnellnavigation)."""
    t = text.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t or "x"

LANGUAGE_PATTERNS = [
    # Koreanisch MUSS als Erstes geprueft werden - sonst wuerde ein
    # japanischer/chinesischer Set-Code-Treffer (z.B. "(sv2a)", "(s6a)")
    # ein explizites "(KOR)" im selben Titel ueberstimmen (Korea nutzt oft
    # dieselben Set-Codes wie Japan).
    ("Koreanisch", re.compile(r"\bkoreanisch\b|\bkorean\b|\(kr\)|- kr\b|\bkor\b|\bcor\b", re.IGNORECASE)),
    ("Deutsch", re.compile(r"\bdeutsch\b|\(de\)|\bger\b|- de\b|\bgermany\b|\bde\b", re.IGNORECASE)),
    ("Englisch", re.compile(r"\benglisch\b|\benglish\b|\(en\)|- en\b|\beng\b|\bengl\.?\b|\ben\b", re.IGNORECASE)),
    ("Japanisch", re.compile(
        r"\bjapanisch\b|\bjapanese\b|\(jp\)|- jp\b|\bjap\b|\bjpn\b|\bjp\b|"
        r"\((s|sm|sv|m)\d{1,2}[a-z]?\)|"  # japanische Set-Codes in Klammern: (s11), (sm8b), (m2a)
        # "25th Anniversary Gold(en) Box" ist ausschliesslich in Japan
        # erschienen (nie auf DE/EN uebersetzt) - auch ohne expliziten
        # Sprach-Marker im Titel.
        r"25th\s*anniversary.{0,20}gold(en)?\s*box",
        re.IGNORECASE)),
    ("Chinesisch", re.compile(
        r"\bchinesisch\b|\bchinese\b|\(cn\)|\(chn\)|\(ch\)|s-ch\b|- cn\b|\bchn\b|\bcn\b|"
        r"\bcs\d+(\.\d+)?[a-z]?c?\b|\bcsm\d+[a-z]?c?\b|\bcbb\d+c?\b|"  # chinesische Set-Codes: CS3a, CS4aC, CS4.5C, CBB4C, CSM1aC
        # Diese beiden Produktlinien sind ausschliesslich in China
        # erschienen (nie auf DE/EN uebersetzt) - auch ohne expliziten
        # Sprach-Marker im Titel.
        r"30th\s*anniversary\s*partner\s*special\s*illustration|"
        r"collect\s*151.{0,40}first\s*partner",
        re.IGNORECASE)),
]
# Reihenfolge der Pruefung: spezifischere/eindeutigere Sprachen zuerst,
# damit z.B. "englisch" nicht faelschlich vor "koreanisch" geprueft wird
# und kurze, mehrdeutige Codes (DE/EN/JP) erst NACH den langen, eindeutigen
# Wortformen (deutsch/english/...) an die Reihe kommen.
_LANG_CHECK_ORDER = ["Deutsch", "Englisch", "Japanisch", "Chinesisch", "Koreanisch"]


# Fallback-Erkennung, falls der Titel KEINE explizite Sprachkennzeichnung
# hat (kein "(DE)", "Deutsch" etc.) - dann wird versucht, die Sprache des
# Titeltexts selbst zu erkennen (Umlaute, typische deutsche Woerter/Endungen).
_GERMAN_HINT_PATTERN = re.compile(
    r"[äöüß]|"
    r"\b\d{1,3}er\b|"  # "36er", "18er" - typisch deutsche Mengenangabe
    r"\bkollektion\b|\bkampfdeck\b|\bliga\b|\beinzelbooster\b|"
    r"\bzuf[äa]llige?\b|\bauswahl\b|\bgebraucht\b|\bverschiedene\b|"
    r"\bordner\b|\bschl[üu]sselanh[äa]nger\b|\brucksack\b|\bteile\b|\bsammelkoffer\b|\bmega-entwicklung\b|"
    r"\bpuzzle\b|\bfigur\b|\bfiguren\b|\bh[üu]lle[n]?\b|\btrinkflasche\b|"
    r"\btasse[n]?\b|\bspielkarten\b|\bsammelkarten\b|\bgesch[äa]ftigt\b|"
    r"\bneu\b|\bset\b.*\bkarten\b|\bkarten\b.*\bset\b|"
    r"\bkaufen\b|\bherbst\b|\bwinter\b|\bfr[üu]hling\b|"
    r"\bschicksale\b|\beisenhaupt\b|\bsonne\b.*\bmond\b|\bschwert\b.*\bschild\b",
    re.IGNORECASE,
)


def detect_language(title):
    """Erkennt die Sprache/Region eines Produkts anhand typischer
    Kennzeichnungen im Titel (z.B. '(DE)', 'Deutsch', 'Chinesisch' ...).
    Ist keine explizite Kennzeichnung vorhanden, gibt der erkannte SET-NAME
    den Ausschlag (z.B. "Journey Together" -> Englisch, auch wenn der Shop
    die Boosteranzahl auf deutsche Art "36er" schreibt - das darf ein
    eindeutig englischer Set-Name-Treffer NICHT ueberstimmen). Erst danach
    werden generische deutsche Hinweiswoerter geprueft. Bleibt auch das
    ergebnislos, wird als letzter Fallback 'Englisch' angenommen."""
    for code, pattern in LANGUAGE_PATTERNS:
        if pattern.search(title):
            return code
    # Set-Name hat Vorrang vor generischen Hinweisen (z.B. "36er"), weil
    # Shops oft die deutsche Zaehlweise ("36er") auch bei eigentlich
    # englischsprachigen Set-Namen verwenden.
    en_hit = any(p.search(title) for p in SET_NAME_EN_PATTERNS)
    de_hit = any(p.search(title) for p in SET_NAME_DE_PATTERNS)
    if en_hit and not de_hit:
        return "Englisch"
    if de_hit and not en_hit:
        return "Deutsch"
    if _GERMAN_HINT_PATTERN.search(title):
        return "Deutsch"
    # "Gem Pack" ist eine ausschliesslich chinesische Produktlinie - manche
    # Shops (z.B. Pokeminati) schreiben aber keine explizite Sprache dazu.
    # Ohne diesen Hinweis wuerden solche Angebote faelschlich auf den
    # generischen "Englisch"-Fallback zurueckfallen und dadurch nie mit den
    # explizit als Chinesisch markierten Angeboten desselben Produkts
    # zusammengefuehrt werden.
    if re.search(r"\bgem\s*pack\b", title, re.IGNORECASE):
        return "Chinesisch"
    if title and title.strip():
        return "Englisch"
    return "Unbekannt"


# Reihenfolge wichtig: spezifischere Begriffe (z.B. "Mini Tin", "Elite
# Trainer Box") muessen VOR den allgemeineren (z.B. "Tin", "Box") geprueft
# werden, sonst wird z.B. eine Mini Tin faelschlich als normale "Tin" erkannt.
# Feste Anzeige-Reihenfolge der Kategorien im "Alle Produkte"-Tab.
PRODUCT_TYPE_ORDER = [
    "Ultra-Premium-Kollektionen",
    "Booster Displays",
    "Elite Trainer Boxen",
    "Kollektionen",
    "Booster Bundles",
    "Sammelkoffer / Collector's Chest",
    "Mini Tins",
    "Tins",
    "Mini Portfolios",
    "Graded Cards & Sammlerstücke",
    "Blister / Checklane Blister",
    "Booster / Sleeved Booster / Einzelbooster",
    "Sonstiges",
]

# Reihenfolge der PRUEFUNG (nicht Anzeige!): spezifischere Begriffe zuerst,
# damit z.B. "Elite Trainer Box" nicht faelschlich unter "Kollektion" faellt.
# HINWEIS: Decks, Trainerkits, Kalender, Zubehoer/Sleeves gibt es nicht mehr
# als Kategorie - diese Produkte werden komplett ausgeschlossen (siehe
# CATEGORY_EXCLUDE_PATTERN).
PRODUCT_TYPE_PATTERNS = [
    # "Schutz..." (Schutzhuelle, Schutz-Case etc.) ist reines Zubehoer zum
    # SCHUTZ eines Displays/einer Box, kein eigenstaendiges TCG-Produkt -
    # wird IMMER (Prioritaet vor allen anderen Kategorien) unter
    # "Sonstiges" einsortiert.
    ("Sonstiges", re.compile(r"\bschutz", re.IGNORECASE)),
    ("Elite Trainer Boxen", re.compile(
        r"elite[\s-]*trainer[\s-]*box|\betb\b|top[\s-]*trainer[\s-]*box|\bttb\b",
        re.IGNORECASE)),
    # "Mini Portfolio" enthaelt meist einen echten Booster (z.B. "Evolving
    # Skies Mini Portfolio - Inkl. 1 Booster") - deshalb eigene Kategorie,
    # NICHT wie generische Portfolios/Alben komplett ausschliessen.
    ("Mini Portfolios", re.compile(r"mini\s*portfolio|mini\s*portfilio", re.IGNORECASE)),
    # Mini Tins MUSS vor Tins geprueft werden (spezifischer)
    ("Mini Tins", re.compile(r"mini[\s-]*tins?", re.IGNORECASE)),
    # Sammelkoffer/Collector's Chest MUSS vor Tins geprueft werden - manche
    # Koffer heissen zusaetzlich "... Treasure Tin" im Titel, sind aber
    # trotzdem ein Koffer (Sammelkoffer-Bauform), kein normales Tin.
    ("Sammelkoffer / Collector's Chest", re.compile(r"sammelkoffer|\bkoffer\b|collector.?s?\s*chest", re.IGNORECASE)),
    ("Tins", re.compile(r"\btins?\b", re.IGNORECASE)),
    # Tech-Sticker-Sets werden physisch als Blister-Packung verkauft, auch
    # wenn "Kollektion" im Namen steht - muss VOR der generischen
    # Kollektion-Pruefung stehen.
    ("Blister / Checklane Blister", re.compile(r"tech\s*sticker", re.IGNORECASE)),
    ("Ultra-Premium-Kollektionen", re.compile(
        r"ultra[\s-]*premium[\s-]*kollektion|ultra[\s-]*premium[\s-]*collection|\bupc\b|"
        # Auch ohne "Kollektion/Collection" dahinter: "Ultra-Premium ... Box"
        # (z.B. "Ultra-Premium Terapagos Box") ist immer diese Produktstufe.
        r"ultra[\s-]*premium|"
        r"game[\s-]*classic[\s-]*box|"
        # Sonderfall: bei "Prismatische Entwicklungen"/"Prismatic Evolutions"
        # heisst die oberste Box-Stufe offiziell "Super Premium Kollektion"
        # statt "Ultra Premium" - NUR in Kombination mit diesem Set-Namen
        # gilt das als UPC-Aequivalent (nicht generisch, siehe "Glurak ex -
        # Super Premium Kollektion", das ist eine normale Kollektion).
        r"(prismatische\s*entwicklung(en)?|prismatic\s*evolutions?).{0,20}super[\s-]*premium|"
        r"super[\s-]*premium.{0,20}(prismatische\s*entwicklung(en)?|prismatic\s*evolutions?)",
        re.IGNORECASE)),
    ("Kollektionen", re.compile(
        r"collection|kollektion|premium\s*collection|"
        r"file\s*set|pin.?collection|special\s*set|sammlerset|"
        r"special\s*box|kampfbox|fallakte|"
        # "Gift Box" (v.a. chinesische Produktlinie, aber auch "Lunar New
        # Year Gift Box" etc.) ist immer eine Sammel-Kollektion - viele
        # Shops schreiben kein "Collection" dazu.
        r"gift[\s-]*box|giftbox|"
        # "Collector Box", "Showcase Box", "Surprise Box" - offizielle
        # Kollektions-Produktlinien ohne das Wort "Collection" im Titel.
        r"collector[\s-]*box|showcase[\s-]*box|surprise[\s-]*box|"
        # "[Pokemon-Name] ex/gx/vmax/vstar Box" - eine einzelne, auf ein
        # bestimmtes Pokemon zugeschnittene Sammelbox (Booster + Promo-
        # karte + Zubehoer). Bewusst NICHT bloss "box" allein (zu generisch,
        # wuerde sonst z.B. "Build & Battle Box" erfassen - die ist aber
        # bereits vorher ausgeschlossen). "V Box" (z.B. "Pikachu V Box",
        # "Boltund V Box") gehoert ebenfalls dazu.
        r"\b(ex|gx|v|vmax|vstar)[\s-]*box\b|"
        # "Pokemon Center [Stadt] Box" (ohne "Special") ist die gleiche
        # Produktlinie wie "... Special Box" - manche Shops lassen
        # "Special" im Titel einfach weg.
        r"pok[ée]mon\s*center\s+\w+\s+box\b", re.IGNORECASE)),
    # "Display Bundle" (mehrere Displays zusammen im Bundle-Preis) ist
    # trotz "Bundle" im Namen ein Display-Produkt, kein Booster Bundle
    # (das waeren einzelne Booster-Packs, kein Bundle von Displays) - muss
    # VOR der generischen Bundle-Pruefung stehen.
    ("Booster Displays", re.compile(r"display[\s-]*bundle", re.IGNORECASE)),
    # "Trick or Trade" (Halloween-BOOster-Paket) ist offiziell ein Booster
    # Bundle, auch wenn "Bundle" nicht immer im Titel steht.
    ("Booster Bundles", re.compile(r"trick\s*or\s*trade|bundle\b", re.IGNORECASE)),
    ("Booster Displays", re.compile(r"\bdisplay[s]?\b|booster\s*display|booster\s*box", re.IGNORECASE)),
    ("Blister / Checklane Blister", re.compile(r"blister|check[- ]?lane|checklane", re.IGNORECASE)),
    ("Booster / Sleeved Booster / Einzelbooster", re.compile(
        r"booster\s*pack|einzelbooster|jumbo\s*booster|\bbooster\b|"
        r"\bpacks?\b", re.IGNORECASE)),
    # KEIN "Sonderbox"-Catchall mehr - alles, was hier durchfaellt (z.B.
    # ein generisches "... ex Box (DE)" ohne erkennbaren spezifischeren
    # Typ), landet stattdessen ehrlich unter "Sonstiges" statt in einer
    # Sammel-Kategorie "Sonderbox" versteckt zu werden.
]



DISPLAY_36_PATTERN = re.compile(r"\b36.?er\b|36\s*booster|36\s*packs?\b|\(36\)", re.IGNORECASE)
DISPLAY_18_PATTERN = re.compile(r"\b18.?er\b|18\s*booster|18\s*packs?\b|\(18\)", re.IGNORECASE)
DISPLAY_20_PATTERN = re.compile(r"\b20.?er\b|20\s*booster|20\s*packs?\b|\(20\)", re.IGNORECASE)
DISPLAY_30_PATTERN = re.compile(r"\b30.?er\b|30\s*booster|30\s*packs?\b|\(30\)", re.IGNORECASE)


_BARE_CHINESE_CODE_PATTERN = re.compile(
    r"\((cs|csv|csm|cbb)\d+(\.\d+)?[a-z]?c?\)\s*(\((cn|chn|chinesisch|chinese)\))?\s*$",
    re.IGNORECASE,
)


def detect_product_type(title):
    """Erkennt den Produkttyp (Display, ETB, Mini Tin, ...) anhand
    typischer Begriffe im Titel. Gibt 'Sonstiges' zurueck, falls nichts
    passt."""
    for label, pattern in PRODUCT_TYPE_PATTERNS:
        if pattern.search(title):
            return label
    # Fallback: "SetName (csv6C) (CN)" ganz ohne Produkttyp-Wort - bei
    # chinesischen Sets (v.a. card-corner.de) wird "Display" im
    # sichtbaren Titel oft weggelassen, obwohl es sich fast immer um ein
    # Display handelt (nur ueber die Kategorie-Zuordnung der Seite
    # erkennbar, nicht im Text selbst).
    if _BARE_CHINESE_CODE_PATTERN.search(title):
        return "Booster Displays"
    return "Sonstiges"


ALERTS_FILE = "alerts.json"
CORRECTIONS_FILE = "corrections.json"
DEFAULT_ALERTS = ["30th", "151", "Zenit", "Center"]


_alerts_lock = threading.Lock()


def _save_alerts_unlocked(alerts):
    with open(ALERTS_FILE, "w", encoding="utf-8") as f:
        json.dump(alerts, f, ensure_ascii=False, indent=2)


_corrections_lock = threading.RLock()  # RLock: add_/remove_correction_pair rufen load_corrections()
                                       # INNERHALB des Locks auf - ein normaler Lock wuerde sich
                                       # dabei selbst blockieren (Deadlock)
_BLOCKED_PAIRS_CACHE = None


def load_corrections():
    """Laedt die vom Nutzer per '🚫 Falsch verglichen?'-Button gemeldeten
    URL-Paare, die NIE zusammengefuehrt werden duerfen - unabhaengig davon,
    was die Text-/Bild-Erkennung sagt. Das ist ein staendig wachsendes,
    manuelles Korrektur-Gedaechtnis, das bei jedem Rescan automatisch neu
    angewendet wird, OHNE dass der Code selbst angepasst werden muss."""
    with _corrections_lock:
        if not os.path.exists(CORRECTIONS_FILE):
            return []
        try:
            with open(CORRECTIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return [tuple(pair) for pair in data if isinstance(pair, list) and len(pair) == 2]
        except (json.JSONDecodeError, OSError):
            pass
        return []


def _save_corrections_unlocked(pairs):
    with open(CORRECTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump([list(p) for p in pairs], f, ensure_ascii=False, indent=2)


def add_correction_pairs(urls):
    """Speichert alle Paar-Kombinationen einer als 'falsch' gemeldeten
    Gruppe dauerhaft in corrections.json."""
    with _corrections_lock:
        existing = load_corrections()
        existing_set = {frozenset(p) for p in existing}
        for i in range(len(urls)):
            for j in range(i + 1, len(urls)):
                pair = frozenset((urls[i], urls[j]))
                if pair not in existing_set:
                    existing.append((urls[i], urls[j]))
                    existing_set.add(pair)
        _save_corrections_unlocked(existing)
    global _BLOCKED_PAIRS_CACHE
    _BLOCKED_PAIRS_CACHE = None  # Cache invalidieren, wird beim naechsten Scan neu geladen


def get_blocked_pairs():
    """Gecachte Menge aus frozenset({url_a, url_b}) fuer schnelle Lookups
    waehrend des Clusterings."""
    global _BLOCKED_PAIRS_CACHE
    if _BLOCKED_PAIRS_CACHE is None:
        _BLOCKED_PAIRS_CACHE = {frozenset(p) for p in load_corrections()}
    return _BLOCKED_PAIRS_CACHE


def remove_correction_pair(url1, url2):
    """Macht eine per Button gemeldete Trennung wieder rueckgaengig."""
    with _corrections_lock:
        existing = load_corrections()
        target = frozenset((url1, url2))
        remaining = [p for p in existing if frozenset(p) != target]
        _save_corrections_unlocked(remaining)
    global _BLOCKED_PAIRS_CACHE
    _BLOCKED_PAIRS_CACHE = None


def load_alerts():
    """Laedt die Liste der Alarm-Stichwoerter aus alerts.json. Wird die
    Datei nicht gefunden, werden Standard-Stichwoerter (30-Jahre-Jubilaeum)
    angelegt. Die Datei kann jederzeit von Hand bearbeitet werden, um
    eigene Alarme zu setzen - oder ueber die Buttons in der Web-Seite
    (benoetigt den --serve Modus)."""
    with _alerts_lock:
        if not os.path.exists(ALERTS_FILE):
            _save_alerts_unlocked(DEFAULT_ALERTS)
            return DEFAULT_ALERTS[:]
        try:
            with open(ALERTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and data:
                return [str(x).strip() for x in data if str(x).strip()]
        except (json.JSONDecodeError, OSError):
            pass
        return DEFAULT_ALERTS[:]


def save_alerts(alerts):
    with _alerts_lock:
        _save_alerts_unlocked(alerts)


def _wc_to_shopify_like(wc_product):
    """Wandelt ein WooCommerce-Store-API-Produkt in ein Shopify-aehnliches
    Dict um, damit die bestehenden Filter-Funktionen (is_pokemon_product,
    is_sealed_or_graded_product, ...) unveraendert wiederverwendet werden
    koennen - keine doppelte Filterlogik noetig."""
    cats = [c.get("name", "") for c in (wc_product.get("categories") or [])]
    tags = [t.get("name", "") for t in (wc_product.get("tags") or [])]
    return {
        "title": html.unescape(wc_product.get("name", "")),
        "product_type": " ".join(cats),
        "tags": tags,
    }


def _expand_wc_language_variations(wc_product, domain):
    """WooCommerce-Produkte vom Typ "variable" mit einem Sprache-Attribut
    (z.B. Sapphire-Cards: "Pokemon Day 2026 Collection" gibt es als DE fuer
    24,99EUR und EN fuer 34,99EUR unter DEMSELBEN Produkt-Eintrag) haben
    PRO Sprache einen eigenen Preis und eine eigene URL. Ohne diese
    Aufloesung wuerde nur der Preis EINER Sprache (meist die Standard-
    Variante) fuer beide uebernommen werden - ein echter Datenfehler.
    Gibt eine Liste von wc_product-aehnlichen Dicts zurueck (eines pro
    Sprachvariante), oder [wc_product] unveraendert wenn keine
    Sprachvarianten vorhanden sind."""
    if wc_product.get("type") != "variable":
        return [wc_product]
    attrs = wc_product.get("attributes", [])
    lang_attr = next(
        (a for a in attrs if a.get("has_variations") and
         a.get("name", "").lower() in ("sprache", "language", "edition")),
        None,
    )
    variations = wc_product.get("variations", [])
    if not lang_attr or not variations:
        return [wc_product]

    results = []
    for var in variations:
        var_id = var.get("id")
        if not var_id:
            continue
        try:
            var_data = fetch_json(f"https://{domain}/wp-json/wc/store/v1/products/{var_id}")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError):
            continue
        # Kopie des Basisprodukts mit den variantenspezifischen Feldern
        # ueberschrieben (Preis, URL, Verfuegbarkeit) - Titel bleibt vom
        # Hauptprodukt, die Sprache wird separat aus dem Varianten-Attribut
        # ergaenzt, damit sie nicht erst wieder aus dem (identischen)
        # Titel geraten werden muss.
        merged = dict(wc_product)
        merged["prices"] = var_data.get("prices", wc_product.get("prices", {}))
        merged["permalink"] = var_data.get("permalink", wc_product.get("permalink"))
        merged["is_in_stock"] = var_data.get("is_in_stock", wc_product.get("is_in_stock"))
        merged["is_purchasable"] = var_data.get("is_purchasable", wc_product.get("is_purchasable"))
        var_lang_value = next(
            (att.get("value", "") for att in var.get("attributes", [])
             if att.get("name", "").lower() in ("sprache", "language", "edition")),
            "",
        )
        merged["_variation_language_hint"] = var_lang_value
        results.append(merged)
    return results or [wc_product]


def _process_wc_product(wc_product, shop, alert_keywords, offers, preorders, all_products, alert_hits):
    """Verarbeitet EIN WooCommerce-Produkt-JSON und haengt es (falls
    relevant) an die uebergebenen Listen an. Gemeinsame Logik fuer
    scan_shop_woocommerce (normale HTTP-Anfrage) und
    scan_shop_woocommerce_playwright (Fallback per echtem Browser fuer
    JS-geschuetzte Shops) - vermeidet doppelten Code."""
    domain = shop["domain"]
    name = shop["name"]
    adapted = _wc_to_shopify_like(wc_product)
    if not is_pokemon_product(adapted):
        return
    if not is_sealed_or_graded_product(adapted):
        return
    if not wc_product.get("is_in_stock") or not wc_product.get("is_purchasable"):
        return

    graded_flag = is_graded_product(adapted)
    preorder_flag = is_preorder_product(adapted)
    # WICHTIG: WooCommerce liefert Titel oft mit HTML-Entitaeten statt
    # echten Zeichen (z.B. "&#038;" statt "&") - ohne Dekodierung wuerden
    # Regex-Muster, die nach einem echten "&" suchen (z.B. "Karmesin &
    # Purpur"), nie greifen.
    title = html.unescape(wc_product.get("name", "Unbekannt"))
    title_lower = title.lower()
    if ALERT_NOISE_PATTERN.search(title_lower):
        matched_keywords = []
    else:
        matched_keywords = [kw for kw in alert_keywords if kw.lower() in title_lower]

    prices = wc_product.get("prices", {})
    minor_unit = int(prices.get("currency_minor_unit", 2))
    try:
        price = float(prices.get("price", 0)) / (10 ** minor_unit)
        regular = prices.get("regular_price")
        compare_at = (float(regular) / (10 ** minor_unit)) if regular else None
    except (TypeError, ValueError):
        return
    if price <= 0:
        return

    image = None
    if wc_product.get("images"):
        image = wc_product["images"][0].get("src")

    has_discount = bool(compare_at and compare_at > price)
    discount_pct = round((1 - price / compare_at) * 100) if has_discount else 0

    # Sprache: falls eine Varianten-Sprache bekannt ist (siehe
    # _expand_wc_language_variations), hat die IMMER Vorrang vor dem
    # Raten aus dem Titel - der Titel ist bei Sprachvarianten oft
    # identisch fuer DE/EN und wuerde sonst falsch geraten.
    var_lang_hint = wc_product.get("_variation_language_hint", "").lower()
    _VAR_LANG_MAP = {"deutsch": "Deutsch", "german": "Deutsch", "englisch": "Englisch",
                      "english": "Englisch", "japanisch": "Japanisch", "japanese": "Japanisch",
                      "chinesisch": "Chinesisch", "chinese": "Chinesisch",
                      "koreanisch": "Koreanisch", "korean": "Koreanisch"}
    entry_language = _VAR_LANG_MAP.get(var_lang_hint) or detect_language(title)
    if entry_language == "Koreanisch":
        return

    entry_ptype = (
        "Graded Cards & Sammlerstücke" if graded_flag
        else detect_product_type(title)
    )
    if entry_ptype == "Booster / Sleeved Booster / Einzelbooster":
        return

    base_entry = {
        "shop": name,
        "title": title,
        "price": price,
        "image": image,
        "url": wc_product.get("permalink", f"https://{domain}"),
        "norm": normalize_title(title),
        "language": entry_language,
        "product_type": entry_ptype,
        "compare_at": compare_at if has_discount else None,
        "discount_pct": discount_pct,
        "has_discount": has_discount,
    }

    all_products.append(base_entry)
    if has_discount:
        offers.append(base_entry)
    if preorder_flag:
        preorders.append(base_entry)
    for kw in matched_keywords:
        alert_hits[kw].append({**base_entry, "preorder": preorder_flag})


def scan_shop_woocommerce(shop, alert_keywords):
    """Wie scan_shop, aber fuer Shops auf WooCommerce-Basis mit offener
    Store-API (wp-json/wc/store/v1/products) statt Shopify. Viele
    "manuelle" Shops (kein products.json) sind tatsaechlich WooCommerce
    mit einer oeffentlich lesbaren REST-API - dieselbe Idee wie bei
    Shopify, nur ein anderes JSON-Format."""
    domain = shop["domain"]
    name = shop["name"]
    offers, preorders, all_products = [], [], []
    alert_hits = {kw: [] for kw in alert_keywords}
    print(f"-> Scanne {name} ({domain}) [WooCommerce] ...")

    for page in range(1, MAX_PAGES_PER_SHOP + 1):
        url = f"https://{domain}/wp-json/wc/store/v1/products?per_page=100&search=pokemon&page={page}"
        try:
            products = fetch_json(url)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
            print(f"   Fehler bei {url}: {exc}")
            break

        if not isinstance(products, list) or not products:
            break

        for wc_product in products:
            for variant in _expand_wc_language_variations(wc_product, domain):
                _process_wc_product(variant, shop, alert_keywords, offers, preorders, all_products, alert_hits)

        print(f"   Seite {page}: {len(products)} Artikel geprueft, "
              f"{len(offers)} Angebote / {len(preorders)} Vorbestellungen bisher")

        if len(products) < 100:
            break
        time.sleep(REQUEST_DELAY_SEC)

    return offers, preorders, alert_hits, all_products


def scan_shop_woocommerce_playwright(shop, alert_keywords):
    """Wie scan_shop_woocommerce, aber holt die JSON-Antwort ueber einen
    ECHTEN Browser (Playwright) statt einer einfachen HTTP-Anfrage. Fuer
    Shops, die per JS-Bot-Check (z.B. Cloudflare "Just a moment...")
    geschuetzt sind - eine normale Anfrage bekommt dort nur die
    Challenge-Seite statt echter Daten, ein echter Browser besteht den
    Check automatisch. Wird uebersprungen, wenn Playwright nicht
    installiert ist (siehe _PLAYWRIGHT_AVAILABLE)."""
    domain = shop["domain"]
    name = shop["name"]
    offers, preorders, all_products = [], [], []
    alert_hits = {kw: [] for kw in alert_keywords}

    if not _PLAYWRIGHT_AVAILABLE:
        print(f"-> Ueberspringe {name} ({domain}): Playwright nicht installiert "
              f"(optional - 'pip install playwright && playwright install chromium')")
        return offers, preorders, alert_hits, all_products

    print(f"-> Scanne {name} ({domain}) [WooCommerce, per Browser] ...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(user_agent=USER_AGENT)
            page.goto(f"https://{domain}", wait_until="domcontentloaded", timeout=TIMEOUT_SEC * 1000)
            for pg in range(1, MAX_PAGES_PER_SHOP + 1):
                url = f"https://{domain}/wp-json/wc/store/v1/products?per_page=100&search=pokemon&page={pg}"
                result = page.evaluate(
                    """async (url) => {
                        const r = await fetch(url);
                        if (!r.ok) return {ok: false, status: r.status};
                        return {ok: true, data: await r.json()};
                    }""",
                    url,
                )
                if not result.get("ok"):
                    print(f"   Fehler bei {url}: HTTP {result.get('status')}")
                    break
                products = result.get("data") or []
                if not isinstance(products, list) or not products:
                    break
                for wc_product in products:
                    _process_wc_product(wc_product, shop, alert_keywords, offers, preorders, all_products, alert_hits)
                print(f"   Seite {pg}: {len(products)} Artikel geprueft, "
                      f"{len(offers)} Angebote / {len(preorders)} Vorbestellungen bisher")
                if len(products) < 100:
                    break
                time.sleep(REQUEST_DELAY_SEC)
            browser.close()
    except Exception as exc:  # noqa: BLE001 - robust gegen jeden Playwright-Fehler
        print(f"   Fehler beim Browser-Scan von {name}: {exc}")

    return offers, preorders, alert_hits, all_products


TCG_TRADE_CATEGORIES = [
    "pokemon-display",
    "pokemon-special-edition-und-kollektion",
    "pokemon-top-trainer-box",
    "pokemon-booster-und-blister",
    "pokemon-tin-box",
    "pokemon-gegradete-karten",
]


def scan_shop_tcgtrade(shop, alert_keywords):
    """Individueller HTML-Scraper fuer TCG-Trade (epages-Shopsystem, keine
    offene API). Besucht die relevanten Unterkategorien direkt (die
    oberste "Pokemon Store"-Uebersicht zeigt nur eine kleine Auswahl,
    nicht das volle Sortiment!), klickt "Mehr anzeigen" bis alle Artikel
    geladen sind, und liest Titel/Preis/Verfuegbarkeit ueber die
    eingebauten schema.org-Microdata-Attribute aus (zuverlaessiger als
    reines Text-Parsing)."""
    domain = shop["domain"]
    name = shop["name"]
    offers, preorders, all_products = [], [], []
    alert_hits = {kw: [] for kw in alert_keywords}

    if not _PLAYWRIGHT_AVAILABLE:
        print(f"-> Ueberspringe {name} ({domain}): Playwright nicht installiert (optional)")
        return offers, preorders, alert_hits, all_products

    print(f"-> Scanne {name} ({domain}) [individueller Scraper] ...")
    seen_urls = set()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(user_agent=USER_AGENT)
            cookies_accepted = False
            for cat in TCG_TRADE_CATEGORIES:
                url = f"https://{domain}/c/pokemon-store/pokemon-sammelkarten/{cat}"
                try:
                    page.goto(url, wait_until="networkidle", timeout=TIMEOUT_SEC * 1000)
                except Exception as exc:  # noqa: BLE001
                    print(f"   Fehler bei {url}: {exc}")
                    continue
                page.wait_for_timeout(1000)
                if not cookies_accepted:
                    accept_btn = page.query_selector('button:has-text("Akzeptieren")')
                    if accept_btn:
                        accept_btn.click()
                        page.wait_for_timeout(500)
                    cookies_accepted = True

                # "Mehr anzeigen" so lange klicken, bis alle Artikel geladen sind
                for _ in range(15):
                    more_btn = page.query_selector('button:has-text("Mehr anzeigen"), a:has-text("Mehr anzeigen")')
                    if not more_btn:
                        break
                    try:
                        more_btn.click(timeout=5000)
                        page.wait_for_timeout(1200)
                    except Exception:  # noqa: BLE001
                        break

                items = page.query_selector_all(".product-item")
                for it in items:
                    try:
                        link_el = it.query_selector("[itemprop=url]")
                        href = link_el.get_attribute("href") if link_el else None
                        if not href:
                            continue
                        product_url = href if href.startswith("http") else f"https://{domain}{href}"
                        if product_url in seen_urls:
                            continue
                        seen_urls.add(product_url)

                        raw_text = it.inner_text()
                        # Titel = Text vor der ersten Preis-/Rabatt-Zeile, ohne
                        # "NEU"/"SALE"-Badges am Anfang.
                        title_line = raw_text.split("\n")[0]
                        for line in raw_text.split("\n"):
                            stripped = line.strip()
                            if stripped and stripped not in ("NEU", "SALE") and "preis" not in stripped.lower() and "%" not in stripped and "€" not in stripped:
                                title_line = stripped
                                break
                        title = title_line

                        price_el = it.query_selector("[itemprop=price]")
                        if not price_el:
                            continue
                        try:
                            price = float(price_el.get_attribute("content"))
                        except (TypeError, ValueError):
                            continue

                        avail_el = it.query_selector("[itemprop=availability]")
                        avail = avail_el.get_attribute("href") if avail_el else ""
                        if "OutOfStock" in (avail or ""):
                            continue  # nicht verfuegbar

                        image = None
                        img_meta = it.query_selector("meta[itemprop=image]")
                        if img_meta:
                            img_src = img_meta.get_attribute("content")
                            image = img_src if (img_src or "").startswith("http") else f"https://{domain}{img_src}" if img_src else None

                        compare_at = None
                        if "Ursprünglicher Preis" in raw_text:
                            m = re.search(r"Ursprünglicher Preis:\s*([\d.,]+)\s*€", raw_text)
                            if m:
                                try:
                                    compare_at = float(m.group(1).replace(".", "").replace(",", "."))
                                except ValueError:
                                    compare_at = None
                    except Exception:  # noqa: BLE001 - robust gegen einzelne kaputte Karten
                        continue

                    adapted = {"title": title, "product_type": "", "tags": []}
                    if not is_pokemon_product(adapted):
                        continue
                    if not is_sealed_or_graded_product(adapted):
                        continue

                    graded_flag = is_graded_product(adapted)
                    preorder_flag = is_preorder_product(adapted)
                    title_lower = title.lower()
                    if ALERT_NOISE_PATTERN.search(title_lower):
                        matched_keywords = []
                    else:
                        matched_keywords = [kw for kw in alert_keywords if kw.lower() in title_lower]

                    entry_language = detect_language(title)
                    if entry_language == "Koreanisch":
                        continue

                    entry_ptype = (
                        "Graded Cards & Sammlerstücke" if graded_flag
                        else detect_product_type(title)
                    )
                    if entry_ptype == "Booster / Sleeved Booster / Einzelbooster":
                        continue

                    has_discount = bool(compare_at and compare_at > price)
                    discount_pct = round((1 - price / compare_at) * 100) if has_discount else 0

                    base_entry = {
                        "shop": name,
                        "title": title,
                        "price": price,
                        "image": image,
                        "url": product_url,
                        "norm": normalize_title(title),
                        "language": entry_language,
                        "product_type": entry_ptype,
                        "compare_at": compare_at if has_discount else None,
                        "discount_pct": discount_pct,
                        "has_discount": has_discount,
                    }
                    all_products.append(base_entry)
                    if has_discount:
                        offers.append(base_entry)
                    if preorder_flag:
                        preorders.append(base_entry)
                    for kw in matched_keywords:
                        alert_hits[kw].append({**base_entry, "preorder": preorder_flag})

                print(f"   {cat}: {len(items)} Artikel geprueft, "
                      f"{len(offers)} Angebote / {len(preorders)} Vorbestellungen bisher")
                time.sleep(REQUEST_DELAY_SEC)
            browser.close()
    except Exception as exc:  # noqa: BLE001
        print(f"   Fehler beim Scan von {name}: {exc}")

    return offers, preorders, alert_hits, all_products


def scan_shop_gambio(shop, alert_keywords):
    """Individueller HTML-Scraper fuer Shops auf dem gleichen "Gambio"-
    artigen System (erkennbar an "_sN"-Paginierung und ".product-wrapper"-
    Karten) - aktuell Poke-Corner (card-corner.de) und Gate to the Games.
    Kategorien kommen aus shop["categories"] (Liste von URL-Pfaden)."""
    domain = shop["domain"]
    name = shop["name"]
    categories = shop["categories"]
    offers, preorders, all_products = [], [], []
    alert_hits = {kw: [] for kw in alert_keywords}

    if not _PLAYWRIGHT_AVAILABLE:
        print(f"-> Ueberspringe {name} ({domain}): Playwright nicht installiert (optional)")
        return offers, preorders, alert_hits, all_products

    print(f"-> Scanne {name} ({domain}) [individueller Scraper] ...")
    seen_urls = set()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(user_agent=USER_AGENT)
            for cat in categories:
                for pg in range(1, 11):
                    url = f"https://{domain}/{cat}_s{pg}" if pg > 1 else f"https://{domain}/{cat}"
                    try:
                        page.goto(url, wait_until="networkidle", timeout=TIMEOUT_SEC * 1000)
                    except Exception as exc:  # noqa: BLE001
                        print(f"   Fehler bei {url}: {exc}")
                        break
                    page.wait_for_timeout(800)
                    items = page.query_selector_all(".product-wrapper")
                    if not items:
                        break

                    for it in items:
                        try:
                            link_el = it.query_selector("a")
                            href = link_el.get_attribute("href") if link_el else None
                            if not href:
                                continue
                            product_url = href.split("#")[0]
                            if product_url in seen_urls:
                                continue
                            seen_urls.add(product_url)

                            raw_text = it.inner_text()
                            lines = [l.strip() for l in raw_text.split("\n") if l.strip()]

                            # Titel zuverlaessig ueber den Link-Text holen
                            # (nicht ueber Zeilen-Raten - manche Shops haben
                            # sehr lange Beschreibungstexte in der Karte,
                            # z.B. "Inhalt:", "Versandgewicht:", etc., die
                            # das einfache "erste sinnvolle Zeile"-Verfahren
                            # durcheinanderbringen).
                            link_text = (link_el.inner_text() or "").strip()
                            # Status-Baegel wie "VORVERKAUF"/"AUSVERKAUFT" am
                            # Ende des Link-Texts abschneiden (nur GROSS-
                            # geschriebene letzte Woerter).
                            title = re.sub(r"\s+[A-ZÄÖÜ]{4,}$", "", link_text).strip()
                            if not title:
                                _skip = {"bestseller", "auf lager", "vorbestellen", "neu", "sale", "ab", "top"}
                                for line in lines:
                                    if line.lower() in _skip or "€" in line or "lieferzeit" in line.lower():
                                        continue
                                    title = line
                                    break
                            if not title:
                                continue

                            price = None
                            for line in lines:
                                m = re.match(r"^([\d.,]+)\s*€\s*\*?$", line)
                                if m:
                                    try:
                                        price = float(m.group(1).replace(".", "").replace(",", "."))
                                        break
                                    except ValueError:
                                        continue
                            if price is None:
                                continue

                            # Verfuegbarkeit: NUR explizite Ausverkauft-
                            # Marker fuehren zum Ausschluss - manche Shops
                            # (Poke-Corner) zeigen auf der Listenseite gar
                            # keinen "In den Warenkorb"-Button, sondern nur
                            # "Auf Lager"/"Zum Artikel", andere (Gate to the
                            # Games) zeigen ihn nur bei verfuegbaren Artikeln.
                            # Daher: nur negative Marker sind zuverlaessig.
                            is_out_of_stock = any(
                                "nicht auf lager" in l.lower() or "ausverkauft" in l.lower()
                                or "nicht verfügbar" in l.lower()
                                for l in lines
                            )
                            is_preorder_local = any(
                                "vorbestell" in l.lower() or "vorverkauf" in l.lower() for l in lines
                            )
                            if is_out_of_stock:
                                continue

                            # Manche Shops (z.B. PokeGeoDude) haben ZWEI
                            # <img>-Tags pro Karte: zuerst eine kleine
                            # Sprach-Flagge, danach erst das eigentliche
                            # Produktfoto - das Flaggen-Bild wird daher
                            # gezielt ausgeschlossen.
                            image = None
                            for img_candidate in it.query_selector_all("img"):
                                src = img_candidate.get_attribute("src") or ""
                                if src and "flags/" not in src.lower() and "flag" not in src.lower():
                                    image = src
                                    break
                        except Exception:  # noqa: BLE001
                            continue

                        adapted = {"title": title, "product_type": "", "tags": []}
                        if not is_pokemon_product(adapted):
                            continue
                        if not is_sealed_or_graded_product(adapted):
                            continue

                        graded_flag = is_graded_product(adapted)
                        preorder_flag = is_preorder_product(adapted) or is_preorder_local
                        title_lower = title.lower()
                        if ALERT_NOISE_PATTERN.search(title_lower):
                            matched_keywords = []
                        else:
                            matched_keywords = [kw for kw in alert_keywords if kw.lower() in title_lower]

                        entry_language = detect_language(title)
                        if entry_language == "Koreanisch":
                            continue

                        entry_ptype = (
                            "Graded Cards & Sammlerstücke" if graded_flag
                            else detect_product_type(title)
                        )
                        if entry_ptype == "Booster / Sleeved Booster / Einzelbooster":
                            continue

                        base_entry = {
                            "shop": name,
                            "title": title,
                            "price": price,
                            "image": image,
                            "url": product_url,
                            "norm": normalize_title(title),
                            "language": entry_language,
                            "product_type": entry_ptype,
                            "compare_at": None,
                            "discount_pct": 0,
                            "has_discount": False,
                        }
                        all_products.append(base_entry)
                        if preorder_flag:
                            preorders.append(base_entry)
                        for kw in matched_keywords:
                            alert_hits[kw].append({**base_entry, "preorder": preorder_flag})

                    print(f"   {cat} Seite {pg}: {len(items)} Artikel geprueft, "
                          f"{len(all_products)} Produkte bisher")
                    if len(items) < 20:
                        break
                    time.sleep(REQUEST_DELAY_SEC)
            browser.close()
    except Exception as exc:  # noqa: BLE001
        print(f"   Fehler beim Scan von {name}: {exc}")

    return offers, preorders, alert_hits, all_products


def scan_shop_jtl(shop, alert_keywords):
    """Individueller HTML-Scraper fuer Shops auf dem "JTL-Shop"-System
    (erkennbar an "_sN"-Paginierung wie bei Gambio, aber anderer
    Karten-Struktur: ".p-w.col-12"-Container mit "a.title"-Link) -
    aktuell Games-Island. Kategorien kommen aus shop["categories"]
    (Liste von URL-Pfaden)."""
    domain = shop["domain"]
    name = shop["name"]
    categories = shop["categories"]
    offers, preorders, all_products = [], [], []
    alert_hits = {kw: [] for kw in alert_keywords}

    if not _PLAYWRIGHT_AVAILABLE:
        print(f"-> Ueberspringe {name} ({domain}): Playwright nicht installiert (optional)")
        return offers, preorders, alert_hits, all_products

    print(f"-> Scanne {name} ({domain}) [individueller Scraper] ...")
    seen_urls = set()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(user_agent=USER_AGENT)
            for cat in categories:
                for pg in range(1, 11):
                    url = f"https://{domain}/{cat}_s{pg}" if pg > 1 else f"https://{domain}/{cat}"
                    try:
                        page.goto(url, wait_until="networkidle", timeout=TIMEOUT_SEC * 1000)
                    except Exception as exc:  # noqa: BLE001
                        print(f"   Fehler bei {url}: {exc}")
                        break
                    page.wait_for_timeout(1500)

                    def _get_items():
                        try:
                            return page.query_selector_all("div.p-w.col-12")
                        except Exception:  # noqa: BLE001
                            return None  # Ausfuehrungskontext zerstoert (spaete Navigation) - erneut versuchen

                    items = _get_items()
                    if items is None:
                        # Die Seite hat sich NACH "networkidle" noch einmal
                        # selbst neu geladen/umgeleitet (z.B. Cookie-Banner-
                        # Skript) - kommt unter hoher Systemlast (viele
                        # parallele Scans) haeufiger vor. Kurz warten und
                        # neu versuchen, statt die ganze Kategorie
                        # aufzugeben.
                        page.wait_for_timeout(2000)
                        items = _get_items()
                    if not items:
                        # Unter hoher Systemlast (viele parallele Scans)
                        # kann die Seite trotz "networkidle" noch nicht
                        # vollstaendig gerendert sein - einmal kurz
                        # nachwarten und erneut pruefen, bevor aufgegeben
                        # wird.
                        page.wait_for_timeout(2500)
                        items = _get_items() or []
                    if not items:
                        break

                    for it in items:
                        try:
                            link_el = it.query_selector("a.title")
                            href = link_el.get_attribute("href") if link_el else None
                            if not href:
                                continue
                            product_url = href.split("#")[0]
                            if product_url in seen_urls:
                                continue
                            seen_urls.add(product_url)

                            title = (link_el.inner_text() or "").strip()
                            if not title:
                                continue

                            raw_text = it.inner_text()
                            lines = [l.strip() for l in raw_text.split("\n") if l.strip()]

                            price = None
                            for line in lines:
                                m = re.match(r"^([\d.,]+)\s*€\s*\*?$", line)
                                if m:
                                    try:
                                        price = float(m.group(1).replace(".", "").replace(",", "."))
                                        break
                                    except ValueError:
                                        continue
                            if price is None:
                                continue

                            # Verfuegbarkeit: "Momentan nicht verfuegbar" bzw.
                            # der "AUSVERKAUFT"-Badge sind die zuverlaessigen
                            # Ausschluss-Marker bei diesem System.
                            is_out_of_stock = any(
                                "nicht verfügbar" in l.lower() or "ausverkauft" in l.lower()
                                for l in lines
                            )
                            is_preorder_local = any(
                                "vorbestell" in l.lower() or "vorverkauf" in l.lower() for l in lines
                            )
                            if is_out_of_stock:
                                continue

                            image = None
                            for img_candidate in it.query_selector_all("img"):
                                src = img_candidate.get_attribute("src") or ""
                                if src and "flags/" not in src.lower() and "flag" not in src.lower():
                                    image = src
                                    break
                        except Exception:  # noqa: BLE001
                            continue

                        adapted = {"title": title, "product_type": "", "tags": []}
                        if not is_pokemon_product(adapted):
                            continue
                        if not is_sealed_or_graded_product(adapted):
                            continue

                        graded_flag = is_graded_product(adapted)
                        preorder_flag = is_preorder_product(adapted) or is_preorder_local
                        title_lower = title.lower()
                        if ALERT_NOISE_PATTERN.search(title_lower):
                            matched_keywords = []
                        else:
                            matched_keywords = [kw for kw in alert_keywords if kw.lower() in title_lower]

                        entry_language = detect_language(title)
                        if entry_language == "Koreanisch":
                            continue

                        entry_ptype = (
                            "Graded Cards & Sammlerstücke" if graded_flag
                            else detect_product_type(title)
                        )
                        if entry_ptype == "Booster / Sleeved Booster / Einzelbooster":
                            continue

                        base_entry = {
                            "shop": name,
                            "title": title,
                            "price": price,
                            "image": image,
                            "url": product_url,
                            "norm": normalize_title(title),
                            "language": entry_language,
                            "product_type": entry_ptype,
                            "compare_at": None,
                            "discount_pct": 0,
                            "has_discount": False,
                        }
                        all_products.append(base_entry)
                        if preorder_flag:
                            preorders.append(base_entry)
                        for kw in matched_keywords:
                            alert_hits[kw].append({**base_entry, "preorder": preorder_flag})

                    print(f"   {cat} Seite {pg}: {len(items)} Artikel geprueft, "
                          f"{len(all_products)} Produkte bisher")
                    if len(items) < 20:
                        break
                    time.sleep(REQUEST_DELAY_SEC)
            browser.close()
    except Exception as exc:  # noqa: BLE001
        print(f"   Fehler beim Scan von {name}: {type(exc).__name__}: {exc}")

    return offers, preorders, alert_hits, all_products


COMIC_PLANET_LANG_PATHS = ["deutsch", "englisch", "japanisch-pkm", "chinesisch-pkm"]
_COMIC_PLANET_LANG_MAP = {
    "deutsch": "Deutsch",
    "englisch": "Englisch",
    "japanisch-pkm": "Japanisch",
    "chinesisch-pkm": "Chinesisch",
}


def scan_shop_comicplanet(shop, alert_keywords):
    """Individueller HTML-Scraper fuer Comic Planet (Shopware 6, keine
    offene Store-API gefunden). Durchsucht jede Sprach-Unterkategorie
    einzeln mit ?p=N-Pagination."""
    domain = shop["domain"]
    name = shop["name"]
    offers, preorders, all_products = [], [], []
    alert_hits = {kw: [] for kw in alert_keywords}

    if not _PLAYWRIGHT_AVAILABLE:
        print(f"-> Ueberspringe {name} ({domain}): Playwright nicht installiert (optional)")
        return offers, preorders, alert_hits, all_products

    print(f"-> Scanne {name} ({domain}) [individueller Scraper] ...")
    seen_urls = set()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(user_agent=USER_AGENT)
            for lang_path in COMIC_PLANET_LANG_PATHS:
                for pg in range(1, 21):
                    url = f"https://{domain}/sammelkarten/pokemon/{lang_path}/?p={pg}"
                    try:
                        page.goto(url, wait_until="networkidle", timeout=TIMEOUT_SEC * 1000)
                    except Exception as exc:  # noqa: BLE001
                        print(f"   Fehler bei {url}: {exc}")
                        break
                    page.wait_for_timeout(700)
                    items = page.query_selector_all(".product-box")
                    if not items:
                        break

                    for it in items:
                        try:
                            link_el = it.query_selector("a")
                            href = link_el.get_attribute("href") if link_el else None
                            if not href:
                                continue
                            if href in seen_urls:
                                continue
                            seen_urls.add(href)

                            raw_text = it.inner_text()
                            lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
                            _skip = {"neu", "tipp", "vorbestellbar", "topseller", "sale"}
                            title = None
                            for line in lines:
                                if (line.lower() in _skip or "€" in line
                                        or "mwst" in line.lower() or line.lower() == "details"):
                                    continue
                                title = line
                                break
                            if not title:
                                continue

                            price = None
                            for line in lines:
                                m = re.match(r"^([\d.,]+)\s*€\*?$", line)
                                if m:
                                    try:
                                        price = float(m.group(1).replace(".", "").replace(",", "."))
                                        break
                                    except ValueError:
                                        continue
                            if price is None:
                                continue

                            # WICHTIG: nur wenn die Karte "In den Warenkorb"
                            # zeigt, ist der Artikel wirklich bestellbar.
                            # "Vorbestellbar" bei Comic Planet ist NUR ein
                            # "Benachrichtigen"-Button (E-Mail-Anmeldung),
                            # KEIN echter Vorbestell-Mechanismus - solche
                            # Artikel muessen daher komplett raus (nicht in
                            # die Hauptliste, nicht in die Vorbestellungen-
                            # Liste), auch wenn sie mit "Vorbestellbar"
                            # markiert sind.
                            if "in den warenkorb" not in raw_text.lower():
                                continue

                            preorder_flag_local = False
                            img_el = it.query_selector("img")
                            image = img_el.get_attribute("src") if img_el else None
                        except Exception:  # noqa: BLE001
                            continue

                        adapted = {"title": title, "product_type": "", "tags": []}
                        if not is_pokemon_product(adapted):
                            continue
                        if not is_sealed_or_graded_product(adapted):
                            continue

                        graded_flag = is_graded_product(adapted)
                        preorder_flag = is_preorder_product(adapted) or preorder_flag_local
                        title_lower = title.lower()
                        if ALERT_NOISE_PATTERN.search(title_lower):
                            matched_keywords = []
                        else:
                            matched_keywords = [kw for kw in alert_keywords if kw.lower() in title_lower]

                        # WICHTIG: die Sprache steht hier schon fest (durch
                        # welche Sprach-Unterkategorie wir gerade scannen) -
                        # zuverlaessiger als aus dem Titel zu raten, da viele
                        # Titel keine expliziten Sprach-Hinweise haben (z.B.
                        # "Team Rockets Mewtu Tin Box" ohne "deutsch"/"(DE)"
                        # waere sonst faelschlich als Englisch erkannt worden).
                        entry_language = _COMIC_PLANET_LANG_MAP.get(lang_path) or detect_language(title)
                        if entry_language == "Koreanisch":
                            continue

                        entry_ptype = (
                            "Graded Cards & Sammlerstücke" if graded_flag
                            else detect_product_type(title)
                        )
                        if entry_ptype == "Booster / Sleeved Booster / Einzelbooster":
                            continue

                        base_entry = {
                            "shop": name,
                            "title": title,
                            "price": price,
                            "image": image,
                            "url": href,
                            "norm": normalize_title(title),
                            "language": entry_language,
                            "product_type": entry_ptype,
                            "compare_at": None,
                            "discount_pct": 0,
                            "has_discount": False,
                        }
                        all_products.append(base_entry)
                        if preorder_flag:
                            preorders.append(base_entry)
                        for kw in matched_keywords:
                            alert_hits[kw].append({**base_entry, "preorder": preorder_flag})

                    print(f"   {lang_path} Seite {pg}: {len(items)} Artikel geprueft, "
                          f"{len(all_products)} Produkte bisher")
                    if len(items) < 20:
                        break
                    time.sleep(REQUEST_DELAY_SEC)
            browser.close()
    except Exception as exc:  # noqa: BLE001
        print(f"   Fehler beim Scan von {name}: {exc}")

    return offers, preorders, alert_hits, all_products


def scan_shop(shop, alert_keywords):
    """Liest alle Seiten von /products.json und gibt vier Werte zurueck:
    (angebote, vorbestellungen, alarm_treffer, alle_produkte) - jeweils
    nur verfuegbare Pokemon-Artikel. alarm_treffer ist ein Dict
    {{stichwort: [treffer]}}."""
    domain = shop["domain"]
    name = shop["name"]
    offers = []
    preorders = []
    all_products = []
    alert_hits = {kw: [] for kw in alert_keywords}
    print(f"-> Scanne {name} ({domain}) ...")

    for page in range(1, MAX_PAGES_PER_SHOP + 1):
        url = f"https://{domain}/products.json?limit=250&page={page}"
        _note_seen_url(url)
        try:
            data = fetch_json(url, use_cache=True)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
            print(f"   Fehler bei {url}: {exc}")
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (403, 429):
                _register_blocked_shop(name)
            if page == 1:
                # KOMPLETTER Shop-Ausfall (schon die erste Seite scheitert):
                # als echten Fehler nach oben melden, damit der Shop in der
                # Fehlerliste der Web-Seite auftaucht - vorher wurde er
                # faelschlich als Erfolg mit "0 Produkte" gezaehlt und der
                # Nutzer hat den Ausfall nur an fehlenden Artikeln bemerkt.
                raise
            break  # spaetere Seite gescheitert - Teilergebnis behalten

        if data is NOT_MODIFIED:
            # Diese Seite hat sich seit dem letzten Scan NICHT geaendert -
            # der Shop hat nur ein winziges "304" geschickt statt der ganzen
            # Liste (schont Bandbreite UND schuetzt vor IP-Sperren). Wir
            # nehmen die zuletzt gespeicherten Produkte dieser Seite.
            products = _load_cached_shop_page(url)
            if products is None:
                # Kein alter Stand vorhanden (sollte nach dem 1. Scan nicht
                # mehr vorkommen) - zur Sicherheit ohne Cache neu laden.
                try:
                    data = fetch_json(url, use_cache=False)
                except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError):
                    break
                products = data.get("products", [])
                _save_cached_shop_page(url, products)
        else:
            products = data.get("products", [])
            _save_cached_shop_page(url, products)

        if not products:
            break

        for product in products:
            # HTML-Entitaeten dekodieren (z.B. "&amp;" -> "&") - manche
            # Shops liefern das unkodiert, wodurch Regex-Muster mit einem
            # echten "&"-Zeichen sonst nie greifen wuerden.
            if product.get("title"):
                product["title"] = html.unescape(product["title"])
            if not is_pokemon_product(product):
                continue

            if not is_sealed_or_graded_product(product):
                continue  # Einzelkarten, Tickets, Merch raus

            graded_flag = is_graded_product(product)

            preorder_flag = is_preorder_product(product)
            title_lower = product.get("title", "").lower()
            if ALERT_NOISE_PATTERN.search(title_lower):
                matched_keywords = []  # z.B. 25th/1st Anniversary nie als Alarmtreffer werten
            else:
                matched_keywords = [kw for kw in alert_keywords if kw.lower() in title_lower]

            # passende (verfuegbare) Variante mit Preis suchen
            chosen_variant = None
            for variant in product.get("variants", []):
                if not variant.get("available"):
                    continue  # nur verfuegbare Artikel
                chosen_variant = variant
                break  # erste verfuegbare Variante reicht

            if chosen_variant is None:
                continue  # Artikel aktuell nicht bestellbar -> ueberspringen

            try:
                price = float(chosen_variant.get("price") or 0)
                compare_at = chosen_variant.get("compare_at_price")
                compare_at = float(compare_at) if compare_at else None
            except (TypeError, ValueError):
                continue

            image = None
            if product.get("images"):
                image = product["images"][0].get("src")
            elif chosen_variant.get("featured_image"):
                image = chosen_variant["featured_image"].get("src")

            has_discount = bool(compare_at and compare_at > price)
            discount_pct = round((1 - price / compare_at) * 100) if has_discount else 0

            entry_language = detect_language(product.get("title", ""))
            if entry_language == "Koreanisch":
                continue  # koreanische Produkte komplett ausblenden

            entry_ptype = (
                "Graded Cards & Sammlerstücke" if graded_flag
                else detect_product_type(product.get("title", ""))
            )
            if entry_ptype == "Booster / Sleeved Booster / Einzelbooster":
                continue  # einzelne Booster komplett ausblenden, auf Wunsch

            base_entry = {
                "shop": name,
                "title": product.get("title", "Unbekannt"),
                "price": price,
                "image": image,
                "url": f"https://{domain}/products/{product.get('handle', '')}",
                "norm": normalize_title(product.get("title", "")),
                "language": entry_language,
                "product_type": entry_ptype,
                "compare_at": compare_at if has_discount else None,
                "discount_pct": discount_pct,
                "has_discount": has_discount,
            }

            all_products.append(base_entry)

            if has_discount:
                offers.append(base_entry)

            if preorder_flag:
                preorders.append(base_entry)

            for kw in matched_keywords:
                alert_hits[kw].append({**base_entry, "preorder": preorder_flag})

        print(f"   Seite {page}: {len(products)} Artikel geprueft, "
              f"{len(offers)} Angebote / {len(preorders)} Vorbestellungen bisher")

        if len(products) < 250:
            break  # letzte Seite erreicht

        time.sleep(REQUEST_DELAY_SEC)

    return offers, preorders, alert_hits, all_products


_IMAGE_HASH_CACHE = {}
_IMAGE_HASH_LOCK = threading.Lock()


def compute_image_dhash(url, timeout=5):
    """Laedt ein Bild und berechnet einen robusten Wahrnehmungs-Hash
    (Difference-Hash, 8x8=64 Bit). Ignoriert Hintergrundfarben weitgehend,
    da er auf relativen Helligkeitsuntgerschieden benachbarter Pixel
    basiert statt auf absoluten Farbwerten - zwei Fotos des GLEICHEN
    Produkts vor unterschiedlichem Hintergrund/Beleuchtung ergeben meist
    trotzdem einen sehr aehnlichen Hash, waehrend zwei UNTERSCHIEDLICHE
    Produkte deutlich abweichen. Gibt None zurueck, wenn PIL fehlt, das
    Bild nicht ladbar ist, oder es zu lange dauert."""
    if not _PIL_AVAILABLE or not url:
        return None
    with _IMAGE_HASH_LOCK:
        if url in _IMAGE_HASH_CACHE:
            return _IMAGE_HASH_CACHE[url]
    result = None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        # Resampling-Filter versionssicher waehlen: Pillow >= 9.1 nutzt
        # Image.Resampling.LANCZOS, aeltere Versionen nur Image.LANCZOS.
        # (Das alte Image.LANCZOS ist seit Pillow 10 veraltet und faellt in
        # kuenftigen Versionen weg - ohne diese Abfrage wuerde die
        # Bild-Duplikaterkennung dann komplett ausfallen.)
        _resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS", None)
        if _resample is None:  # sehr alte Pillow-Version
            _resample = getattr(Image, "ANTIALIAS", 1)
        img = Image.open(io.BytesIO(data)).convert("L").resize((9, 8), _resample)
        pixels = list(img.getdata())
        bits = 0
        for row in range(8):
            for col in range(8):
                left = pixels[row * 9 + col]
                right = pixels[row * 9 + col + 1]
                bits = (bits << 1) | (1 if left > right else 0)
        result = bits
    except Exception:
        result = None
    with _IMAGE_HASH_LOCK:
        _IMAGE_HASH_CACHE[url] = result
    return result


def _hamming(a, b):
    return bin(a ^ b).count("1")


# Ab dieser Preis-Differenz innerhalb einer Gruppe (teuerster/guenstigster
# Eintrag) wird zusaetzlich das Produktbild verglichen, bevor die Gruppe
# als "gleiches Produkt" akzeptiert wird - reine Text-Aehnlichkeit reicht
# bei so grossen Preisspruengen erfahrungsgemaess nicht mehr als Beleg aus.
IMAGE_VERIFY_PRICE_RATIO = 2.5  # nur noch bei WIRKLICH extremen Preisunterschieden pruefen
IMAGE_HASH_MAX_DISTANCE = 32  # von 64 moeglichen Bits - grosszuegig, da echte Shop-Fotos desselben Produkts (unterschiedlicher Winkel/Hintergrund/Kamera) oft ueber 25 liegen und die Text-Erkennung inzwischen robust genug ist, um Fehltreffer selbststaendig abzufangen


def verify_group_with_images(entries):
    """Prueft eine Gruppe vermeintlich gleicher Produkte zusaetzlich per
    Bildvergleich, WENN die Preise stark auseinanderliegen (typisches
    Warnsignal fuer eine Text-basierte Fehlgruppierung). Gibt eine Liste
    von Teil-Gruppen zurueck (meist nur 1 Element = alles bestaetigt
    gleich; bei einem erkannten Ausreisser 2 Elemente)."""
    if len(entries) < 2:
        return [entries]
    prices = [e["price"] for e in entries]
    if max(prices) < min(prices) * IMAGE_VERIFY_PRICE_RATIO:
        return [entries]  # Preise nah beieinander - keine Bildpruefung noetig
    if not _PIL_AVAILABLE:
        return [entries]  # Bildpruefung nicht verfuegbar - im Zweifel zusammenlassen

    # Referenz: guenstigster Eintrag (meist der "normale" Fall)
    ref = min(entries, key=lambda e: e["price"])
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        hashes = dict(zip(
            [e["url"] for e in entries],
            pool.map(lambda e: compute_image_dhash(e.get("image")), entries),
        ))
    ref_hash = hashes.get(ref["url"])
    if ref_hash is None:
        return [entries]  # Referenzbild nicht ladbar - im Zweifel zusammenlassen

    confirmed, outliers = [], []
    for e in entries:
        h = hashes.get(e["url"])
        if h is None or e is ref:
            confirmed.append(e)
            continue
        if _hamming(ref_hash, h) <= IMAGE_HASH_MAX_DISTANCE:
            confirmed.append(e)
        else:
            outliers.append(e)
    if not outliers:
        return [entries]
    return [confirmed, outliers] if confirmed else [outliers]


def group_by_product(entries):
    """Gruppiert Eintraege, die vermutlich das gleiche Produkt sind, damit
    sie nebeneinander mit ihren jeweiligen Preisen angezeigt werden koennen.

    Statt exaktem Titel-Abgleich wird verglichen:
    - Sprache und Produktart muessen uebereinstimmen (harte Kriterien)
    - Schlagwoerter im Titel (Setname, Edition, Zahlen...) per Jaccard-
      Aehnlichkeit (Fuellwoerter/Sprachkuerzel werden ignoriert)
    - falls vorhanden: Schlagwoerter im Bild-Dateinamen als zusaetzliches
      unterstuetzendes Signal
    Das faengt Schreibweisen-Unterschiede zwischen Shops ab (andere
    Wortreihenfolge, mit/ohne Klammern etc.), ohne wirklich unterschiedliche
    Produkte (z.B. Vol. 1 vs. Vol. 2) faelschlich zusammenzuwerfen.
    """
    # Vorbereitung: Tokens einmal pro Eintrag berechnen
    for e in entries:
        if "_tokens" not in e:
            e["_tokens"] = title_tokens(e["title"])
            e["_img_tokens"] = image_tokens(e.get("image"))

    # nach Produktart vorsortieren - nur innerhalb dieser groben Kategorie
    # wird ueberhaupt auf Aehnlichkeit verglichen (Performance + verhindert
    # voellig unterschiedliche Produkte im selben Cluster). Sprache wird
    # bewusst NICHT als harter Bucket-Schluessel verwendet, sondern erst
    # innerhalb von product_similarity geprueft - so koennen kuratierte
    # Set-Uebersetzungen (z.B. "Journey Together" = "Reisegefährten") trotz
    # unterschiedlicher Sprache erkannt werden, waehrend normale Wort-
    # Aehnlichkeit weiterhin NIE Deutsch und Englisch zufaellig mischt.
    buckets = {}
    for e in entries:
        key = e.get("product_type", "Sonstiges")
        buckets.setdefault(key, []).append(e)

    groups = {}
    group_counter = 0
    for bucket_entries in buckets.values():
        for cluster in _hierarchical_cluster(bucket_entries, product_similarity, SIMILARITY_THRESHOLD):
            deduped = _dedupe_by_shop(cluster)
            # Bei grossem Preisunterschied zusaetzlich das Produktbild
            # pruefen (ignoriert Hintergrund/Beleuchtung weitgehend) - ein
            # per Text faelschlich gruppierter Ausreisser wird so als
            # eigene Gruppe abgespalten statt falsch mitgezeigt zu werden.
            for sub_group in verify_group_with_images(deduped):
                group_counter += 1
                groups[f"g{group_counter}"] = sub_group

    return groups


def _hierarchical_cluster(items, similarity_fn, threshold):
    """Echtes Complete-Linkage-Clustering (im Gegensatz zum vorherigen
    gierigen Ansatz): findet in jedem Schritt GLOBAL das Cluster-Paar mit
    der besten minimalen Aehnlichkeit (= alle Kreuz-Paare muessen passen)
    und fuehrt es zusammen, bis nichts mehr ueber der Schwelle liegt. Das
    ist unabhaengig von der Verarbeitungsreihenfolge der Eintraege - der
    vorherige gierige Ansatz konnte je nach zufaelliger Scan-Reihenfolge
    (Shops werden parallel gescannt) mal ein eigentlich zusammengehoeriges
    Produkt in zwei Gruppen aufspalten, mal nicht - das ist damit behoben.

    Fuer sehr grosse Buckets (>120 Eintraege, z.B. "Sonstiges") wird auf
    den schnelleren gierigen Ansatz zurueckgefallen, um die Laufzeit nicht
    explodieren zu lassen (echtes Complete-Linkage ist O(n^3))."""
    if len(items) > 300:
        return _greedy_cluster(items, similarity_fn, threshold)

    clusters = [[e] for e in items]
    while len(clusters) > 1:
        best_score = 0.0
        best_pair = None
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                min_score = min(
                    similarity_fn(a, b) for a in clusters[i] for b in clusters[j]
                )
                if min_score > best_score:
                    best_score = min_score
                    best_pair = (i, j)
        if best_pair is None or best_score < threshold:
            break
        i, j = best_pair
        clusters[i] = clusters[i] + clusters[j]
        del clusters[j]
    return clusters


def _greedy_cluster(items, similarity_fn, threshold):
    """Schnellerer, reihenfolge-abhaengiger Fallback fuer sehr grosse
    Buckets (siehe _hierarchical_cluster)."""
    clusters = []
    for e in items:
        best_idx = None
        best_score = 0.0
        for i, members in enumerate(clusters):
            min_score = min(similarity_fn(e, m) for m in members)
            if min_score > best_score:
                best_score = min_score
                best_idx = i
        if best_idx is not None and best_score >= threshold:
            clusters[best_idx].append(e)
        else:
            clusters.append([e])
    return clusters


def _dedupe_by_shop(members):
    """Falls durch die Gruppierung mehrere Eintraege vom GLEICHEN Shop im
    selben Cluster landen (z.B. mehrere Varianten desselben Produkts),
    wird pro Shop nur der guenstigste Eintrag behalten - ein Shop soll nie
    doppelt/mehrfach in einer Vergleichskarte auftauchen."""
    by_shop = {}
    for e in members:
        if e["shop"] not in by_shop or e["price"] < by_shop[e["shop"]]["price"]:
            by_shop[e["shop"]] = e
    return list(by_shop.values())


def build_html(all_offers, all_preorders, all_alerts, all_products, scan_time, errors, shop_count):
    all_offers.sort(key=lambda o: o["discount_pct"], reverse=True)
    all_preorders.sort(key=lambda o: (o["shop"], o["title"]))
    placeholder_js = json.dumps(PLACEHOLDER_IMG)
    server_port = CURRENT_SERVER_PORT
    # Sammelt {{"key","price","title","url"}} fuer die Preisverlauf-Funktion
    # waehrend des Renderns - EIN Eintrag pro Produkt+Sprache (guenstigster
    # Preis), nicht pro einzelnem Haendler. Wird am Ende von build_html
    # einmalig persistiert.
    PRICE_POINTS = []

    def esc(s):
        return (str(s)
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;"))

    def offer_card(o):
        img = esc(o["image"]) if o["image"] else ""
        badge = f'<span class="badge">-{o["discount_pct"]}%</span>'
        search_key = esc(f"{o['title']} {o['shop']}".lower())
        img_tag = (
            f'<img src="{img}" alt="{esc(o["title"])}" referrerpolicy="no-referrer" '
            f'class="fallback-img" loading="lazy">'
            if img else f'<img src="{PLACEHOLDER_IMG}" alt="{esc(o["title"])}">'
        )
        return f"""
        <a class="card" data-search="{search_key}" href="{esc(o['url'])}" target="_blank" rel="noopener">
          <div class="imgwrap">{img_tag}{badge}</div>
          <div class="info">
            <div class="shop">{esc(o['shop'])}</div>
            <div class="title">{esc(o['title'])}</div>
            <div class="prices">
              <span class="new">{o['price']:.2f} €</span>
              <span class="old">{o['compare_at']:.2f} €</span>
            </div>
          </div>
        </a>"""

    def compare_card(entries, is_preorder=False):
        """Karte fuer ein Produkt, das in mehreren Shops gefunden wurde -
        zeigt alle Shops mit Preis nebeneinander, sortiert nach Sprache
        (Deutsch, Englisch, Japanisch, Chinesisch, ...), innerhalb der
        gleichen Sprache nach Preis."""
        entries = sorted(entries, key=lambda o: o["price"])
        first = entries[0]
        img = esc(first["image"]) if first["image"] else ""
        img_tag = (
            f'<img src="{img}" alt="{esc(first["title"])}" referrerpolicy="no-referrer" '
            f'class="fallback-img" loading="lazy">'
            if img else f'<img src="{PLACEHOLDER_IMG}" alt="{esc(first["title"])}">'
        )
        search_key = esc(" ".join([e["title"] + " " + e["shop"] for e in entries]).lower())

        def _lang_sort_key(e):
            lang = e.get("language", "Unbekannt")
            return LANGUAGE_ORDER.index(lang) if lang in LANGUAGE_ORDER else len(LANGUAGE_ORDER)

        # Sprache mit den MEISTEN Anbietern (innerhalb dieser Karte) kommt
        # zuerst - das ist relevanter fuer den Nutzer als eine starre
        # Reihenfolge. Bei Gleichstand entscheidet die feste Reihenfolge
        # (Deutsch, Englisch, Japanisch, Chinesisch, ...) als Tie-Breaker.
        # Innerhalb der gleichen Sprache wird weiterhin nach Preis sortiert.
        _lang_counts = {}
        for e in entries:
            lang = e.get("language", "Unbekannt")
            _lang_counts[lang] = _lang_counts.get(lang, 0) + 1
        entries = sorted(
            entries,
            key=lambda e: (-_lang_counts.get(e.get("language", "Unbekannt"), 0), _lang_sort_key(e), e["price"]),
        )
        min_price = min(e["price"] for e in entries)

        # Preisverlauf: NUR EIN Chart pro SPRACHE innerhalb dieser Karte
        # (nicht pro Haendler) - basierend auf dem jeweils GUENSTIGSTEN
        # Preis der Sprachgruppe. Gibt es das Produkt auf Deutsch UND
        # Englisch, entstehen also zwei getrennte Charts.
        _urls_by_lang = {}
        for e in entries:
            _urls_by_lang.setdefault(e.get("language", "Unbekannt"), []).append(e["url"])
        _cheapest_by_lang = {}
        for e in entries:
            lang = e.get("language", "Unbekannt")
            if lang not in _cheapest_by_lang or e["price"] < _cheapest_by_lang[lang]["price"]:
                _cheapest_by_lang[lang] = e
        for lang, cheapest_entry in _cheapest_by_lang.items():
            key = _price_group_key(lang, _urls_by_lang[lang])
            PRICE_POINTS.append({
                "key": key, "price": cheapest_entry["price"],
                "title": f"{first['title']} ({lang})", "url": cheapest_entry["url"],
            })

        rows = []
        best_discount = 0
        _lang_button_shown = set()
        for e in entries:
            cheapest = ' class="cheapest"' if e["price"] == min_price else ""
            price_html = f'{e["price"]:.2f} €'
            if not is_preorder and e.get("compare_at"):
                price_html += f' <span class="old">{e["compare_at"]:.2f} €</span>'
                best_discount = max(best_discount, e.get("discount_pct", 0))
            badge_lang = lang_badge_html(esc, e.get("language", "Unbekannt"))
            cond_badges = entry_condition_badges(esc, e["title"])
            img_attr = f' data-preview-img="{esc(e["image"])}"' if e.get("image") else ""
            lang = e.get("language", "Unbekannt")
            history_btn = ""
            if lang not in _lang_button_shown:
                _lang_button_shown.add(lang)
                key = _price_group_key(lang, _urls_by_lang[lang])
                history_btn = (
                    f'<button class="price-history-btn" data-key="{esc(key)}" '
                    f'data-title="{esc(first["title"])} ({esc(lang)})" title="Preisverlauf ({esc(lang)})">📈</button>'
                )
            rows.append(
                f'<a href="{esc(e["url"])}" target="_blank" rel="noopener" class="compare-row preview-link"{cheapest}{img_attr}>'
                f'<span class="cshop">{badge_lang} {esc(e["shop"])}{cond_badges}</span>'
                f'<span class="cprice">{price_html}{history_btn}</span></a>'
            )
        if is_preorder:
            badge = '<span class="badge pre">VORBESTELLUNG · VERGLEICH</span>'
        elif best_discount:
            badge = f'<span class="badge">-{best_discount}%</span><span class="badge multi">VERGLEICH</span>'
        else:
            badge = '<span class="badge multi">VERGLEICH</span>'
        urls_json = esc(json.dumps([e["url"] for e in entries]))
        flag_btn = (
            f'<button class="flag-wrong-btn" data-urls="{urls_json}" '
            f'title="Sind das in Wirklichkeit VERSCHIEDENE Produkte? Hier melden - '
            f'sie werden dann bei jedem zukünftigen Scan dauerhaft getrennt.">'
            f'🚫 Falsch zusammengeführt?</button>'
        )
        return f"""
        <div class="card compare" data-search="{search_key}">
          <div class="imgwrap">{img_tag}{badge}</div>
          <div class="info">
            <div class="title">{esc(first['title'])}</div>
            <div class="compare-list">{"".join(rows)}</div>
            {flag_btn}
          </div>
        </div>"""

    def preorder_card(o):
        img = esc(o["image"]) if o["image"] else ""
        search_key = esc(f"{o['title']} {o['shop']}".lower())
        img_tag = (
            f'<img src="{img}" alt="{esc(o["title"])}" referrerpolicy="no-referrer" '
            f'class="fallback-img" loading="lazy">'
            if img else f'<img src="{PLACEHOLDER_IMG}" alt="{esc(o["title"])}">'
        )
        return f"""
        <a class="card" data-search="{search_key}" href="{esc(o['url'])}" target="_blank" rel="noopener">
          <div class="imgwrap">{img_tag}<span class="badge pre">VORBESTELLUNG</span></div>
          <div class="info">
            <div class="shop">{esc(o['shop'])}</div>
            <div class="title">{esc(o['title'])}</div>
            <div class="prices">
              <span class="new">{o['price']:.2f} €</span>
            </div>
          </div>
        </a>"""

    # Gruppieren: gleiche Produkte aus mehreren Shops als Vergleichskarte,
    # alles andere als normale Einzelkarte
    offer_groups = group_by_product(all_offers)
    offer_cards = []
    # Zweistufige Sortierung: erst DE/EN/JP-Gruppen (nach Rabatt absteigend),
    # danach ALLE rein chinesischen Gruppen ganz unten (dort ebenfalls nach
    # Rabatt absteigend).
    for entries in [
        e for _, e in sorted(
            offer_groups.items(),
            key=lambda kv: (_is_low_prio_group(kv[1]), -min(e["discount_pct"] for e in kv[1])),
        )
    ]:
        if len(entries) > 1:
            offer_cards.append(compare_card(entries, is_preorder=False))
        else:
            offer_cards.append(offer_card(entries[0]))

    preorder_groups = group_by_product(all_preorders)
    preorder_cards = []
    # Auch hier: Chinesisch immer ganz unten, innerhalb der Stufen nach
    # fuehrender Sprache (DE vor EN vor JP) und dann alphabetisch.
    for entries in [
        e for _, e in sorted(
            preorder_groups.items(),
            key=lambda kv: (
                _is_low_prio_group(kv[1]),
                min(_language_priority(e.get("language", "Unbekannt")) for e in kv[1]),
                kv[1][0]["title"].lower(),
            ),
        )
    ]:
        if len(entries) > 1:
            preorder_cards.append(compare_card(entries, is_preorder=True))
        else:
            preorder_cards.append(preorder_card(entries[0]))

    offers_html = "".join(offer_cards) or \
        '<div class="empty">Aktuell keine reduzierten, verfügbaren Pokemon-Artikel gefunden.</div>'
    preorders_html = "".join(preorder_cards) or \
        '<div class="empty">Aktuell keine offenen Pokemon-Vorbestellungen gefunden.</div>'

    # -- "Alle Produkte"-Tab: nach Produktart gruppiert, gleiche Produkte
    # ueber Sprachgrenzen hinweg zusammengefasst (Sprache wird pro Eintrag
    # als Flagge angezeigt statt strikt zu trennen). "Graded" (gegradete
    # Karten) und "Zubehör" bleiben als eigene, klar abgegrenzte Bereiche,
    # weil das inhaltlich keine "Sprachen" im eigentlichen Sinn sind.
    def product_card(o):
        img = esc(o["image"]) if o["image"] else ""
        search_key = esc(f"{o['title']} {o['shop']} {o['language']} {o['product_type']}".lower())
        img_tag = (
            f'<img src="{img}" alt="{esc(o["title"])}" referrerpolicy="no-referrer" class="fallback-img" loading="lazy">'
            if img else f'<img src="{PLACEHOLDER_IMG}" alt="{esc(o["title"])}">'
        )
        badge = f'<span class="badge">-{o["discount_pct"]}%</span>' if o.get("has_discount") else ""
        price_html = f'<span class="new">{o["price"]:.2f} €</span>'
        if o.get("has_discount"):
            price_html += f' <span class="old">{o["compare_at"]:.2f} €</span>'
        badge_lang = lang_badge_html(esc, o.get("language", "Unbekannt"))
        cond_badges = entry_condition_badges(esc, o["title"])
        lang = o.get("language", "Unbekannt")
        key = _price_group_key(lang, [o["url"]])
        PRICE_POINTS.append({"key": key, "price": o["price"], "title": f"{o['title']} ({lang})", "url": o["url"]})
        return f"""
        <a class="card" data-search="{search_key}" href="{esc(o['url'])}" target="_blank" rel="noopener">
          <div class="imgwrap">{img_tag}{badge}</div>
          <div class="info">
            <div class="shop">{badge_lang} {esc(o['shop'])}{cond_badges}</div>
            <div class="title">{esc(o['title'])}</div>
            <div class="prices">{price_html}<button class="price-history-btn" data-key="{esc(key)}" data-title="{esc(o['title'])} ({esc(lang)})" title="Preisverlauf">📈</button></div>
          </div>
        </a>"""

    def ptype_sort_key(t):
        return PRODUCT_TYPE_ORDER.index(t) if t in PRODUCT_TYPE_ORDER else len(PRODUCT_TYPE_ORDER)

    def render_type_sections(items_by_type, id_prefix):
        """Baut fuer eine gegebene {{ptyp: [produkte]}}-Zuordnung die
        HTML-Bloecke + Schnellnav-Pills. Gibt (html, nav_pills) zurueck."""
        sections = []
        pills = []
        for ptype in sorted(items_by_type.keys(), key=ptype_sort_key):
            items = items_by_type[ptype]
            cat_id = f"cat-{id_prefix}-{slugify(ptype)}"
            pills.append(
                f'<a class="nav-pill" href="#{cat_id}">{esc(ptype)} <span>{len(items)}</span></a>'
            )
            # Gleiche Produkte (auch ueber Sprachgrenzen hinweg!) als
            # Vergleichskarte zusammenfassen, alles andere als Einzelkarte.
            item_groups = group_by_product(items)
            cards_list = []
            for entries in item_groups.values():
                has_disc = any(e.get("has_discount") for e in entries)
                max_price = max(e["price"] for e in entries)
                lang_idx = min(
                    (LANGUAGE_ORDER.index(e.get("language", "Unbekannt"))
                     if e.get("language", "Unbekannt") in LANGUAGE_ORDER
                     else len(LANGUAGE_ORDER))
                    for e in entries
                )
                if ptype == "Booster Displays":
                    # Speziell fuer Displays: erst 36er, dann 18er, dann
                    # Japanisch, dann Chinesisch (Boosteranzahl ist hier
                    # wichtiger als Sprache, da DE/EN-Displays ueblicherweise
                    # in 36er/18er-Groesse kommen, JP/CN aber andere feste
                    # Groessen haben und daher nach Sprache gruppiert bleiben).
                    sort_idx = 4  # Fallback
                    for e in entries:
                        boostercounts = {t for t in e.get("_tokens", set()) if t.startswith("boostercount")}
                        lang = e.get("language", "Unbekannt")
                        # WICHTIG: die 18er/36er-Unterscheidung gilt NUR
                        # innerhalb DE/EN - ein chinesisches oder
                        # japanisches Display kann im Titel ebenfalls
                        # "18er" stehen haben (z.B. weil es dort wirklich
                        # 18 Booster sind), gehoert aber trotzdem in den
                        # JP/CN-Sprachtopf, nicht in den DE-18er-Topf.
                        if lang in ("Deutsch", "Englisch") and "boostercount18" in boostercounts:
                            sort_idx = min(sort_idx, 1)
                        elif lang in ("Deutsch", "Englisch"):
                            sort_idx = min(sort_idx, 0)  # 36er (Standard, auch ohne Tag)
                        elif lang == "Japanisch":
                            sort_idx = min(sort_idx, 2)
                        elif lang == "Chinesisch":
                            sort_idx = min(sort_idx, 3)
                else:
                    # Sprache der Karte: die "fuehrende" (niedrigste in der
                    # LANGUAGE_ORDER) Sprache unter allen zusammengefassten
                    # Angeboten - z.B. hat eine DE+EN-Vergleichskarte Vorrang
                    # vor einer reinen EN-Karte. detect_language() erkennt die
                    # Sprache bereits zuverlaessig direkt aus dem Artikeltext
                    # (auch ohne expliziten Sprach-Tag, ueber Hinweiswoerter),
                    # "Unbekannt" tritt daher nur in echten Ausnahmefaellen auf.
                    sort_idx = lang_idx
                if len(entries) > 1:
                    html = compare_card(entries, is_preorder=False)
                else:
                    html = product_card(entries[0])
                cards_list.append((sort_idx, has_disc, max_price, html))
            # Erst die primaere Sortiergruppe (36er/18er/JP/CN bei Displays,
            # sonst Sprache), danach wie bisher Rabatt-Artikel zuerst, dann
            # jeweils absteigend nach Preis.
            cards_list.sort(key=lambda t: (t[0], not t[1], -t[2]))
            cards = "".join(html for _, _, _, html in cards_list)
            sections.append(f"""
            <div class="ptype-block" id="{cat_id}">
              <div class="ptype-title">📦 {esc(ptype)} ({len(items)})</div>
              <div class="grid grid-compact">{cards}</div>
            </div>""")
        return "".join(sections), pills

    # Alle Produkte (Graded/Zubehör sind jetzt normale Kategorien in
    # PRODUCT_TYPE_ORDER, keine Sonderbehandlung mehr noetig) nach
    # Produktart gruppieren. Vorbestellungen UND sehr teure Artikel (ab
    # 1000 Euro) werden NICHT mit aufgenommen - die sollen ausschliesslich
    # im jeweils eigenen Tab auftauchen, nicht zusaetzlich auch noch in
    # "Alle Produkte" (sonst wuerden z.B. Sealed Cases/Sammlerstuecke mit
    # Extrempreisen die normale Uebersicht zumuellen).
    _preorder_urls = {p["url"] for p in all_preorders}
    _EXPENSIVE_THRESHOLD = 1000
    expensive_products = [p for p in all_products if p["price"] >= _EXPENSIVE_THRESHOLD]
    _expensive_urls = {p["url"] for p in expensive_products}
    products_by_type = {}
    for p in all_products:
        if p["url"] in _preorder_urls or p["url"] in _expensive_urls:
            continue
        products_by_type.setdefault(p["product_type"], []).append(p)

    expensive_by_type = {}
    for p in expensive_products:
        expensive_by_type.setdefault(p["product_type"], []).append(p)

    all_products_sections = []
    quick_nav_blocks = []

    products_html, products_pills = render_type_sections(products_by_type, "all")
    products_total = sum(len(items) for items in products_by_type.values())
    if products_html:
        all_products_sections.append(f'<div class="lang-block" id="lang-all">{products_html}</div>')
        quick_nav_blocks.append(f"""
        <div class="qnav-lang">
          <a class="qnav-lang-title" href="#lang-all">📦 Alle Kategorien <span>{products_total}</span></a>
          <div class="qnav-pills">{"".join(products_pills)}</div>
        </div>""")

    all_products_html = "".join(all_products_sections) or \
        '<div class="empty">Keine Produkte gefunden.</div>'
    quick_nav_html = "".join(quick_nav_blocks)

    expensive_html, _expensive_pills = render_type_sections(expensive_by_type, "expensive")
    expensive_total = sum(len(items) for items in expensive_by_type.values())
    expensive_html = expensive_html or '<div class="empty">Aktuell keine Artikel ab 1.000 € gefunden.</div>'

    calendar_sorted = sorted(get_release_calendar(), key=lambda c: c["date"], reverse=True)

    def _format_cal_date(iso_date):
        """ISO-Datum (YYYY-MM-DD) in ein kompaktes, gut lesbares deutsches
        Format (DD.MM.YYYY) umwandeln - faellt bei unvollstaendigen/
        Sonderformaten (z.B. "2026-09-ca.") auf das Original zurueck."""
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", iso_date)
        if m:
            yyyy, mm, dd = m.groups()
            return f"{dd}.{mm}.{yyyy}"
        return iso_date

    _CAL_STATUS_BADGE = {
        "erschienen": ("✅", "Erschienen"),
        "bevorstehend": ("🕒", "Bevorstehend"),
        "erwartet": ("❔", "Erwartet"),
    }

    calendar_rows = "\n".join(
        f'<tr class="cal-{c["status"]}" data-search="{esc((c["set"] + " " + c["lang"] + " " + c["status"] + " " + c["date"]).lower())}">'
        f'<td class="cal-date">{esc(_format_cal_date(c["date"]))}</td>'
        f'<td class="cal-set">{esc(c["set"])}</td>'
        f'<td class="cal-lang">{esc(c["lang"])}</td>'
        f'<td class="cal-status"><span class="cal-status-badge cal-badge-{c["status"]}">'
        f'{_CAL_STATUS_BADGE.get(c["status"], ("", c["status"]))[0]} '
        f'{_CAL_STATUS_BADGE.get(c["status"], ("", c["status"]))[1]}</span></td></tr>'
        for c in calendar_sorted
    )

    manual_html = "\n".join(
        f'<li><a href="{esc(s["url"])}" target="_blank" rel="noopener">{esc(s["name"])}</a></li>'
        for s in MANUAL_SHOPS
    )
    manual_section = (
        f'<div class="manual">\n'
        f'  <h2>Weitere Shops (keine offene Schnittstelle – bitte manuell prüfen)</h2>\n'
        f'  <ul>\n    {manual_html}\n  </ul>\n'
        f'</div>'
    ) if manual_html else ""

    def alert_block(keyword, hits):
        seen = set()
        filtered_hits = []
        for a in hits:
            key = (a["shop"], a["title"])
            if key in seen:
                continue
            seen.add(key)
            lang = a.get("language", "Unbekannt")
            ptype = a.get("product_type", "")
            if lang == "Koreanisch":
                continue  # in Alarmen nicht relevant
            if ptype in ("Zubehör & Schutz", "Graded Cards & Sammlerstücke"):
                continue  # Zubehoer und gegradete Karten nicht in Alarmen listen
            filtered_hits.append(a)

        total_count = len(filtered_hits)
        status_class = "alert-hit" if total_count else "alert-empty"
        status_text = (
            f"🎉 {total_count} Treffer!" if total_count else "😶 noch keine Treffer"
        )

        if filtered_hits:
            # Gleiche Produkte aus mehreren Shops UND ueber Sprachgrenzen
            # hinweg zusammenfassen (wie im "Alle Produkte"-Tab), statt
            # jeden Eintrag einzeln oder pro Sprache getrennt zu listen.
            item_groups = group_by_product(filtered_hits)

            def _common_prefix_at_word(titles):
                """Laengster gemeinsamer Anfang mehrerer Titel, endend an
                einer Wortgrenze (Leerzeichen oder Bindestrich) - schneidet
                nie mitten in einem Wort ab."""
                if not titles:
                    return ""
                prefix = os.path.commonprefix(titles)
                idx = max(prefix.rfind(" "), prefix.rfind("-"))
                return prefix[:idx + 1] if idx > 5 else ""

            # Varianten-Buendelung: mehrere Produkte, die sich NUR in einem
            # Detail unterscheiden (z.B. "... Mini-Tin deutsch - Dragoran &
            # Giflor" vs. "... - Elektek & Magnetilo"), teilen sich einen
            # langen gemeinsamen Namens-Anfang. Statt jede Variante als
            # eigene volle Karte mit komplett wiederholtem Namen zu zeigen,
            # werden 3+ solcher Varianten zu EINER kompakten Liste
            # zusammengefasst (gemeinsamer Name einmal oben, darunter nur
            # die jeweilige Variante + Preis).
            groups_by_title = sorted(item_groups.values(), key=lambda es: es[0]["title"])
            clusters = []
            current = [groups_by_title[0]] if groups_by_title else []
            for g in groups_by_title[1:]:
                prefix = _common_prefix_at_word([current[-1][0]["title"], g[0]["title"]])
                if len(prefix) >= 20:
                    current.append(g)
                else:
                    clusters.append(current)
                    current = [g]
            if current:
                clusters.append(current)

            def _group_lang_key(es):
                langs = [e.get("language", "Unbekannt") for e in es]
                best_lang_idx = min(
                    (LANGUAGE_ORDER.index(l) if l in LANGUAGE_ORDER else len(LANGUAGE_ORDER))
                    for l in langs
                )
                return (best_lang_idx, min(e["price"] for e in es))

            def _alert_lang_key(e):
                lang = e.get("language", "Unbekannt")
                return (LANGUAGE_ORDER.index(lang) if lang in LANGUAGE_ORDER else len(LANGUAGE_ORDER), e["price"])

            def _cluster_lang_key(cluster):
                best_idx = min(_group_lang_key(g)[0] for g in cluster)
                best_price = min(_group_lang_key(g)[1] for g in cluster)
                return (best_idx, best_price)

            clusters.sort(key=_cluster_lang_key)

            rows = []
            for cluster in clusters:
                if len(cluster) >= 3:
                    shared_prefix = _common_prefix_at_word([g[0]["title"] for g in cluster])
                else:
                    shared_prefix = ""

                if shared_prefix:
                    # Kompakte Varianten-Liste: gemeinsamer Name einmal,
                    # darunter jede Variante + billigster Preis/Shop.
                    cluster_sorted = sorted(cluster, key=_group_lang_key)
                    variant_rows = []
                    for entries in cluster_sorted:
                        entries_sorted = sorted(entries, key=_alert_lang_key)
                        cheapest = entries_sorted[0]
                        variant = cheapest["title"][len(shared_prefix):].strip() or cheapest["title"]
                        badge_lang = lang_badge_html(esc, cheapest.get("language", "Unbekannt"))
                        img_attr = f' data-preview-img="{esc(cheapest["image"])}"' if cheapest.get("image") else ""
                        extra = f" (+{len(entries_sorted)-1} weitere)" if len(entries_sorted) > 1 else ""
                        variant_rows.append(
                            f'<a href="{esc(cheapest["url"])}" target="_blank" rel="noopener" class="alert-variant-row preview-link"{img_attr}>'
                            f'<span class="alert-variant-name">{badge_lang} {esc(variant)}</span>'
                            f'<span class="alert-variant-price">{cheapest["price"]:.2f} € · {esc(cheapest["shop"])}{esc(extra)}</span></a>'
                        )
                    rows.append(
                        f'<li class="alert-item alert-item-cluster">'
                        f'<div class="alert-item-title">{esc(short_title_html(shared_prefix.rstrip(" -")))} '
                        f'<span class="alert-variant-count">({len(cluster)} Varianten)</span></div>'
                        f'<div class="alert-variant-list">{"".join(variant_rows)}</div>'
                        f'</li>'
                    )
                    continue

                for entries in sorted(cluster, key=_group_lang_key):
                    entries_sorted = sorted(entries, key=_alert_lang_key)
                    first = entries_sorted[0]
                    img_attr = f' data-preview-img="{esc(first["image"])}"' if first.get("image") else ""
                    short_title = short_title_html(first["title"])
                    shop_rows = []
                    for e in entries_sorted:
                        badge_lang = lang_badge_html(esc, e.get("language", "Unbekannt"))
                        cond_badges = entry_condition_badges(esc, e["title"])
                        tag = " · VB" if e.get("preorder") else ""
                        shop_rows.append(
                            f'<a href="{esc(e["url"])}" target="_blank" rel="noopener" class="alert-shop-row preview-link"{img_attr}>'
                            f'<span class="alert-shop-name">{badge_lang} {esc(e["shop"])}{cond_badges}</span>'
                            f'<span class="alert-shop-price">{e["price"]:.2f} €{tag}</span></a>'
                        )
                    rows.append(
                        f'<li class="alert-item">'
                        f'<div class="alert-item-title">{esc(short_title)}</div>'
                        f'<div class="alert-item-shops">{"".join(shop_rows)}</div>'
                        f'</li>'
                    )
            body = f'<ul class="alert-item-list">{"".join(rows)}</ul>'
        else:
            body = '<p class="alert-waiting">Wird bei jedem Scan automatisch weiter geprüft.</p>'

        return f"""
        <div class="alert-card {status_class}" data-keyword="{esc(keyword)}">
          <div class="alert-head">
            <span class="alert-kw">🔔 „{esc(keyword)}"</span>
            <span class="alert-status">{status_text}</span>
            <button class="alert-remove" data-remove-keyword="{esc(keyword)}" title="Alarm entfernen">✕</button>
          </div>
          {body}
        </div>"""

    alerts_html = "".join(alert_block(kw, hits) for kw, hits in all_alerts.items()) or \
        '<p class="alert-waiting">Noch keine Alarme konfiguriert.</p>'

    total_alert_hits = sum(len(v) for v in all_alerts.values())
    alerts_banner = f"""
        <div class="anniv-banner" id="alertsBanner">
          <div class="alert-banner-head">
            <strong>🔔 Produkt-Alarme</strong>
            <span class="alert-summary">{total_alert_hits} Treffer über {len(all_alerts)} Alarm(e)</span>
          </div>
          <div class="alert-add-row">
            <input type="text" id="newAlertInput" placeholder="Neues Stichwort, z. B. „151" oder „Charizard"…">
            <button id="addAlertBtn">+ Alarm hinzufügen</button>
          </div>
          <div id="alertLocalStatus" class="alert-local-status"></div>
          <div id="alertsList" class="alerts-list">{alerts_html}</div>
          <p class="alert-hint">Alarme werden in <code>alerts.json</code> gespeichert. Hinzufügen/Entfernen über die Buttons hier funktioniert nur mit <code>python3 scan.py --serve</code>. Ohne Server: <code>alerts.json</code> direkt bearbeiten und <code>python3 scan.py</code> erneut ausführen.</p>
        </div>"""

    corrections = load_corrections()
    if corrections:
        correction_rows = []
        for pair in corrections:
            u1, u2 = pair[0], pair[1]
            short1 = u1.split("/")[2] if u1.count("/") >= 2 else u1
            short2 = u2.split("/")[2] if u2.count("/") >= 2 else u2
            pair_json = esc(json.dumps([u1, u2]))
            correction_rows.append(f"""
            <li class="correction-item">
              <span class="correction-pair"><a href="{esc(u1)}" target="_blank" rel="noopener">{esc(short1)}</a> ↔ <a href="{esc(u2)}" target="_blank" rel="noopener">{esc(short2)}</a></span>
              <button class="correction-undo-btn" data-pair="{pair_json}" title="Diese Trennung wieder rückgängig machen">↩ rückgängig</button>
            </li>""")
        corrections_html = f"""
        <div class="anniv-banner" id="correctionsBanner">
          <div class="alert-banner-head">
            <strong>🚫 Gemeldete Korrekturen</strong>
            <span class="alert-summary">{len(corrections)} getrennt gehalten</span>
          </div>
          <ul class="correction-list">{"".join(correction_rows)}</ul>
          <p class="alert-hint">Diese Produktpaare werden bei jedem Scan automatisch getrennt gehalten (siehe <code>corrections.json</code>). "Rückgängig" braucht <code>python3 scan.py --serve</code>.</p>
        </div>"""
    else:
        corrections_html = ""

    errors_html = ""
    if errors:
        items = "\n".join(f"<li>{esc(e)}</li>" for e in errors)
        errors_html = f"""
        <div class="errorbox">
          <strong>Hinweis:</strong> Bei folgenden Shops gab es beim Scannen ein Problem
          (evtl. temporaer nicht erreichbar):
          <ul>{items}</ul>
        </div>"""

    _update_price_history_grouped(PRICE_POINTS)
    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<title>Pokemon TCG Angebote &amp; Vorbestellungen – Scan vom {esc(scan_time)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<!-- PWA: macht die Seite auf Android UND iOS als App-Icon installierbar
     ("Zum Home-Bildschirm hinzufuegen") - kein natives APK/IPA, aber
     verhaelt sich wie eine App (eigenes Icon, Vollbild-Start, Offline-
     Anzeige des letzten Scan-Stands). -->
<link rel="manifest" href="manifest.json">
<meta name="theme-color" content="#ffcb05">
<link rel="apple-touch-icon" href="icon-192.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="PKM Scanner">
<style>
  :root {{
    --bg: #0d0f1a;
    --bg-elevated: #151934;
    --card: #1a1f36;
    --card-hover: #202748;
    --accent: #ffcb05;
    --accent-soft: #ffe8a3;
    --accent2: #3b4cca;
    --text: #f2f3fb;
    --muted: #9aa0c0;
    --border: #2a2f4a;
    --radius: 14px;
    --radius-sm: 9px;
    --shadow: 0 4px 16px rgba(0,0,0,.35);
    --shadow-lg: 0 12px 32px rgba(0,0,0,.45);
  }}
  * {{ box-sizing: border-box; }}
  html {{ scroll-behavior: smooth; }}
  body {{
    margin: 0;
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background:
      radial-gradient(circle at 15% 0%, rgba(59,76,202,.18), transparent 45%),
      radial-gradient(circle at 85% 8%, rgba(255,203,5,.08), transparent 40%),
      var(--bg);
    color: var(--text);
    line-height: 1.45;
    -webkit-font-smoothing: antialiased;
  }}
  a {{ transition: color .15s ease; }}
  header {{
    padding: 32px 24px 22px;
    text-align: center;
    background: linear-gradient(135deg, var(--accent2), #171b34 75%);
    border-bottom: 3px solid var(--accent);
    box-shadow: var(--shadow-lg);
    position: relative;
  }}
  header h1 {{ margin: 0 0 8px; font-size: 1.75rem; font-weight: 800; letter-spacing: -.01em; }}
  header p {{ margin: 0; color: #dfe2f5; font-size: 0.92rem; }}
  .meta {{
    max-width: 1100px; margin: 10px auto 0; padding: 0 20px;
    color: #565b7a; font-size: 0.68rem; opacity: 0.8; line-height: 1.4;
  }}
  .searchbar {{
    max-width: 1100px; margin: 18px auto 0; padding: 0 20px;
  }}
  .searchbar input {{
    width: 100%; padding: 15px 18px; border-radius: var(--radius);
    border: 1.5px solid var(--border); background: var(--card); color: var(--text);
    font-size: 1rem; outline: none; transition: border-color .15s ease, box-shadow .15s ease;
    box-shadow: var(--shadow);
  }}
  .searchbar input:focus {{ border-color: var(--accent); box-shadow: 0 0 0 3px rgba(255,203,5,.18), var(--shadow); }}
  .searchbar input::placeholder {{ color: var(--muted); }}
  .no-results {{
    text-align: center; color: var(--muted); padding: 40px 20px; grid-column: 1/-1; display: none;
  }}
  nav.tabs {{
    max-width: 1100px; margin: 22px auto 0; padding: 0 20px;
    display: flex; gap: 8px; flex-wrap: wrap;
  }}
  nav.tabs button {{
    flex: 1; min-width: 140px; padding: 13px; border-radius: var(--radius-sm);
    border: 1.5px solid var(--border); background: var(--card); color: var(--text);
    font-size: 0.92rem; font-weight: 700; cursor: pointer;
    transition: all .15s ease;
  }}
  nav.tabs button:hover {{ border-color: var(--accent); transform: translateY(-1px); }}
  nav.tabs button.active {{
    background: linear-gradient(135deg, var(--accent), #f2b400); color: #1a1f36;
    border-color: var(--accent); box-shadow: 0 4px 14px rgba(255,203,5,.3);
  }}
  section {{ display: none; }}
  section.active {{ display: block; }}
  h2.section-title {{
    max-width: 1200px; margin: 26px auto 0; padding: 0 20px;
    font-size: 1.15rem; color: var(--text);
  }}
  .grid {{
    max-width: 1200px;
    margin: 14px auto 40px;
    padding: 0 20px;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 18px;
  }}
  .card {{
    background: var(--card);
    border-radius: var(--radius);
    overflow: hidden;
    text-decoration: none;
    color: var(--text);
    display: flex;
    flex-direction: column;
    border: 1px solid var(--border);
    box-shadow: var(--shadow);
    transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease, background .18s ease;
  }}
  .card:hover {{
    transform: translateY(-5px);
    border-color: var(--accent);
    box-shadow: var(--shadow-lg);
    background: var(--card-hover);
  }}
  .imgwrap {{ position: relative; aspect-ratio: 1/1; background: #10142a; overflow: hidden; }}
  .imgwrap img {{ width: 100%; height: 100%; object-fit: contain; transition: transform .3s ease; }}
  .card:hover .imgwrap img {{ transform: scale(1.04); }}
  .badge {{
    position: absolute; top: 8px; right: 8px;
    background: linear-gradient(135deg, #ff5a3c, #e3350d); color: #fff;
    font-weight: 800; font-size: 0.8rem;
    padding: 4px 9px; border-radius: 999px;
    box-shadow: 0 3px 8px rgba(227,53,13,.4);
  }}
  .badge.pre {{ background: linear-gradient(135deg, #5a6ce0, var(--accent2)); font-size: 0.66rem; }}
  .badge.multi {{ background: linear-gradient(135deg, #9d5cf0, #7b3fe4); font-size: 0.66rem; }}
  .lang-badge {{
    display: inline-block; font-size: 0.66rem; font-weight: 800; padding: 2px 6px;
    border-radius: 5px; letter-spacing: .02em; vertical-align: middle;
    color: #10142a;
  }}
  .lang-badge.lang-de {{ background: #ffce00; }}
  .lang-badge.lang-en {{ background: #6fb8ff; }}
  .lang-badge.lang-jp {{ background: #ff8fa8; }}
  .lang-badge.lang-cn {{ background: #ff8a5c; }}
  .lang-badge.lang-kr {{ background: #b9a3ff; }}
  .lang-badge.lang-graded {{ background: #7CFC9A; }}
  .lang-badge.lang-zubehoer {{ background: #9aa0c0; }}
  .lang-badge.lang-unbekannt {{ background: #4a4f6a; color: #d5d8ea; }}
  .cond-badge {{
    display: inline-block; font-size: 0.62rem; font-weight: 800; padding: 2px 6px;
    border-radius: 5px; margin-left: 5px; vertical-align: middle; letter-spacing: .02em;
  }}
  .cond-badge.cond-case {{ background: #ff5a3c; color: #fff; }}
  .cond-badge.cond-bware {{ background: #6a5300; color: #ffe9a8; border: 1px solid #ffcb05; }}
  .cond-badge.cond-info {{ background: #2a3a5c; color: #a8cfff; }}
  .info {{ padding: 13px 15px 15px; display: flex; flex-direction: column; gap: 7px; flex: 1; }}
  .shop {{ font-size: 0.72rem; text-transform: uppercase; letter-spacing: .05em; color: var(--accent); font-weight: 700; }}
  .title {{ font-size: 0.92rem; line-height: 1.35; flex: 1; }}
  .prices {{ display: flex; gap: 8px; align-items: baseline; }}
  .new {{ font-size: 1.12rem; font-weight: 800; color: #7CFC9A; }}
  .old {{ font-size: 0.85rem; color: var(--muted); text-decoration: line-through; }}
  .compare-list {{ display: flex; flex-direction: column; gap: 4px; margin-top: 4px; }}
  .compare-row {{
    display: flex; justify-content: space-between; align-items: baseline;
    text-decoration: none; color: var(--text); font-size: 0.82rem;
    padding: 4px 6px; border-radius: 6px; background: #10142a;
  }}
  .compare-row:hover {{ background: #202547; }}
  .compare-row.cheapest {{ border: 1px solid #7CFC9A; }}
  .compare-row.cheapest .cprice {{ color: #7CFC9A; font-weight: 700; }}
  .cshop {{ color: var(--muted); }}
  .cprice .old {{ margin-left: 4px; }}
  .calendar-wrap {{ max-width: 1100px; margin: 20px auto 60px; padding: 0 20px; }}
  .cal-note {{ color: var(--muted); font-size: 0.82rem; margin-bottom: 14px; }}
  .quick-nav {{
    max-width: 1300px; margin: 14px auto 0; padding: 0 20px;
  }}
  .quick-nav-toggle {{
    width: 100%; text-align: left; padding: 12px 16px; border-radius: 10px;
    border: 1px solid #2a2f4a; background: var(--card); color: var(--text);
    font-size: 0.9rem; font-weight: 600; cursor: pointer;
  }}
  .quick-nav-body {{
    display: none; margin-top: 10px; padding: 14px 16px; border-radius: 10px;
    background: var(--card); border: 1px solid #2a2f4a;
    max-height: 340px; overflow-y: auto;
  }}
  .quick-nav-body.open {{ display: block; }}
  .qnav-lang {{ margin-bottom: 14px; }}
  .qnav-lang:last-child {{ margin-bottom: 0; }}
  .qnav-lang-title {{
    display: inline-block; font-size: 1rem; font-weight: 700; color: var(--text);
    text-decoration: none; margin-bottom: 6px;
  }}
  .qnav-lang-title:hover {{ color: var(--accent); }}
  .qnav-lang-title span {{ color: var(--muted); font-weight: 400; font-size: 0.85rem; }}
  .qnav-pills {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  .nav-pill {{
    font-size: 0.78rem; padding: 5px 10px; border-radius: 999px;
    background: #10142a; border: 1px solid #2a2f4a; color: var(--text);
    text-decoration: none; white-space: nowrap;
  }}
  .nav-pill:hover {{ border-color: var(--accent); color: var(--accent); }}
  .nav-pill span {{ color: var(--muted); }}
  #allproducts-wrap {{ max-width: 1300px; margin: 10px auto 60px; padding: 0 20px; }}
  .lang-block {{ margin-top: 40px; }}
  .lang-title {{
    font-size: 1.6rem; font-weight: 800; margin: 0 0 14px; padding: 10px 16px;
    background: linear-gradient(90deg, rgba(255,203,5,.12), transparent);
    border-left: 4px solid var(--accent); border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
    color: var(--text);
  }}
  .ptype-block {{ margin-top: 24px; }}
  .ptype-title {{
    font-size: 1.05rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: .04em; color: var(--accent); margin-bottom: 12px;
    display: inline-block; padding-bottom: 4px; border-bottom: 2px solid rgba(255,203,5,.3);
  }}
  .grid-compact {{
    grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
    gap: 12px; margin: 0;
  }}
  .grid-compact .title {{ font-size: 0.8rem; }}
  .grid-compact .new {{ font-size: 0.95rem; }}
  .cal-table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; table-layout: fixed; }}
  .cal-table th {{
    text-align: left; padding: 10px 12px; border-bottom: 2px solid var(--accent);
    color: var(--accent); font-size: 0.78rem; text-transform: uppercase;
  }}
  .cal-table th:nth-child(1), .cal-table td.cal-date {{ width: 110px; }}
  .cal-table th:nth-child(3), .cal-table td.cal-lang {{ width: 140px; }}
  .cal-table th:nth-child(4), .cal-table td.cal-status {{ width: 150px; }}
  .cal-table td {{ padding: 11px 12px; border-bottom: 1px solid #262b47; vertical-align: middle; }}
  .cal-table td.cal-date {{ white-space: nowrap; font-variant-numeric: tabular-nums; color: var(--muted); }}
  .cal-table td.cal-set {{ font-weight: 600; line-height: 1.35; }}
  .cal-table tr.cal-erschienen td.cal-set {{ color: var(--muted); font-weight: 400; }}
  .cal-status-badge {{
    display: inline-flex; align-items: center; gap: 5px; white-space: nowrap;
    padding: 4px 10px; border-radius: 20px; font-size: 0.78rem; font-weight: 600;
  }}
  .cal-badge-erschienen {{ background: rgba(255,255,255,.06); color: var(--muted); }}
  .cal-badge-bevorstehend {{ background: rgba(255,203,5,.15); color: var(--accent); }}
  .cal-badge-erwartet {{ background: rgba(124,252,154,.12); color: #7CFC9A; }}
  @media (max-width: 700px) {{
    .cal-table {{ table-layout: auto; font-size: 0.82rem; }}
    .cal-table th:nth-child(3), .cal-table td.cal-lang {{ display: none; }}
    .cal-table th:nth-child(1), .cal-table td.cal-date {{ width: auto; }}
  }}
  .manual {{
    max-width: 1100px; margin: 0 auto 60px; padding: 0 20px; color: var(--muted);
  }}
  .manual h2 {{ color: var(--text); font-size: 1.1rem; }}
  .manual ul {{ columns: 2; column-gap: 30px; }}
  .manual a {{ color: #9db4ff; }}
  .errorbox {{
    max-width: 1100px; margin: 20px auto 0; padding: 12px 18px;
    background: #2a2038; border: 1px solid #513a5c; border-radius: 10px;
    color: #e9c9ff; font-size: 0.85rem;
  }}
  .empty {{ text-align: center; color: var(--muted); padding: 60px 20px; grid-column: 1/-1; }}
  .rescan-btn {{
    margin-top: 16px; padding: 12px 24px; border-radius: 999px; border: none;
    background: linear-gradient(135deg, var(--accent), #f2b400); color: #1a1f36;
    font-weight: 800; font-size: 0.92rem; cursor: pointer;
    box-shadow: 0 4px 16px rgba(255,203,5,.3);
    transition: transform .15s ease, box-shadow .15s ease;
  }}
  .rescan-btn:hover {{ transform: translateY(-2px); box-shadow: 0 6px 20px rgba(255,203,5,.4); }}
  .rescan-btn:disabled {{ opacity: 0.5; cursor: wait; transform: none; }}
  .rescan-status {{ margin-top: 8px; font-size: 0.8rem; color: #dfe2f5; min-height: 1.2em; }}

  .page-layout {{
    display: flex; align-items: flex-start; gap: 20px;
    max-width: 1600px; margin: 18px auto 0; padding: 0 20px;
  }}
  .sidebar {{
    width: 360px; flex-shrink: 0; position: sticky; top: 12px;
    max-height: calc(100vh - 24px); overflow-y: auto;
  }}
  .sidebar-toggle {{
    display: none; width: 100%; text-align: left; padding: 12px 16px;
    border-radius: 10px; border: 1px solid #2a2f4a; background: var(--card);
    color: var(--text); font-size: 0.95rem; font-weight: 700; cursor: pointer;
    margin-bottom: 10px;
  }}
  .main-content {{ flex: 1; min-width: 0; }}
  .main-content .searchbar, .main-content .meta, .main-content nav.tabs,
  .main-content #allproducts-wrap, .main-content .grid, .main-content .calendar-wrap,
  .main-content .manual, .main-content .quick-nav {{
    max-width: none; margin-left: 0; margin-right: 0; padding-left: 0; padding-right: 0;
  }}
  .sidebar-right {{ order: 2; }}
  .new-items-hint {{ font-size: 0.82rem; color: #9298b8; line-height: 1.4; margin: 0 0 12px; }}
  .new-item-card {{
    background: var(--card); border: 1px solid #2a2f4a; border-radius: 10px;
    padding: 10px 12px; margin-bottom: 8px; display: flex; gap: 10px; align-items: center;
  }}
  .new-item-card img {{ width: 42px; height: 42px; object-fit: contain; border-radius: 6px; background: #fff; flex-shrink: 0; }}
  .new-item-card .nic-info {{ min-width: 0; flex: 1; }}
  .new-item-card .nic-title {{ font-size: 0.82rem; color: var(--text); line-height: 1.25; display: block; text-decoration: none; }}
  .new-item-card .nic-title:hover {{ color: var(--accent); }}
  .new-item-card .nic-meta {{ font-size: 0.75rem; color: #9298b8; margin-top: 3px; }}
  .new-item-card .nic-price {{ font-weight: 700; color: var(--accent); }}
  .new-item-card .nic-oldprice {{ text-decoration: line-through; color: #6b7094; margin-right: 4px; font-weight: 400; }}
  .new-items-section-title {{ font-size: 0.85rem; font-weight: 700; color: var(--text); margin: 14px 0 8px; }}
  .new-items-section-title:first-child {{ margin-top: 0; }}
  .last-scan-badge {{ font-size: 0.78rem; color: #9298b8; }}
  @media (max-width: 980px) {{
    .page-layout {{ flex-direction: column; }}
    .sidebar {{
      width: 100%; position: static; max-height: none;
    }}
    .sidebar-toggle {{ display: block; }}
    .sidebar-body {{ display: none; }}
    .sidebar-body.open {{ display: block; }}
  }}
  .progress-wrap {{
    max-width: 420px; margin: 12px auto 0; height: 10px; border-radius: 6px;
    background: #10142a; overflow: hidden; border: 1px solid #2a2f4a;
  }}
  .progress-bar {{
    height: 100%; width: 0%; background: linear-gradient(90deg, var(--accent), #7CFC9A);
    transition: width .3s ease; border-radius: 6px;
  }}
  .anniv-banner {{
    max-width: 1100px; margin: 18px auto 0; padding: 14px 18px;
    background: linear-gradient(90deg, #4a3b00, #2a2038); border: 1px solid var(--accent);
    border-radius: 12px; color: #ffe9a8; font-size: 0.9rem;
  }}
  .anniv-banner ul {{ margin: 8px 0 0; padding-left: 20px; }}
  .anniv-banner a {{ color: #ffe9a8; text-decoration: underline; }}
  .alert-banner-head {{ display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 8px; }}
  .alert-summary {{ font-size: 0.8rem; color: #dfc98a; }}
  .alert-add-row {{ display: flex; gap: 8px; margin: 10px 0; }}
  .alert-add-row input {{
    flex: 1; padding: 8px 12px; border-radius: 8px; border: 1px solid #6b5a1f;
    background: #1a1f36; color: var(--text); font-size: 0.85rem;
  }}
  .alert-add-row button {{
    padding: 8px 14px; border-radius: 8px; border: none; background: var(--accent);
    color: #1a1f36; font-weight: 700; cursor: pointer; font-size: 0.82rem; white-space: nowrap;
  }}
  .alerts-list {{ display: flex; flex-direction: column; gap: 10px; margin-top: 6px; }}
  .alert-card {{
    background: var(--bg-elevated); border: 1px solid #4a3b00; border-radius: var(--radius-sm);
    padding: 12px 14px; transition: border-color .15s ease;
  }}
  .alert-card.alert-hit {{ border-color: #7CFC9A; box-shadow: 0 0 0 1px rgba(124,252,154,.15); }}
  .alert-head {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
  .alert-kw {{ font-weight: 800; color: #ffe9a8; }}
  .alert-status {{ font-size: 0.8rem; color: var(--muted); }}
  .alert-card.alert-hit .alert-status {{ color: #7CFC9A; font-weight: 700; }}
  .alert-remove {{
    margin-left: auto; background: none; border: none; color: #ff8080;
    cursor: pointer; font-size: 0.9rem; padding: 3px 7px; border-radius: 6px;
    transition: background .15s ease;
  }}
  .alert-remove:hover {{ background: rgba(255,128,128,.15); }}
  .alert-item-list {{ list-style: none; margin: 8px 0 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }}
  .alert-item {{
    background: rgba(255,255,255,.03); border-radius: 8px; padding: 8px 10px;
    border: 1px solid rgba(255,255,255,.06);
  }}
  .alert-item-title {{
    font-size: 0.84rem; font-weight: 600; color: var(--text); margin-bottom: 6px;
    line-height: 1.3;
  }}
  .alert-item-shops {{ display: flex; flex-direction: column; gap: 3px; }}
  .alert-shop-row {{
    display: flex; justify-content: space-between; align-items: center;
    text-decoration: none; color: #cfd3ec; font-size: 0.8rem;
    padding: 3px 6px; border-radius: 6px; transition: background .12s ease;
  }}
  .alert-shop-row:hover {{ background: rgba(255,203,5,.1); color: var(--text); }}
  .alert-shop-name {{ display: flex; align-items: center; gap: 4px; }}
  .alert-shop-price {{ font-weight: 700; color: #7CFC9A; white-space: nowrap; }}
  .alert-variant-count {{ font-weight: 400; color: #9298b8; font-size: 0.78rem; }}
  .alert-variant-list {{ display: flex; flex-direction: column; gap: 2px; max-height: 260px; overflow-y: auto; }}
  .alert-variant-row {{
    display: flex; justify-content: space-between; align-items: center; gap: 8px;
    text-decoration: none; color: #cfd3ec; font-size: 0.78rem;
    padding: 4px 6px; border-radius: 6px; transition: background .12s ease;
  }}
  .alert-variant-row:hover {{ background: rgba(255,203,5,.1); color: var(--text); }}
  .alert-variant-name {{ display: flex; align-items: center; gap: 4px; min-width: 0; }}
  .alert-variant-price {{ font-weight: 700; color: #7CFC9A; white-space: nowrap; flex-shrink: 0; }}
  .alert-lang-group {{ margin-top: 10px; }}
  .alert-lang-title {{
    font-size: 0.78rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: .04em; color: var(--accent); margin-bottom: 2px;
  }}
  .alert-waiting {{ color: var(--muted); font-size: 0.82rem; margin: 6px 0 0; }}
  .alert-hint {{ color: #565b7a; font-size: 0.68rem; margin: 10px 0 0; opacity: 0.8; line-height: 1.4; }}
  .alert-local-status {{
    display: none; font-size: 0.82rem; color: var(--accent); margin: 8px 0;
    padding: 8px 10px; background: rgba(255,203,5,.1); border-radius: 8px;
    border: 1px solid rgba(255,203,5,.3);
  }}
  .alert-local-status.active {{ display: block; }}
  .flag-wrong-btn {{
    display: block; width: 100%; margin-top: 10px; padding: 6px 8px;
    background: rgba(255,80,80,.08); border: 1px solid rgba(255,80,80,.3);
    color: #ff8a8a; border-radius: 6px; font-size: 0.7rem; cursor: pointer;
    transition: background .15s ease;
  }}
  .flag-wrong-btn:hover {{ background: rgba(255,80,80,.2); color: #fff; }}
  .flag-wrong-btn:disabled {{ opacity: 0.5; cursor: default; }}
  .correction-list {{ list-style: none; margin: 8px 0 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }}
  .correction-item {{
    display: flex; justify-content: space-between; align-items: center; gap: 8px;
    background: rgba(255,255,255,.03); border-radius: 8px; padding: 6px 10px;
    font-size: 0.72rem; border: 1px solid rgba(255,255,255,.06);
  }}
  .correction-pair {{ color: #a9adca; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .correction-pair a {{ color: #a9adca; }}
  .correction-undo-btn {{
    flex-shrink: 0; background: rgba(124,252,154,.1); border: 1px solid rgba(124,252,154,.3);
    color: #7CFC9A; border-radius: 6px; padding: 3px 8px; font-size: 0.68rem; cursor: pointer;
  }}
  .correction-undo-btn:hover {{ background: rgba(124,252,154,.25); }}
  .hover-preview {{
    display: none; position: fixed; z-index: 9999; pointer-events: none;
    background: #10142a; border: 2px solid var(--accent); border-radius: 10px;
    padding: 6px; box-shadow: 0 8px 24px rgba(0,0,0,.5);
  }}
  .hover-preview img {{
    display: block; width: 200px; height: 200px; object-fit: contain;
    border-radius: 6px;
  }}
  .price-history-btn {{
    background: transparent; border: 1px solid #3a3f5c; color: #9298b8;
    border-radius: 6px; padding: 2px 6px; font-size: 0.72rem; cursor: pointer;
    margin-left: 6px; flex-shrink: 0; transition: all .15s ease;
  }}
  .price-history-btn:hover {{ border-color: var(--accent); color: var(--accent); }}
  .price-history-modal-overlay {{
    display: none; position: fixed; inset: 0; background: rgba(0,0,0,.6);
    z-index: 10000; align-items: center; justify-content: center;
  }}
  .price-history-modal-overlay.open {{ display: flex; }}
  .price-history-modal {{
    background: var(--card); border: 1px solid #3a3f5c; border-radius: 14px;
    padding: 20px; width: min(640px, 92vw); max-height: 85vh; overflow-y: auto;
    position: relative;
  }}
  .price-history-modal-close {{
    position: absolute; top: 12px; right: 14px; background: transparent; border: none;
    color: #9298b8; font-size: 1.3rem; cursor: pointer; line-height: 1;
  }}
  .price-history-modal-close:hover {{ color: var(--text); }}
  .price-history-modal h3 {{ margin: 0 0 4px; font-size: 1rem; padding-right: 30px; }}
  .price-history-modal .ph-note {{ font-size: 0.78rem; color: #9298b8; margin: 0 0 14px; }}
  .price-history-chart-wrap {{ position: relative; height: 280px; }}
</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
</head>
<body>
<header>
  <h1>🔥 Pokemon TCG – Alle Produkte, Angebote &amp; Vorbestellungen (Deutschland)</h1>
  <p>{len(all_products)} verfügbare Produkte gesamt · {len(all_offers)} reduzierte · {len(all_preorders)} vorbestellbare Pokemon-Artikel aus {shop_count} automatisch gescannten Shops</p>
  <button id="rescanBtn" class="rescan-btn">🔄 Neue Angebote suchen</button>
  <div class="progress-wrap" id="progressWrap" style="display:none;">
    <div class="progress-bar" id="progressBar"></div>
  </div>
  <div id="rescanStatus" class="rescan-status"></div>
</header>

<div class="price-history-modal-overlay" id="priceHistoryOverlay">
  <div class="price-history-modal">
    <button class="price-history-modal-close" id="priceHistoryClose">✕</button>
    <h3 id="priceHistoryTitle">Preisverlauf</h3>
    <p class="ph-note">Eigenständig ab dem ersten Scan gesammelt (kein Fremddienst) - wächst mit jedem Tag, an dem gescannt wird.</p>
    <div class="price-history-chart-wrap">
      <canvas id="priceHistoryCanvas"></canvas>
    </div>
    <p class="ph-note" id="priceHistoryEmpty" style="display:none;">Noch keine Verlaufsdaten für dieses Produkt - schau in ein paar Tagen wieder vorbei.</p>
  </div>
</div>
<div class="page-layout">
<aside class="sidebar" id="alertsSidebar">
  <button class="sidebar-toggle" id="sidebarToggle">🔔 Alarme <span id="sidebarToggleIcon">▾</span></button>
  <div class="sidebar-body" id="sidebarBody">
    {alerts_banner}
    {corrections_html}
  </div>
</aside>
<main class="main-content">
<div class="meta">Zuletzt gescannt am <span id="lastScanTime">{esc(scan_time)}</span> · Für den "Neu suchen"-Button und automatische Hintergrund-Scans muss das Skript mit <code>python3 scan.py --serve</code> laufen. Ohne Server: Skript manuell erneut ausführen (<code>python3 scan.py</code>).</div>
{errors_html}

<div class="searchbar">
  <input type="text" id="searchInput" placeholder="🔍 Nach Set, Produkt, Shop oder Kalender suchen (z. B. „Display", „Elite Trainer Box", „God of Cards")…">
</div>

<nav class="tabs">
  <button id="tab-allproducts" class="active" data-tab="allproducts">📦 Alle Produkte (<span id="count-allproducts">{products_total}</span>)</button>
  <button id="tab-expensive" data-tab="expensive">💎 Selten und Teuer ab 1.000 € (<span id="count-expensive">{expensive_total}</span>)</button>
  <button id="tab-offers" data-tab="offers">💰 Angebote (<span id="count-offers">{len(all_offers)}</span>)</button>
  <button id="tab-preorders" data-tab="preorders">🕒 Vorbestellungen (<span id="count-preorders">{len(all_preorders)}</span>)</button>
  <button id="tab-calendar" data-tab="calendar">📅 Release-Kalender</button>
</nav>

<section id="section-allproducts" class="active">
  <div class="quick-nav" id="quickNav">
    <button class="quick-nav-toggle" id="quickNavToggle">🧭 Schnellnavigation (Sprache &amp; Kategorie) ▾</button>
    <div class="quick-nav-body" id="quickNavBody">
      {quick_nav_html}
    </div>
  </div>
  <div id="allproducts-wrap">
    {all_products_html}
    <p class="no-results" id="allproducts-no-results">Keine Treffer für diese Suche.</p>
  </div>
</section>

<section id="section-offers">
  <div class="grid" id="grid-offers">
    {offers_html}
    <div class="no-results">Keine Treffer für diese Suche.</div>
  </div>
</section>

<section id="section-preorders">
  <div class="grid" id="grid-preorders">
    {preorders_html}
    <div class="no-results">Keine Treffer für diese Suche.</div>
  </div>
</section>

<section id="section-expensive">
  <p class="cal-note">💎 Alle Artikel ab 1.000 € - typischerweise Sealed Cases, sehr seltene Sammlerstücke oder Massen-Bundles. Werden hier gesondert gelistet, damit sie die normale Übersicht nicht verzerren.</p>
  <div id="expensive-wrap">
    {expensive_html}
    <p class="no-results" id="expensive-no-results">Keine Treffer für diese Suche.</p>
  </div>
</section>

<section id="section-calendar">
  <div class="calendar-wrap">
    <p class="cal-note">📌 Manuell zusammengestellt (Stand der Recherche: Juli 2026) - keine Live-Daten. Deutsche Releases erscheinen i. d. R. gleichzeitig mit dem internationalen Release. Termine für Spezial-/Chinesische Sets teils noch nicht offiziell bestätigt. Neueste zuerst.</p>
    <table class="cal-table">
      <thead><tr><th>Datum</th><th>Set</th><th>Sprache</th><th>Status</th></tr></thead>
      <tbody id="calendar-body">
        {calendar_rows}
      </tbody>
    </table>
    <p class="no-results" id="calendar-no-results">Keine Treffer für diese Suche.</p>
  </div>
</section>

{manual_section}
</main>
<aside class="sidebar sidebar-right" id="newItemsSidebar">
  <button class="sidebar-toggle" id="newItemsSidebarToggle">🆕 Neu seit letztem Scan <span id="newItemsSidebarIcon">▾</span></button>
  <div class="sidebar-body" id="newItemsSidebarBody">
    <p class="new-items-hint" id="newItemsHint">Läuft nur mit <code>python3 scan.py --serve</code> - der Server scannt dann automatisch alle paar Minuten im Hintergrund weiter nach, ohne diese Seite neu zu laden. Zeigt neue Artikel, günstiger gewordene Artikel und neue Angebote der letzten 48 Stunden.</p>
    <div id="newItemsContent"></div>
  </div>
</aside>
</div>

<script>
const PLACEHOLDER_IMG = {placeholder_js};
// Wird die Seite per Doppelklick (file://) geoeffnet, muessen die Buttons
// den im Hintergrund laufenden Server unter seiner vollen Adresse ansprechen.
// Laeuft die Seite direkt ueber den Server (http://...), reichen relative Pfade.
const SERVER_BASE = (location.protocol === 'file:') ? 'http://127.0.0.1:{server_port}' : '';
if ('serviceWorker' in navigator) {{
  window.addEventListener('load', function() {{
    navigator.serviceWorker.register('sw.js').catch(function() {{}});
  }});
}}

// -- Bild-Fallback (per Delegation statt inline onerror) -------------------
document.addEventListener('error', function(e) {{
  const el = e.target;
  if (el && el.tagName === 'IMG' && el.src !== PLACEHOLDER_IMG) {{
    el.src = PLACEHOLDER_IMG;
  }}
}}, true);

// -- Tabs --------------------------------------------------------------
function showTab(name) {{
  document.getElementById('section-allproducts').classList.toggle('active', name === 'allproducts');
  document.getElementById('section-offers').classList.toggle('active', name === 'offers');
  document.getElementById('section-preorders').classList.toggle('active', name === 'preorders');
  document.getElementById('section-expensive').classList.toggle('active', name === 'expensive');
  document.getElementById('section-calendar').classList.toggle('active', name === 'calendar');
  document.getElementById('tab-allproducts').classList.toggle('active', name === 'allproducts');
  document.getElementById('tab-offers').classList.toggle('active', name === 'offers');
  document.getElementById('tab-preorders').classList.toggle('active', name === 'preorders');
  document.getElementById('tab-expensive').classList.toggle('active', name === 'expensive');
  document.getElementById('tab-calendar').classList.toggle('active', name === 'calendar');
}}
document.querySelectorAll('nav.tabs button[data-tab]').forEach(function(btn) {{
  btn.addEventListener('click', function() {{ showTab(btn.getAttribute('data-tab')); }});
}});

// -- Suche (Angebote, Vorbestellungen, Kalender) ------------------------
function filterCards() {{
  const query = document.getElementById('searchInput').value.trim().toLowerCase();

  ['grid-offers', 'grid-preorders'].forEach(function(gridId) {{
    const grid = document.getElementById(gridId);
    const cards = grid.querySelectorAll('.card');
    let visibleCount = 0;
    cards.forEach(function(card) {{
      const match = !query || card.getAttribute('data-search').includes(query);
      card.style.display = match ? '' : 'none';
      if (match) visibleCount++;
    }});
    const noResults = grid.querySelector('.no-results');
    if (noResults) {{
      noResults.style.display = (visibleCount === 0 && cards.length > 0) ? 'block' : 'none';
    }}
    const countEl = document.getElementById(gridId === 'grid-offers' ? 'count-offers' : 'count-preorders');
    if (countEl) {{ countEl.textContent = query ? visibleCount : cards.length; }}
  }});

  const calRows = document.querySelectorAll('#calendar-body tr');
  let calVisible = 0;
  calRows.forEach(function(row) {{
    const match = !query || row.getAttribute('data-search').includes(query);
    row.style.display = match ? '' : 'none';
    if (match) calVisible++;
  }});
  const calNoResults = document.getElementById('calendar-no-results');
  if (calNoResults) {{
    calNoResults.style.display = (calVisible === 0 && calRows.length > 0) ? 'block' : 'none';
  }}

  // "Alle Produkte"- und "Selten und Teuer"-Tab: Karten filtern, dann
  // leere Typ-/Sprachgruppen ausblenden (gleiche Struktur, daher gleiche
  // Filterlogik fuer beide Wraps).
  [['allproducts-wrap', 'allproducts-no-results', 'count-allproducts'],
   ['expensive-wrap', 'expensive-no-results', null]].forEach(function(cfg) {{
    const wrap = document.getElementById(cfg[0]);
    if (!wrap) return;
    let visibleTotal = 0;
    const cards = wrap.querySelectorAll('.card');
    cards.forEach(function(card) {{
      const match = !query || card.getAttribute('data-search').includes(query);
      card.style.display = match ? '' : 'none';
      if (match) visibleTotal++;
    }});
    wrap.querySelectorAll('.ptype-block').forEach(function(block) {{
      const visible = block.querySelectorAll('.card:not([style*="display: none"])').length;
      block.style.display = visible > 0 ? '' : 'none';
    }});
    wrap.querySelectorAll('.lang-block').forEach(function(block) {{
      const visible = block.querySelectorAll('.card:not([style*="display: none"])').length;
      block.style.display = visible > 0 ? '' : 'none';
    }});
    const noResults = document.getElementById(cfg[1]);
    if (noResults) {{
      noResults.style.display = (visibleTotal === 0 && cards.length > 0) ? 'block' : 'none';
    }}
    if (cfg[2]) {{
      const countEl = document.getElementById(cfg[2]);
      if (countEl) {{ countEl.textContent = query ? visibleTotal : cards.length; }}
    }}
  }});
}}
document.getElementById('searchInput').addEventListener('input', filterCards);

// -- Neu suchen / Rescan --------------------------------------------------
function pollProgress(onDone, extraStatusEl) {{
  const wrap = document.getElementById('progressWrap');
  const bar = document.getElementById('progressBar');
  const status = document.getElementById('rescanStatus');
  wrap.style.display = 'block';

  const interval = setInterval(function() {{
    fetch(SERVER_BASE + '/progress')
      .then(function(resp) {{ return resp.json(); }})
      .then(function(data) {{
        const pct = data.total > 0 ? Math.round((data.done / data.total) * 100) : 0;
        bar.style.width = pct + '%';
        if (data.running) {{
          const msg = '⏳ Scanne Shop ' + data.done + ' von ' + data.total +
            (data.current_shop ? ' (zuletzt: ' + data.current_shop + ')' : '') + ' ...';
          status.textContent = msg;
          if (extraStatusEl) extraStatusEl.textContent = msg;
        }} else if (data.total > 0) {{
          bar.style.width = '100%';
          const doneMsg = '✅ Fertig! Seite wird neu geladen ...';
          status.textContent = doneMsg;
          if (extraStatusEl) extraStatusEl.textContent = doneMsg;
          clearInterval(interval);
          setTimeout(onDone, 600);
        }}
      }})
      .catch(function() {{ /* kurzzeitiger Aussetzer beim Pollen ignorieren */ }});
  }}, 700);
}}

function rescan() {{
  const btn = document.getElementById('rescanBtn');
  const status = document.getElementById('rescanStatus');
  const bar = document.getElementById('progressBar');
  btn.disabled = true;
  bar.style.width = '0%';
  status.textContent = '⏳ Suche wird gestartet ...';
  fetch(SERVER_BASE + '/rescan', {{ method: 'POST' }})
    .then(function(resp) {{
      if (!resp.ok && resp.status !== 202) throw new Error('Server-Fehler');
      pollProgress(function() {{ window.location.href = window.location.pathname + '?t=' + Date.now(); }});
    }})
    .catch(function() {{
      document.getElementById('progressWrap').style.display = 'none';
      status.textContent = '⚠️ Kein lokaler Server aktiv. Starte ihn mit: python3 scan.py --serve, oder führe scan.py manuell erneut aus.';
      btn.disabled = false;
    }});
}}
document.getElementById('rescanBtn').addEventListener('click', rescan);

// -- Schnellnavigation auf-/zuklappen -------------------------------------
// -- Sidebar (Alarme) auf schmalen Bildschirmen auf-/zuklappen -----------
const sidebarToggle = document.getElementById('sidebarToggle');
const sidebarBody = document.getElementById('sidebarBody');
if (sidebarToggle) {{
  sidebarToggle.addEventListener('click', function() {{
    sidebarBody.classList.toggle('open');
  }});
}}

// -- "Neu seit letztem Scan" Seitenleiste: pollt den Server, OHNE die
// Seite neu zu laden - damit das eigene Suchen/Browsen nicht gestoert wird.
const newItemsToggle = document.getElementById('newItemsSidebarToggle');
const newItemsBody = document.getElementById('newItemsSidebarBody');
if (newItemsToggle) {{
  newItemsToggle.addEventListener('click', function() {{
    newItemsBody.classList.toggle('open');
  }});
}}

function escHtml(s) {{
  const d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}}

function renderNewItemCard(p, oldPrice) {{
  const img = p.image || PLACEHOLDER_IMG;
  const priceHtml = oldPrice
    ? `<span class="nic-oldprice">${{oldPrice.toFixed(2)}} €</span><span class="nic-price">${{p.price.toFixed(2)}} €</span>`
    : `<span class="nic-price">${{p.price.toFixed(2)}} €</span>`;
  return `<div class="new-item-card">
    <img src="${{escHtml(img)}}" loading="lazy">
    <div class="nic-info">
      <a class="nic-title preview-link" href="${{escHtml(p.url)}}" target="_blank" rel="noopener" data-preview-img="${{escHtml(img)}}">${{escHtml(p.title)}}</a>
      <div class="nic-meta">${{escHtml(p.shop)}} · ${{priceHtml}}</div>
    </div>
  </div>`;
}}

// -- Spezial-Alarm: rotes Popup bei einem ganz bestimmten Produkt --------
// Bleibt so lange stehen, bis der Nutzer es manuell wegklickt (Zustand
// wird pro Produkt-URL in localStorage gemerkt, ueberlebt also auch einen
// Seiten-Reload).
// -- Preisverlauf-Modal (eigenstaendig gesammelte Daten, kein Fremddienst) -
let priceHistoryChart = null;
async function showPriceHistory(key, title) {{
  const overlay = document.getElementById('priceHistoryOverlay');
  const titleEl = document.getElementById('priceHistoryTitle');
  const emptyEl = document.getElementById('priceHistoryEmpty');
  const canvas = document.getElementById('priceHistoryCanvas');
  titleEl.textContent = '📈 ' + title;
  overlay.classList.add('open');
  canvas.style.display = 'none';
  emptyEl.style.display = 'none';
  try {{
    const res = await fetch(SERVER_BASE + '/price-history?key=' + encodeURIComponent(key), {{cache: 'no-store'}});
    const data = await res.json();
    const history = data.history || [];
    if (history.length < 2) {{
      emptyEl.style.display = 'block';
      return;
    }}
    canvas.style.display = 'block';
    if (priceHistoryChart) {{ priceHistoryChart.destroy(); }}
    priceHistoryChart = new Chart(canvas.getContext('2d'), {{
      type: 'line',
      data: {{
        labels: history.map(h => h.date),
        datasets: [{{
          label: 'Preis (€)',
          data: history.map(h => h.price),
          borderColor: '#ffcb05',
          backgroundColor: 'rgba(255,203,5,.12)',
          fill: true,
          tension: 0.15,
          pointRadius: 3,
        }}]
      }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{ legend: {{ display: false }} }},
        scales: {{
          y: {{ ticks: {{ color: '#9298b8' }}, grid: {{ color: '#262b47' }} }},
          x: {{ ticks: {{ color: '#9298b8', maxRotation: 45 }}, grid: {{ display: false }} }}
        }}
      }}
    }});
  }} catch (e) {{
    emptyEl.textContent = 'Preisverlauf konnte nicht geladen werden (Server nicht erreichbar - nur mit --serve verfügbar).';
    emptyEl.style.display = 'block';
  }}
}}
document.getElementById('priceHistoryClose').addEventListener('click', function() {{
  document.getElementById('priceHistoryOverlay').classList.remove('open');
}});
document.getElementById('priceHistoryOverlay').addEventListener('click', function(e) {{
  if (e.target === this) this.classList.remove('open');
}});
document.addEventListener('click', function(e) {{
  const btn = e.target.closest('.price-history-btn');
  if (btn) {{
    e.preventDefault(); e.stopPropagation();
    showPriceHistory(btn.getAttribute('data-key'), btn.getAttribute('data-title'));
  }}
}});

async function pollRecentChanges() {{
  try {{
    const res = await fetch(SERVER_BASE + '/recent-changes', {{cache: 'no-store'}});
    if (!res.ok) return;
    const data = await res.json();
    const hint = document.getElementById('newItemsHint');
    const content = document.getElementById('newItemsContent');
    if (!content) return;
    const lastScanEl = document.getElementById('lastScanTime');
    if (lastScanEl && data.last_scan) {{
      lastScanEl.textContent = data.last_scan;
    }}
    const newItems = data.new_items || [];
    const priceDrops = data.price_drops || [];
    const newOffers48h = data.new_offers_48h || [];
    if (!newItems.length && !priceDrops.length && !newOffers48h.length) {{
      if (hint) hint.style.display = '';
      content.innerHTML = '';
      return;
    }}
    if (hint) hint.style.display = 'none';
    let html = '';
    if (newOffers48h.length) {{
      html += `<div class="new-items-section-title">🔥 Neue Angebote (48h) (${{newOffers48h.length}})</div>`;
      html += newOffers48h.map(p => renderNewItemCard(p)).join('');
    }}
    if (newItems.length) {{
      html += `<div class="new-items-section-title">🆕 Neu (${{newItems.length}})</div>`;
      html += newItems.map(p => renderNewItemCard(p)).join('');
    }}
    if (priceDrops.length) {{
      html += `<div class="new-items-section-title">📉 Günstiger geworden (${{priceDrops.length}})</div>`;
      html += priceDrops.map(p => renderNewItemCard(p, p.old_price)).join('');
    }}
    content.innerHTML = html;
  }} catch (e) {{
    // Server nicht erreichbar (kein --serve) - Hinweistext bleibt einfach stehen
  }}
}}
if (document.getElementById('newItemsContent')) {{
  pollRecentChanges();
  setInterval(pollRecentChanges, 30000);
}}

// -- Bildvorschau beim Hover ueber Alarm-Links ----------------------------
(function() {{
  const tip = document.createElement('div');
  tip.id = 'hoverPreview';
  tip.className = 'hover-preview';
  document.body.appendChild(tip);


  document.addEventListener('mouseover', function(e) {{
    const link = e.target.closest('.preview-link');
    if (!link) return;
    const imgUrl = link.getAttribute('data-preview-img');
    if (!imgUrl) return;
    tip.innerHTML = '<img src="' + imgUrl + '" referrerpolicy="no-referrer">';
    tip.style.display = 'block';
  }});
  document.addEventListener('mousemove', function(e) {{
    if (tip.style.display !== 'block') return;
    const margin = 18;
    let x = e.clientX + margin;
    let y = e.clientY + margin;
    if (x + 200 > window.innerWidth) {{ x = e.clientX - 200 - margin; }}
    if (y + 200 > window.innerHeight) {{ y = e.clientY - 200 - margin; }}
    tip.style.left = x + 'px';
    tip.style.top = y + 'px';
  }});
  document.addEventListener('mouseout', function(e) {{
    const link = e.target.closest('.preview-link');
    if (!link) return;
    tip.style.display = 'none';
  }});
}})();

const qnavToggle = document.getElementById('quickNavToggle');
const qnavBody = document.getElementById('quickNavBody');
if (qnavToggle) {{
  qnavToggle.addEventListener('click', function() {{
    qnavBody.classList.toggle('open');
  }});
  // Nach Klick auf einen Sprung-Link automatisch wieder einklappen
  qnavBody.querySelectorAll('a').forEach(function(a) {{
    a.addEventListener('click', function() {{
      setTimeout(function() {{ qnavBody.classList.remove('open'); }}, 150);
    }});
  }});
}}

// -- Alarme verwalten (nur mit --serve aktiv) -----------------------------
function alertRequest(action, keyword) {{
  const localStatus = document.getElementById('alertLocalStatus');
  const addBtn = document.getElementById('addAlertBtn');
  if (localStatus) {{
    localStatus.textContent = action === 'add'
      ? '⏳ „' + keyword + '" wird hinzugefügt – Scan läuft, bitte warten …'
      : '⏳ „' + keyword + '" wird entfernt – Scan läuft, bitte warten …';
    localStatus.classList.add('active');
  }}
  if (addBtn) addBtn.disabled = true;
  fetch(SERVER_BASE + '/alerts', {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{ action: action, keyword: keyword }})
  }})
    .then(function(resp) {{
      if (!resp.ok && resp.status !== 202) throw new Error('Server-Fehler');
      document.getElementById('rescanBtn').disabled = true;
      pollProgress(function() {{ window.location.href = window.location.pathname + '?t=' + Date.now(); }}, localStatus);
    }})
    .catch(function() {{
      if (addBtn) addBtn.disabled = false;
      if (action === 'remove') {{
        // Kein Server aktiv: Alarm wenigstens aus der aktuellen Ansicht entfernen.
        const card = document.querySelector('.alert-card[data-keyword="' + keyword.replace(/"/g, '\\\\"') + '"]');
        if (card) {{ card.remove(); }}
        if (localStatus) {{
          localStatus.textContent = '⚠️ Kein Server aktiv – nur vorübergehend entfernt (siehe Hinweis unten).';
        }}
        alert('Alarm „' + keyword + '" wurde aus dieser Ansicht entfernt.\\n\\n' +
              'Das ist aber nur vorübergehend (bis zum nächsten Neuladen)! Damit es dauerhaft gespeichert wird:\\n' +
              '- entweder alerts.json öffnen und die Zeile mit "' + keyword + '" löschen,\\n' +
              '- oder das Skript mit "python3 scan.py --serve" starten, dann funktioniert der Button direkt.');
      }} else {{
        if (localStatus) {{
          localStatus.textContent = '⚠️ Kein Server aktiv – Alarm wurde NICHT gespeichert.';
        }}
        alert('⚠️ Kein lokaler Server aktiv. Starte ihn mit: python3 scan.py --serve\\n\\n' +
              'Ohne Server: alerts.json direkt bearbeiten (Stichwort als neue Zeile hinzufügen) und scan.py erneut ausführen.');
      }}
    }});
}}
document.getElementById('addAlertBtn').addEventListener('click', function() {{
  const input = document.getElementById('newAlertInput');
  const kw = input.value.trim();
  if (kw) {{ alertRequest('add', kw); }}
}});
document.getElementById('newAlertInput').addEventListener('keydown', function(e) {{
  if (e.key === 'Enter') {{ document.getElementById('addAlertBtn').click(); }}
}});
document.querySelectorAll('[data-remove-keyword]').forEach(function(btn) {{
  btn.addEventListener('click', function() {{
    alertRequest('remove', btn.getAttribute('data-remove-keyword'));
  }});
}});

// -- "Falsch zusammengefuehrt?" melden -------------------------------------
document.querySelectorAll('.flag-wrong-btn').forEach(function(btn) {{
  btn.addEventListener('click', function(e) {{
    e.preventDefault();
    e.stopPropagation();
    if (!confirm('Diese Angebote wirklich als "kein gleiches Produkt" melden?\\n\\n' +
                 'Sie werden dann bei JEDEM zukuenftigen Scan automatisch getrennt ' +
                 '- dauerhaft gespeichert, unabhaengig von der Text-/Bild-Erkennung.')) {{
      return;
    }}
    let urls;
    try {{ urls = JSON.parse(btn.getAttribute('data-urls')); }} catch (err) {{ return; }}
    btn.disabled = true;
    btn.textContent = '⏳ wird gespeichert ...';
    fetch(SERVER_BASE + '/flag_wrong', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ urls: urls }})
    }})
      .then(function(resp) {{
        if (!resp.ok && resp.status !== 202) throw new Error('Server-Fehler');
        btn.textContent = '⏳ gespeichert - Scan läuft ...';
        pollProgress(function() {{ window.location.href = window.location.pathname + '?t=' + Date.now(); }});
      }})
      .catch(function() {{
        btn.disabled = false;
        btn.textContent = '🚫 Falsch zusammengeführt?';
        alert('⚠️ Kein lokaler Server aktiv. Starte ihn mit: python3 scan.py --serve\\n\\n' +
              'Ohne Server kann diese Meldung nicht dauerhaft gespeichert werden.');
      }});
  }});
}});

// -- "Falsch zusammengeführt"-Meldung rückgängig machen --------------------
document.querySelectorAll('.correction-undo-btn').forEach(function(btn) {{
  btn.addEventListener('click', function(e) {{
    e.preventDefault();
    e.stopPropagation();
    let pair;
    try {{ pair = JSON.parse(btn.getAttribute('data-pair')); }} catch (err) {{ return; }}
    btn.disabled = true;
    btn.textContent = '⏳ ...';
    fetch(SERVER_BASE + '/unflag_wrong', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ pair: pair }})
    }})
      .then(function(resp) {{
        if (!resp.ok && resp.status !== 202) throw new Error('Server-Fehler');
        btn.textContent = '⏳ Scan läuft ...';
        pollProgress(function() {{ window.location.href = window.location.pathname + '?t=' + Date.now(); }});
      }})
      .catch(function() {{
        btn.disabled = false;
        btn.textContent = '↩ rückgängig';
        alert('⚠️ Kein lokaler Server aktiv. Starte ihn mit: python3 scan.py --serve');
      }});
  }});
}});
</script>

</body>
</html>"""


MAX_WORKERS = 10  # wie viele Shops gleichzeitig abgefragt werden

# -- Erkennung einer IP-weiten Blockierung (Shopify-Botschutz) --------------
# Wenn VIELE Shops im selben Scan mit 403/429 antworten, ist praktisch immer
# die eigene IP voruebergehend gesperrt (zu viele Scans in zu kurzer Zeit) -
# nicht ein Problem einzelner Shops. Dann bringt sofortiges Weiter-Scannen
# nichts, sondern verlaengert die Sperre nur. Der Hintergrund-Scan pausiert
# in dem Fall automatisch fuer eine Abkuehlphase.
_blocked_shops_lock = threading.Lock()
_BLOCKED_SHOPS_THIS_SCAN = set()
MASS_BLOCK_THRESHOLD = 8          # ab so vielen 403/429-Shops gilt: IP-Sperre
MASS_BLOCK_COOLDOWN_MINUTES = 60  # so lange pausiert der Hintergrund-Scan dann
_scan_cooldown_until = 0.0


def _register_blocked_shop(shop_name):
    with _blocked_shops_lock:
        _BLOCKED_SHOPS_THIS_SCAN.add(shop_name)


def _reset_blocked_shops():
    with _blocked_shops_lock:
        _BLOCKED_SHOPS_THIS_SCAN.clear()


def _blocked_shop_count():
    with _blocked_shops_lock:
        return len(_BLOCKED_SHOPS_THIS_SCAN)


def _total_shop_count():
    """Gesamtzahl der tatsaechlich gescannten Shops - inkl. der optionalen
    Playwright-Shops NUR wenn Playwright installiert ist."""
    js_count = len(WOOCOMMERCE_JS_PROTECTED_SHOPS) if _PLAYWRIGHT_AVAILABLE else 0
    custom_count = len(CUSTOM_SCRAPER_SHOPS) if _PLAYWRIGHT_AVAILABLE else 0
    return len(SHOPS) + len(WOOCOMMERCE_SHOPS) + js_count + custom_count
DEFAULT_SERVER_PORT = 8765  # muss mit --port uebereinstimmen, falls geaendert

# Globaler Fortschritts-Status, den der lokale Server per /progress
# ausliefert, damit die Web-Seite einen echten Fortschrittsbalken zeigen kann.
_progress_lock = threading.Lock()
SCAN_PROGRESS = {"running": False, "done": 0, "total": 0, "current_shop": ""}

# Verfolgt Aenderungen zwischen aufeinanderfolgenden Scans (neue Artikel,
# guenstiger gewordene Artikel) fuer die "Neu"-Seitenleiste rechts in der
# Web-Seite. _PREVIOUS_SNAPSHOT lebt nur im Arbeitsspeicher dieses
# Serverprozesses - beim ALLERERSTEN Scan nach dem Start gibt es daher noch
# keinen Vergleichspunkt (bewusst leer, nicht "alles ist neu").
_changes_lock = threading.Lock()
RECENT_CHANGES = {"new_items": [], "price_drops": [], "new_offers_48h": [], "last_scan": None}

_PREVIOUS_SNAPSHOT = {}

OFFERS_HISTORY_FILE = "offers_history.json"
_OFFERS_HISTORY_MAX_AGE_DAYS = 7  # Eintraege werden nach 7 Tagen aus der Datei entfernt


PRICE_HISTORY_FILE = "price_history.json"
_PRICE_HISTORY_MAX_AGE_DAYS = 400  # etwas mehr als 12 Monate, damit die Anzeige "letzte 12 Monate" immer voll ist


def _price_group_key(language, urls):
    """Stabiler Schluessel fuer eine Produkt+Sprache-Gruppe: haengt von der
    Sprache und der Menge der aktuell dazugehoerenden Shop-URLs ab (bleibt
    stabil, solange sich die Shop-Zusammensetzung der Gruppe nicht
    aendert - kommt ein neuer Shop fuer das gleiche Produkt dazu, faengt
    der Verlauf fuer diese Gruppe neu an, was ein akzeptabler Kompromiss
    ist, da es keine dauerhafte produktuebergreifende ID gibt)."""
    joined = "|".join(sorted(urls))
    digest = hashlib.md5(joined.encode("utf-8")).hexdigest()[:16]
    return f"{language}:{digest}"


def _update_price_history_grouped(price_points):
    """Fuehrt eine PERSISTENTE (dateibasierte) Preishistorie - EINMAL PRO
    PRODUKT+SPRACHE (nicht pro einzelnem Shop-Eintrag), jeweils der
    GUENSTIGSTE Preis der Gruppe an diesem Tag. price_points ist eine
    Liste von {{"key":, "price":, "title":, "url":}} (url = die aktuell
    guenstigste Shop-URL, nur fuer die Anzeige/Verlinkung im Frontend).
    Das ist eine EIGENSTAENDIGE, selbst gesammelte Preisverlauf-
    Datenquelle (keine uebernommenen Fremddaten) - waechst daher ab dem
    Tag der Ersteinrichtung."""
    try:
        with open(PRICE_HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        history = {}

    today_str = datetime.date.today().isoformat()
    cutoff = (datetime.date.today() - datetime.timedelta(days=_PRICE_HISTORY_MAX_AGE_DAYS)).isoformat()

    for point in price_points:
        key = point["key"]
        price = point["price"]
        entry_group = history.setdefault(key, {"title": point.get("title", ""), "entries": []})
        entry_group["title"] = point.get("title", entry_group.get("title", ""))
        entries = entry_group["entries"]
        if entries and entries[-1]["date"] == today_str:
            entries[-1]["price"] = min(entries[-1]["price"], price)
        else:
            entries.append({"date": today_str, "price": price})
        entry_group["entries"] = [e for e in entries if e["date"] >= cutoff]

    try:
        with open(PRICE_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False)
    except OSError:
        pass


def _load_price_history(key):
    try:
        with open(PRICE_HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return history.get(key, {}).get("entries", [])


def _update_offers_history(all_offers):
    """Fuehrt eine PERSISTENTE (dateibasierte, ueberlebt Server-Neustarts)
    Historie darueber, wann jedes Angebot ZUM ERSTEN MAL als Angebot
    aufgetaucht ist. Gibt alle Angebote zurueck, die in den letzten 48
    Stunden neu hinzugekommen sind - fuer die "Neue Angebote (48h)"-Anzeige
    in der Seitenleiste."""
    try:
        with open(OFFERS_HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        history = {}

    now = datetime.datetime.now()
    now_iso = now.isoformat()
    new_in_48h = []
    seen_urls = set()

    for offer in all_offers:
        url = offer.get("url")
        if not url:
            continue
        seen_urls.add(url)
        entry = history.get(url)
        if entry is None:
            history[url] = {"first_seen": now_iso}
            entry_time = now
        else:
            try:
                entry_time = datetime.datetime.fromisoformat(entry["first_seen"])
            except (KeyError, ValueError):
                entry_time = now
                history[url]["first_seen"] = now_iso
        if (now - entry_time) <= datetime.timedelta(hours=48):
            # Nur die fuer die Anzeige noetigen, JSON-serialisierbaren
            # Felder uebernehmen - "offer" kann zusaetzliche interne
            # Felder wie ein "_tokens"-Set enthalten (aus der Vergleichs-
            # logik), die sich nicht in JSON umwandeln lassen.
            new_in_48h.append({
                "url": url,
                "title": offer.get("title", ""),
                "shop": offer.get("shop", ""),
                "price": offer.get("price"),
                "image": offer.get("image"),
            })

    # Zusaetzlicher Filter: ein "neues" Angebot wird nur angezeigt, wenn es
    # entweder GUENSTIGER ist als der aktuell beste bekannte Preis fuer das
    # gleiche Produkt (ueber alle Angebote hinweg, via normalisiertem
    # Titel gruppiert) ODER es ueberhaupt noch kein vergleichbares Angebot
    # dazu gibt - sonst waere es nur redundantes Rauschen (ein "neues"
    # Angebot, das aber teurer ist als ein bereits gelistetes fuer das
    # gleiche Produkt, bringt dem Nutzer keinen Mehrwert).
    _best_price_by_norm = {}
    for offer in all_offers:
        norm = offer.get("norm")
        price = offer.get("price")
        if not norm or price is None:
            continue
        if norm not in _best_price_by_norm or price < _best_price_by_norm[norm]:
            _best_price_by_norm[norm] = price

    filtered_new_in_48h = []
    for item in new_in_48h:
        norm = next((o.get("norm") for o in all_offers if o.get("url") == item["url"]), None)
        best_price = _best_price_by_norm.get(norm)
        # "noch nicht gelistet" (kein anderer Preis fuer dasselbe Produkt
        # bekannt) ODER "guenstiger als der aktuell beste bekannte Preis"
        # (<= statt < - das eigene Angebot selbst darf natuerlich den
        # aktuellen Bestpreis stellen).
        if best_price is None or item["price"] <= best_price:
            filtered_new_in_48h.append(item)
    new_in_48h = filtered_new_in_48h

    # Alte Eintraege (weder aktuell ein Angebot noch juengst gesehen)
    # nach _OFFERS_HISTORY_MAX_AGE_DAYS Tagen aus der Datei entfernen,
    # damit sie nicht unbegrenzt waechst.
    cutoff = now - datetime.timedelta(days=_OFFERS_HISTORY_MAX_AGE_DAYS)
    pruned = {}
    for url, entry in history.items():
        try:
            entry_time = datetime.datetime.fromisoformat(entry["first_seen"])
        except (KeyError, ValueError, TypeError):
            continue
        if url in seen_urls or entry_time >= cutoff:
            pruned[url] = entry

    try:
        with open(OFFERS_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(pruned, f, ensure_ascii=False)
    except OSError:
        pass

    return new_in_48h


def _compute_recent_changes(all_products):
    """Vergleicht die aktuellen Scan-Ergebnisse mit dem Snapshot des
    VORHERIGEN Scans (im Speicher) und ermittelt neue Artikel sowie
    Preissenkungen. Aktualisiert den Snapshot fuer den naechsten Vergleich."""
    global _PREVIOUS_SNAPSHOT
    current_snapshot = {}
    new_items = []
    price_drops = []
    had_previous = bool(_PREVIOUS_SNAPSHOT)
    for p in all_products:
        url = p.get("url")
        price = p.get("price")
        if not url or price is None:
            continue
        current_snapshot[url] = price
        if not had_previous:
            continue  # erster Scan dieser Sitzung - kein Vergleich moeglich
        old_price = _PREVIOUS_SNAPSHOT.get(url)
        clean_p = {"url": url, "title": p.get("title", ""), "shop": p.get("shop", ""),
                   "price": price, "image": p.get("image")}
        if old_price is None:
            new_items.append(clean_p)
        elif price < old_price:
            price_drops.append({**clean_p, "old_price": old_price})
    _PREVIOUS_SNAPSHOT = current_snapshot
    return new_items, price_drops


def _set_progress(**kwargs):
    with _progress_lock:
        SCAN_PROGRESS.update(kwargs)


# Schwellen fuer den bildbestaetigten Reklassifizierungs-Pfad in
# reclassify_unknown_types(): der Titel muss bereits deutlich aehneln
# (>= 0.75), und die Produktfotos muessen sich praktisch gleichen
# (Hamming-Distanz <= 16 von 64 Bit - strenger als die normale
# Ausreisser-Pruefung, weil das Bild hier der entscheidende Beweis ist).
RECLASSIFY_MIN_TEXT_SCORE = 0.75
RECLASSIFY_IMAGE_MAX_DISTANCE = 16


def reclassify_unknown_types(all_products):
    """Fuer Produkte, die als 'Sonstiges' eingestuft wurden (weil der Titel
    keine der bekannten Kategorie-Schluesselwoerter enthaelt, z.B. weil ein
    Shop nicht 'Kollektion' dazuschreibt), wird versucht, ueber die
    Titel-Aehnlichkeit zu bereits erkannten Produkten eine passendere
    Kategorie zu uebernehmen (gleiche Sprache vorausgesetzt)."""
    for p in all_products:
        if "_tokens" not in p:
            p["_tokens"] = title_tokens(p["title"])
            p["_img_tokens"] = image_tokens(p.get("image"))

    known = [p for p in all_products if p["product_type"] != "Sonstiges"]
    unknown = [p for p in all_products if p["product_type"] == "Sonstiges"]
    if not unknown or not known:
        return

    # nach Sprache vorsortieren, um die Vergleiche einzugrenzen
    known_by_lang = {}
    for k in known:
        known_by_lang.setdefault(k.get("language", "Unbekannt"), []).append(k)

    for u in unknown:
        candidates = known_by_lang.get(u.get("language", "Unbekannt"), [])
        best_score = 0.0
        best_type = None
        best_candidate = None
        for k in candidates:
            score = product_similarity(u, k)
            if score > best_score:
                best_score = score
                best_type = k["product_type"]
                best_candidate = k
                if best_score >= 0.99:
                    break  # eindeutiger Treffer, weitersuchen lohnt nicht
        # WICHTIG: hier gilt eine deutlich strengere Regel als beim
        # normalen Preisvergleich - diese Funktion vergleicht ueber die
        # GESAMTE Produktpalette hinweg (nicht nur innerhalb einer bereits
        # vorgefilterten Gruppe gleichen Typs), das Risiko eines falschen
        # Treffers ist dadurch strukturell hoeher (z.B. ein "Badge Set" und
        # eine "Booster Box" derselben Serie teilen sich den Serien-Namen,
        # sind aber trotzdem komplett unterschiedliche Produkte). Deshalb:
        # NUR bei einem kuratierten Set-Tag-Treffer (siehe SET_NAME_ALIASES)
        # reklassifizieren - das ist die einzige Form von Uebereinstimmung,
        # die zuverlaessig genug ist, um ueber Produkttyp-Grenzen hinweg zu
        # vertrauen. Reine Wort-Aehnlichkeit reicht hier NICHT mehr aus.
        if best_score >= 0.9 and best_type and best_candidate:
            shared_canonical = {
                t for t in (u["_tokens"] & best_candidate["_tokens"])
                if t.startswith("cset")
            }
            if shared_canonical:
                verified = verify_group_with_images([u, best_candidate])
                if len(verified) == 1:
                    u["product_type"] = best_type
                    continue
        # ZWEITER Pfad (Bild-Beweis): auch OHNE kuratierten Set-Tag darf
        # reklassifiziert werden, wenn das PRODUKTFOTO praktisch identisch
        # ist - viele Shops listen z.B. ein Display oder eine Gift Box nur
        # mit dem nackten Set-Namen ("Pokemon Night Wanderer (JP)"), waehrend
        # andere Shops dasselbe Produkt (gleiches Foto!) mit vollem
        # Typ-Wort fuehren. Ein sehr aehnlicher Wahrnehmungs-Hash beider
        # Bilder ist hier der Beleg, den der Titel allein nicht liefert.
        # Bewusst STRENGER als IMAGE_HASH_MAX_DISTANCE (32), weil das Bild
        # hier POSITIV beweisen muss statt nur nicht zu widersprechen.
        if best_score >= RECLASSIFY_MIN_TEXT_SCORE and best_type and best_candidate and _PIL_AVAILABLE:
            h_u = compute_image_dhash(u.get("image"))
            h_k = compute_image_dhash(best_candidate.get("image"))
            if (h_u is not None and h_k is not None
                    and _hamming(h_u, h_k) <= RECLASSIFY_IMAGE_MAX_DISTANCE):
                u["product_type"] = best_type


def _draw_pokeball_icon(size):
    """Zeichnet ein einfaches Pokeball-Icon (rot/weiss mit schwarzem Band)
    fuer die PWA-App-Icons - ganz ohne externe Bilddatei."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = size * 0.04
    draw.ellipse([pad, pad, size - pad, size - pad], fill=(26, 27, 46, 255))  # dunkler Hintergrund-Kreis
    r = size * 0.42
    cx, cy = size / 2, size / 2
    draw.pieslice([cx - r, cy - r, cx + r, cy + r], 180, 360, fill=(255, 59, 59, 255))  # obere Haelfte rot
    draw.pieslice([cx - r, cy - r, cx + r, cy + r], 0, 180, fill=(255, 255, 255, 255))  # untere Haelfte weiss
    band_h = size * 0.045
    draw.rectangle([cx - r, cy - band_h, cx + r, cy + band_h], fill=(20, 20, 20, 255))
    br = size * 0.13
    draw.ellipse([cx - br, cy - br, cx + br, cy + br], fill=(20, 20, 20, 255))
    br2 = br * 0.55
    draw.ellipse([cx - br2, cy - br2, cx + br2, cy + br2], fill=(255, 255, 255, 255))
    return img


def _ensure_pwa_files():
    """Erzeugt/aktualisiert die Begleitdateien, die angebote.html als
    installierbare PWA (Progressive Web App) nutzbar machen - fuers
    Handy per "Zum Home-Bildschirm hinzufuegen" unter Android UND iOS.
    Kein natives APK/IPA (dafuer waeren Android-SDK bzw. zwingend macOS/
    Xcode noetig, hier nicht verfuegbar), aber funktional wie eine App:
    eigenes Icon, eigener Vollbild-Start, funktioniert offline mit dem
    zuletzt gespeicherten Scan-Stand."""
    manifest = {
        "name": "Pokemon TCG Scanner",
        "short_name": "PKM Scanner",
        "description": "Preisvergleich fuer Pokemon TCG Sammelkarten-Produkte in deutschen Online-Shops",
        "start_url": "./app.html",
        "scope": "./",
        "display": "standalone",
        "background_color": "#1a1b2e",
        "theme_color": "#ffcb05",
        "orientation": "portrait-primary",
        "icons": [
            {"src": "icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
    }
    try:
        with open("manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
    except OSError:
        pass

    # Minimaler Service Worker: cached die zuletzt geladene Seite, damit
    # die App auch ohne Internet/Server-Verbindung zumindest den letzten
    # Scan-Stand zeigt (rein statisch, kein Hintergrund-Sync).
    sw_js = """const CACHE = 'pkm-scanner-v2';
const PRECACHE = ['./app.html', './manifest.json', './icon-192.png', './icon-512.png'];
self.addEventListener('install', (e) => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then((c) => Promise.all(
    PRECACHE.map((u) => c.add(u).catch(() => null))
  )));
});
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(
    ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))
  )).then(() => self.clients.claim()));
});
self.addEventListener('fetch', (e) => {
  if (e.request.method !== 'GET') return;
  e.respondWith(
    fetch(e.request).then((res) => {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(e.request, copy));
      return res;
    }).catch(() => caches.match(e.request))
  );
});
"""
    try:
        with open("sw.js", "w", encoding="utf-8") as f:
            f.write(sw_js)
    except OSError:
        pass

    for size, fname in ((192, "icon-192.png"), (512, "icon-512.png")):
        if _PIL_AVAILABLE and not os.path.exists(fname):
            try:
                _draw_pokeball_icon(size).save(fname)
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# App-Daten (data.json) fuer die Handy-App app.html
# ---------------------------------------------------------------------------

APP_DATA_FILE = "data.json"


def _app_group(entries, kind):
    """Baut aus allen Shop-Eintraegen EINES Produkts (bereits von
    group_by_product zusammengefasst) einen kompakten Datensatz fuer die
    App: ein Produkt, darunter alle Haendler mit Preis, sortiert vom
    guenstigsten aufwaerts."""
    entries = sorted(entries, key=lambda e: e["price"])
    first = entries[0]

    urls_by_lang = {}
    for e in entries:
        urls_by_lang.setdefault(e.get("language", "Unbekannt"), []).append(e["url"])
    # Schluessel fuer den Preisverlauf - identisch zu dem, was die
    # Desktop-Seite verwendet, damit /price-history die gleichen Daten
    # liefert.
    history_keys = [
        {"language": lang, "key": _price_group_key(lang, urls)}
        for lang, urls in urls_by_lang.items()
    ]

    shops = []
    for e in entries:
        shops.append({
            "shop": e.get("shop", ""),
            "price": round(float(e["price"]), 2),
            "compare_at": (round(float(e["compare_at"]), 2)
                           if e.get("compare_at") else None),
            "discount_pct": e.get("discount_pct") or 0,
            "url": e.get("url", ""),
            "language": e.get("language", "Unbekannt"),
        })

    image = next((e.get("image") for e in entries if e.get("image")), None)
    languages = sorted({s["language"] for s in shops})

    return {
        "kind": kind,
        "title": first.get("title", "Unbekannt"),
        "image": image,
        "product_type": first.get("product_type", "Sonstiges"),
        "languages": languages,
        "min_price": min(s["price"] for s in shops),
        "max_price": max(s["price"] for s in shops),
        "best_discount": max((s["discount_pct"] or 0) for s in shops),
        "shop_count": len(shops),
        "shops": shops,
        "history_keys": history_keys,
        "search": " ".join([first.get("title", "")] + [s["shop"] for s in shops]).lower(),
    }


def _app_groups_from(entries, kind):
    out = []
    for group in group_by_product(entries).values():
        try:
            out.append(_app_group(group, kind))
        except (KeyError, ValueError, TypeError):
            continue
    out.sort(key=lambda g: (-g["best_discount"], g["min_price"]))
    return out


APP_PRODUCTS_FILE = "products.json"


def write_app_data(all_offers, all_preorders, all_products, scan_time,
                   errors, shop_count, changes=None, out_dir="."):
    """Schreibt die beiden Datenquellen der Handy-App (app.html):

    data.json      - Angebote, Vorbestellungen, Aenderungen. Wird beim Start
                     der App geladen und bleibt deshalb bewusst schlank.
    products.json  - der komplette Katalog aller gefundenen Pokemon-Artikel.
                     Deutlich groesser und daher eine eigene Datei: die App
                     holt sie erst, wenn der Reiter "Alle" geoeffnet wird."""
    changes = changes or {}
    catalog = _app_groups_from(all_products, "product")
    for g in catalog:
        g.pop("search", None)      # baut die App sich selbst
        g.pop("history_keys", None)  # Verlauf gibt es ueber Angebote/Vorbestellungen
    payload = {
        "version": 2,
        "scan_time": scan_time,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "shop_count": shop_count,
        "errors": errors[:20],
        "offers": _app_groups_from(all_offers, "offer"),
        "preorders": _app_groups_from(all_preorders, "preorder"),
        "product_count": len(catalog),
        "changes": {
            "new_items": (changes.get("new_items") or [])[:60],
            "price_drops": (changes.get("price_drops") or [])[:60],
            "new_offers_48h": (changes.get("new_offers_48h") or [])[:60],
        },
    }
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, APP_DATA_FILE)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    except OSError as exc:
        print(f"Warnung: {path} konnte nicht geschrieben werden ({exc})")
        return
    size_kb = os.path.getsize(path) / 1024
    print(f"App-Daten gespeichert in: {path} ({size_kb:.0f} KB)")

    cat_path = os.path.join(out_dir, APP_PRODUCTS_FILE)
    try:
        with open(cat_path, "w", encoding="utf-8") as f:
            json.dump({
                "version": 2,
                "scan_time": scan_time,
                "generated_at": payload["generated_at"],
                "products": catalog,
            }, f, ensure_ascii=False, separators=(",", ":"))
    except OSError as exc:
        print(f"Warnung: {cat_path} konnte nicht geschrieben werden ({exc})")
        return
    cat_kb = os.path.getsize(cat_path) / 1024
    print(f"Gesamtkatalog gespeichert in: {cat_path} "
          f"({len(catalog)} Produkte, {cat_kb:.0f} KB)")


# ---------------------------------------------------------------------------
# Veroeffentlichen (GitHub Pages / beliebiger statischer Webspace)
# ---------------------------------------------------------------------------

# Wird per --publish-dir gesetzt. Ist es gesetzt, legt jeder Scan zusaetzlich
# einen fertigen, komplett statischen App-Ordner an: App, Daten, Preisverlauf,
# Manifest, Service Worker und Icons. Der Ordner braucht danach keinen Server
# mehr - er kann von GitHub Pages ausgeliefert werden, und die App laeuft
# damit auch, wenn der eigene PC aus ist.
PUBLISH_DIR = None

# Wie viele Tage Preisverlauf in die veroeffentlichte history.json wandern.
# Kurz genug, damit die Datei klein bleibt, lang genug fuer eine sichtbare
# Kurve in der App.
PUBLISH_HISTORY_DAYS = 120


def _publish_history(keys, out_dir):
    """Schreibt einen Auszug der Preishistorie fuer genau die Produkte, die
    in data.json vorkommen - damit die App den Verlauf auch ohne laufenden
    Server zeichnen kann (ohne die komplette, viel groessere
    price_history.json mitzuliefern)."""
    try:
        with open(PRICE_HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        history = {}

    cutoff = (datetime.date.today()
              - datetime.timedelta(days=PUBLISH_HISTORY_DAYS)).isoformat()
    slim = {}
    for key in keys:
        entries = history.get(key, {}).get("entries", [])
        entries = [e for e in entries if e.get("date", "") >= cutoff]
        if len(entries) >= 2:
            slim[key] = entries

    path = os.path.join(out_dir, "history.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(slim, f, ensure_ascii=False, separators=(",", ":"))
    return len(slim)


def publish_static(out_dir):
    """Baut den statischen App-Ordner fuer GitHub Pages.

    data.json wurde bereits von write_app_data() dorthin geschrieben; hier
    kommen Preisverlauf, App-Datei und PWA-Zubehoer dazu. Alles nur mit
    Bordmitteln, damit es auch auf einem frischen CI-Runner laeuft."""
    os.makedirs(out_dir, exist_ok=True)

    data_path = os.path.join(out_dir, APP_DATA_FILE)
    try:
        with open(data_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print("Warnung: keine data.json zum Veroeffentlichen gefunden.")
        return

    keys = set()
    # Bewusst nur Angebote und Vorbestellungen: fuer den kompletten Katalog
    # waere history.json um ein Vielfaches groesser, und der Verlauf ist
    # genau dort interessant, wo sich Preise gerade bewegen.
    buckets = [data.get("offers", []), data.get("preorders", [])]
    for bucket in buckets:
        for group in bucket:
            for hk in group.get("history_keys", []):
                keys.add(hk["key"])
    hist_count = _publish_history(keys, out_dir)

    # App-Datei und PWA-Zubehoer daneben legen. index.html ist eine Kopie
    # von app.html, damit die nackte Adresse (ohne Dateiname) direkt in der
    # App landet.
    copied = []
    try:
        with open("app.html", "r", encoding="utf-8") as f:
            app_html = f.read()
        for target in ("app.html", "index.html"):
            with open(os.path.join(out_dir, target), "w", encoding="utf-8") as f:
                f.write(app_html)
        copied.append("app.html + index.html")
    except OSError:
        print("Warnung: app.html nicht gefunden - App-Datei fehlt im "
              "Veroeffentlichungs-Ordner.")

    for fname in ("manifest.json", "sw.js", "icon-192.png", "icon-512.png"):
        if not os.path.exists(fname):
            continue
        try:
            with open(fname, "rb") as src, \
                 open(os.path.join(out_dir, fname), "wb") as dst:
                dst.write(src.read())
            copied.append(fname)
        except OSError:
            pass

    # GitHub Pages wuerde den Ordner sonst durch Jekyll schicken.
    try:
        open(os.path.join(out_dir, ".nojekyll"), "w").close()
    except OSError:
        pass

    print(f"Veroeffentlicht in ./{out_dir}/ - {hist_count} Preisverlaeufe, "
          f"{len(copied)} Begleitdateien.")


def run_scan():
    """Fuehrt einen kompletten Scan aller Shops durch (parallel, mehrere
    Shops gleichzeitig) und schreibt angebote.html.
    Gibt (offers, preorders, alerts_result) zurueck."""
    alert_keywords = load_alerts()
    all_offers = []
    all_preorders = []
    all_alerts = {kw: [] for kw in alert_keywords}
    all_products = []
    errors = []

    js_shops = WOOCOMMERCE_JS_PROTECTED_SHOPS if _PLAYWRIGHT_AVAILABLE else []
    custom_shops = CUSTOM_SCRAPER_SHOPS if _PLAYWRIGHT_AVAILABLE else []
    total_shop_count = _total_shop_count()
    print(f"Scanne {total_shop_count} Shops parallel (max. {MAX_WORKERS} gleichzeitig) ...\n")
    if not _PLAYWRIGHT_AVAILABLE and (WOOCOMMERCE_JS_PROTECTED_SHOPS or CUSTOM_SCRAPER_SHOPS):
        names = ", ".join(s["name"] for s in WOOCOMMERCE_JS_PROTECTED_SHOPS + CUSTOM_SCRAPER_SHOPS)
        print(f"(Hinweis: {names} wird uebersprungen - braucht optional Playwright: "
              f"pip install playwright && playwright install chromium)\n")
    start_time = time.time()
    _reset_blocked_shops()
    _reset_seen_urls()
    _set_progress(running=True, done=0, total=total_shop_count, current_shop="")

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future_to_shop = {
            pool.submit(scan_shop, shop, alert_keywords): shop for shop in SHOPS
        }
        future_to_shop.update({
            pool.submit(scan_shop_woocommerce, shop, alert_keywords): shop for shop in WOOCOMMERCE_SHOPS
        })
        future_to_shop.update({
            pool.submit(scan_shop_woocommerce_playwright, shop, alert_keywords): shop for shop in js_shops
        })
        _CUSTOM_SCRAPER_FUNCS = {
            "tcgtrade": scan_shop_tcgtrade,
            "gambio": scan_shop_gambio,
            "comicplanet": scan_shop_comicplanet,
            "jtl": scan_shop_jtl,
        }
        future_to_shop.update({
            pool.submit(_CUSTOM_SCRAPER_FUNCS[shop["scraper"]], shop, alert_keywords): shop
            for shop in custom_shops
        })
        done_count = 0
        for future in concurrent.futures.as_completed(future_to_shop):
            shop = future_to_shop[future]
            done_count += 1
            try:
                offers, preorders, alert_hits, products = future.result()
                all_offers.extend(offers)
                all_preorders.extend(preorders)
                all_products.extend(products)
                for kw, hits in alert_hits.items():
                    all_alerts.setdefault(kw, []).extend(hits)
                print(f"[{done_count}/{total_shop_count}] ✓ {shop['name']}: "
                      f"{len(offers)} Angebote, {len(preorders)} Vorbestellungen, "
                      f"{len(products)} Produkte gesamt")
            except Exception as exc:  # noqa: BLE001 - robust gegen jeden Shop-Fehler
                print(f"[{done_count}/{total_shop_count}] ✗ {shop['name']}: Fehler - {exc}")
                errors.append(f"{shop['name']}: {exc}")
            _set_progress(done=done_count, current_shop=shop["name"])

    elapsed = time.time() - start_time

    # Massen-Blockierung erkennen (viele 403/429 im selben Scan = die
    # EIGENE IP ist voruebergehend gesperrt, nicht die Shops sind kaputt).
    blocked_count = _blocked_shop_count()
    if blocked_count >= MASS_BLOCK_THRESHOLD:
        global _scan_cooldown_until
        _scan_cooldown_until = time.time() + MASS_BLOCK_COOLDOWN_MINUTES * 60
        warn = (f"⚠ {blocked_count} Shops haben diesen Scan mit 403/429 abgewiesen - "
                f"das deutet auf eine VORUEBERGEHENDE SPERRE deiner IP-Adresse hin "
                f"(zu viele Scans in zu kurzer Zeit). Der automatische Hintergrund-Scan "
                f"pausiert jetzt fuer {MASS_BLOCK_COOLDOWN_MINUTES} Minuten. Tipp: "
                f"--background-interval erhoehen (z.B. 30 oder 60 Minuten) und ein paar "
                f"Stunden gar nicht scannen - die Sperre laeuft von selbst ab.")
        print(f"\n{warn}\n")
        errors.insert(0, warn)
    else:
        # Nur bei einem "gesunden" Scan (keine Massen-Sperre) die Caches von
        # verwaisten URLs befreien - bei einer IP-Sperre waeren zu viele
        # Seiten faelschlich als "nicht mehr vorhanden" markiert worden.
        _prune_caches(_get_seen_urls())
    # Manuell dauerhaft ausgeschlossene, defekte Produkt-URLs entfernen
    # (siehe EXCLUDED_PRODUCT_URLS oben).
    if EXCLUDED_PRODUCT_URLS:
        all_offers = [p for p in all_offers if p.get("url") not in EXCLUDED_PRODUCT_URLS]
        all_preorders = [p for p in all_preorders if p.get("url") not in EXCLUDED_PRODUCT_URLS]
        all_products = [p for p in all_products if p.get("url") not in EXCLUDED_PRODUCT_URLS]
    reclassify_unknown_types(all_products)
    scan_time = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")

    new_items, price_drops = _compute_recent_changes(all_products)
    new_offers_48h = _update_offers_history(all_offers)
    with _changes_lock:
        RECENT_CHANGES["new_items"] = new_items
        RECENT_CHANGES["price_drops"] = price_drops
        RECENT_CHANGES["new_offers_48h"] = new_offers_48h
        RECENT_CHANGES["last_scan"] = scan_time

    html = build_html(all_offers, all_preorders, all_alerts, all_products, scan_time, errors, total_shop_count)

    out_path = "angebote.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    _ensure_pwa_files()

    # Datenquelle fuer die Handy-App (app.html)
    with _changes_lock:
        _changes_snapshot = dict(RECENT_CHANGES)
    write_app_data(all_offers, all_preorders, all_products, scan_time,
                   errors, total_shop_count, _changes_snapshot)

    # Statischer App-Ordner (--publish-dir), z.B. fuer GitHub Pages. Ein
    # Scan, der praktisch nichts gefunden hat (gesperrte IP, Netzwerkproblem),
    # darf den zuletzt veroeffentlichten Stand NICHT ueberschreiben.
    if PUBLISH_DIR:
        if len(all_products) < 50:
            print(f"Veroeffentlichung uebersprungen: nur {len(all_products)} "
                  f"Produkte gefunden - der bisherige Stand bleibt stehen.")
        else:
            write_app_data(all_offers, all_preorders, all_products, scan_time,
                           errors, total_shop_count, _changes_snapshot,
                           out_dir=PUBLISH_DIR)
            publish_static(PUBLISH_DIR)

    total_alert_hits = sum(len(v) for v in all_alerts.values())
    print(f"\nFertig in {elapsed:.0f}s! {len(all_offers)} Angebote, {len(all_preorders)} Vorbestellungen, "
          f"{len(all_products)} Produkte gesamt, {total_alert_hits} Alarm-Treffer "
          f"(über {len(alert_keywords)} Alarme) gefunden.")
    print(f"Ergebnis gespeichert in: {out_path}")
    _set_progress(running=False, done=_total_shop_count(), current_shop="")
    return all_offers, all_preorders, all_alerts


def background_scan_loop(interval_minutes):
    """Laeuft dauerhaft im Hintergrund (eigener Thread) und stoesst alle
    interval_minutes automatisch einen neuen Scan an - damit neue Angebote
    und Preissenkungen erkannt werden, OHNE dass der Nutzer manuell auf
    'Neu suchen' klicken muss. Wird beim --serve Start automatisch
    mitgestartet. Laeuft bewusst LANGSAM (Standard: alle 5 Minuten), um
    die Shops nicht zu ueberlasten und die Seite waehrend des eigenen
    Browsens/Suchens nicht zu stoeren (das Front-End laedt die Seite dabei
    nicht neu, sondern pollt nur /recent-changes fuer die Seitenleiste)."""
    while True:
        time.sleep(interval_minutes * 60)
        if SCAN_PROGRESS["running"]:
            continue  # ein Rescan (z.B. per Button) laeuft schon - ueberspringen
        if time.time() < _scan_cooldown_until:
            remaining = int((_scan_cooldown_until - time.time()) / 60) + 1
            print(f"== Hintergrund-Scan pausiert (IP-Sperre erkannt) - noch ca. {remaining} Min. Abkuehlphase ==")
            continue
        print(f"\n== Automatischer Hintergrund-Scan (alle {interval_minutes} Min.) gestartet ==")
        try:
            run_scan()
        except Exception as exc:  # noqa: BLE001 - Hintergrund-Loop darf nie ganz abbrechen
            print(f"Fehler im Hintergrund-Scan: {exc}")


def serve(port=DEFAULT_SERVER_PORT, open_browser=True, background_interval=15):
    """Startet einen kleinen lokalen Server, damit der 'Neu suchen'-Button
    in der HTML-Seite einen echten Rescan anstossen kann (das kann eine
    per Doppelklick geoeffnete Datei aus Sicherheitsgruenden nicht selbst).
    Per CORS-Headern funktioniert das auch, wenn angebote.html ganz normal
    per Doppelklick (file://) geoeffnet wird, solange dieser Server im
    Hintergrund laeuft."""
    import http.server
    import socketserver
    import webbrowser

    global CURRENT_SERVER_PORT
    CURRENT_SERVER_PORT = port  # damit build_html() die richtige Adresse einbettet

    class Handler(http.server.SimpleHTTPRequestHandler):
        def _cors_headers(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            # WICHTIG: Ohne diese Header kann der Browser nach einem Alarm-
            # Update/Rescan eine ALTE zwischengespeicherte Version von
            # angebote.html anzeigen (unformatiert/inkonsistent wirkend,
            # obwohl der Server laengst die neue Datei geschrieben hat).
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")

        def do_OPTIONS(self):
            self.send_response(204)
            self.end_headers()

        def do_GET(self):
            if self.path == "/" or self.path == "":
                self.send_response(302)
                self.send_header("Location", "/app.html")
                self.end_headers()
            elif self.path == "/progress":
                with _progress_lock:
                    data = json.dumps(SCAN_PROGRESS).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data)
            elif self.path == "/recent-changes":
                with _changes_lock:
                    data = json.dumps(RECENT_CHANGES).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data)
            elif self.path.startswith("/price-history"):
                parsed = urllib.parse.urlparse(self.path)
                qs = urllib.parse.parse_qs(parsed.query)
                key_param = (qs.get("key") or [""])[0]
                history = _load_price_history(key_param) if key_param else []
                data = json.dumps({"key": key_param, "history": history}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data)
            else:
                super().do_GET()

        def do_POST(self):
            if self.path == "/rescan":
                if SCAN_PROGRESS["running"]:
                    self.send_response(202)  # laeuft schon - einfach mitpollen
                    self.end_headers()
                    self.wfile.write(b"already running")
                    return
                print("\n== Rescan angefordert vom Button in der Web-Seite ==")
                # WICHTIG: running=True SOFORT (synchron) setzen, bevor der
                # Hintergrund-Thread startet. Sonst sieht die Web-Seite beim
                # allerersten /progress-Poll noch den alten "running=false"-
                # Stand (vom letzten fertigen Scan) und laedt faelschlich
                # sofort neu, statt auf den neuen Scan zu warten.
                _set_progress(running=True, done=0, total=_total_shop_count(), current_shop="")
                threading.Thread(target=run_scan, daemon=True).start()
                self.send_response(202)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"started")
            elif self.path == "/alerts":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(length) or b"{}")
                    action = body.get("action")
                    keyword = (body.get("keyword") or "").strip()
                    alerts = load_alerts()
                    if action == "add" and keyword and keyword not in alerts:
                        alerts.append(keyword)
                        save_alerts(alerts)
                    elif action == "remove" and keyword in alerts:
                        alerts.remove(keyword)
                        save_alerts(alerts)
                    print(f"\n== Alarm-Update: {action} '{keyword}' -> Rescan ==")
                    if not SCAN_PROGRESS["running"]:
                        # Siehe Kommentar oben bei /rescan - gleiches Race
                        # Condition-Problem, gleicher Fix.
                        _set_progress(running=True, done=0, total=_total_shop_count(), current_shop="")
                        threading.Thread(target=run_scan, daemon=True).start()
                    self.send_response(202)
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"started")
                except BrokenPipeError:
                    pass
                except Exception as exc:  # noqa: BLE001
                    try:
                        self.send_response(500)
                        self.end_headers()
                        self.wfile.write(str(exc).encode("utf-8"))
                    except BrokenPipeError:
                        pass
            elif self.path == "/flag_wrong":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(length) or b"{}")
                    urls = [u for u in (body.get("urls") or []) if u]
                    if len(urls) >= 2:
                        add_correction_pairs(urls)
                        print(f"\n== '{len(urls)}' Angebote als falsch zusammengefuehrt gemeldet -> Rescan ==")
                    if not SCAN_PROGRESS["running"]:
                        _set_progress(running=True, done=0, total=_total_shop_count(), current_shop="")
                        threading.Thread(target=run_scan, daemon=True).start()
                    self.send_response(202)
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"started")
                except BrokenPipeError:
                    pass
                except Exception as exc:  # noqa: BLE001
                    try:
                        self.send_response(500)
                        self.end_headers()
                        self.wfile.write(str(exc).encode("utf-8"))
                    except BrokenPipeError:
                        pass
            elif self.path == "/unflag_wrong":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(length) or b"{}")
                    pair = body.get("pair") or []
                    if len(pair) == 2:
                        remove_correction_pair(pair[0], pair[1])
                        print("\n== Korrektur rueckgaengig gemacht -> Rescan ==")
                    if not SCAN_PROGRESS["running"]:
                        _set_progress(running=True, done=0, total=_total_shop_count(), current_shop="")
                        threading.Thread(target=run_scan, daemon=True).start()
                    self.send_response(202)
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"started")
                except BrokenPipeError:
                    pass
                except Exception as exc:  # noqa: BLE001
                    try:
                        self.send_response(500)
                        self.end_headers()
                        self.wfile.write(str(exc).encode("utf-8"))
                    except BrokenPipeError:
                        pass
            else:
                self.send_response(404)
                self.end_headers()

        def end_headers(self):
            # CORS-Header auch fuer normale GET-Antworten (z.B. angebote.html
            # selbst, falls sie mal ueber den Server statt file:// geladen wird)
            self._cors_headers()
            super().end_headers()

        def log_message(self, format, *args):
            pass  # ruhiger Server-Log

    if not os.path.exists("angebote.html") or not os.path.exists(APP_DATA_FILE):
        print("Noch keine Scan-Daten vorhanden - fuehre ersten Scan aus ...")
        run_scan()

    if background_interval > 0:
        if background_interval < 15:
            print(f"⚠ Hinweis: --background-interval {background_interval} ist sehr aggressiv. "
                  f"Bei 58 Shops kann das zu einer voruebergehenden IP-Sperre fuehren "
                  f"(viele 403-Fehler). Empfohlen: 30 oder mehr Minuten.")
        threading.Thread(
            target=background_scan_loop, args=(background_interval,), daemon=True
        ).start()
        print(f"Automatischer Hintergrund-Scan aktiv: alle {background_interval} Minuten.")

    class ThreadingServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        daemon_threads = True
        allow_reuse_address = True

    with ThreadingServer(("0.0.0.0", port), Handler) as httpd:
        url = f"http://127.0.0.1:{port}/app.html"
        print(f"\nServer laeuft: {url}")
        try:
            _s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            _s.connect(("8.8.8.8", 80))
            lan_ip = _s.getsockname()[0]
            _s.close()
            print(f"Handy-App im selben WLAN erreichbar unter: http://{lan_ip}:{port}/app.html")
        except OSError:
            pass
        print("Die Buttons in angebote.html funktionieren jetzt (auch wenn du die Datei per Doppelklick oeffnest).")
        print("Zum Beenden: Strg+C in diesem Fenster (oder Prozess beenden, falls im Hintergrund).")
        if open_browser:
            try:
                webbrowser.open(url)
            except Exception:  # noqa: BLE001
                pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer beendet.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Pokemon TCG Angebots- und Vorbestellungs-Scanner"
    )
    parser.add_argument(
        "--serve", action="store_true",
        help="Startet einen lokalen Server, damit der 'Neu suchen'-Button in der "
             "Web-Seite einen echten Rescan ausloesen kann."
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_SERVER_PORT,
        help="Port fuer den lokalen Server (Standard: 8765)"
    )
    parser.add_argument(
        "--no-browser", action="store_true",
        help="Beim --serve Start NICHT automatisch einen Browser-Tab oeffnen "
             "(nuetzlich, wenn der Server unsichtbar im Hintergrund laufen soll "
             "und du angebote.html selbst per Doppelklick oeffnest)."
    )
    parser.add_argument(
        "--background-interval", type=int, default=60,
        help="Wie oft (in Minuten) im --serve Modus automatisch neu gescannt wird "
             "(Standard: 60). Mit 0 abschalten (nur noch manueller Rescan per Button). "
             "ACHTUNG: Werte unter 15 koennen bei 58 Shops dazu fuehren, dass die "
             "eigene IP vom Shopify-Botschutz voruebergehend gesperrt wird (403-Fehler)."
    )
    parser.add_argument(
        "--publish-dir", metavar="ORDNER", default=None,
        help="Nach dem Scan zusaetzlich einen komplett statischen App-Ordner "
             "erzeugen (App + Daten + Preisverlauf + PWA-Dateien), z.B. "
             "'docs' fuer GitHub Pages. Damit laeuft die Handy-App auch ohne "
             "eingeschalteten PC."
    )
    args = parser.parse_args()

    if args.publish_dir:
        PUBLISH_DIR = args.publish_dir

    if args.serve:
        serve(port=args.port, open_browser=not args.no_browser,
              background_interval=args.background_interval)
    else:
        run_scan()
