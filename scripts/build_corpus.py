#!/usr/bin/env python3
"""
AG983 Assignment 2026 — EDGAR corpus builder
=============================================
Downloads Item 1A (Risk Factors) and Item 7 (MD&A) text from 10-K filings
on EDGAR for each of the four research scenarios and writes one corpus.csv
per scenario to:

    data/scenario_a/corpus.csv
    data/scenario_b/corpus.csv
    data/scenario_c/corpus.csv
    data/scenario_d/corpus.csv

Usage
-----
Run from the repository root:

    pip install requests beautifulsoup4 pandas lxml
    python scripts/build_corpus.py

The script respects EDGAR's rate-limit guideline (max 10 req/s); it sleeps
0.15 s between requests. Expect approximately 40-70 minutes total.

Output columns
--------------
    cik, firm, ticker, category, year, section,
    filing_date, accession_number, text, word_count

Scenario C only: also includes `litigation_status` column.
Scenario D only: also includes `reit_type` column (mirrors category).
"""

import os
import re
import csv
import time
import json
import logging
import requests
import pandas as pd
from pathlib import Path
from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning
import warnings

warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT   = Path(__file__).resolve().parents[1]   # repo root
DATA_ROOT   = REPO_ROOT / "data"
DATA_ROOT.mkdir(parents=True, exist_ok=True)
LOG_FILE    = DATA_ROOT / "build_corpus.log"

HEADERS     = {"User-Agent": "University of Strathclyde AG983 Research james.bowden@strath.ac.uk"}
RATE_SLEEP  = 0.15

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, mode="w"),
    ],
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Firm lists
# ---------------------------------------------------------------------------

# ── Scenario A: Cybersecurity Risk Disclosure (2019-2024) ─────────────────
# ~55 firms across financial services, healthcare, technology, and retail/
# hospitality — sectors with the highest breach frequency and regulatory
# exposure. Anchor events: SolarWinds (2020), Colonial Pipeline (2021),
# MOVEit (2023), SEC mandatory cyber disclosure rules (Dec 2023).
SCENARIO_A = [
    # Financial services — high-value targets, early SEC scrutiny
    {"cik": "19617",    "firm": "JPMorgan Chase",             "ticker": "JPM",  "category": "financial_services"},
    {"cik": "70858",    "firm": "Bank of America",            "ticker": "BAC",  "category": "financial_services"},
    {"cik": "831001",   "firm": "Citigroup",                  "ticker": "C",    "category": "financial_services"},
    {"cik": "72971",    "firm": "Wells Fargo",                "ticker": "WFC",  "category": "financial_services"},
    {"cik": "927628",   "firm": "Capital One",                "ticker": "COF",  "category": "financial_services"},
    {"cik": "4977",     "firm": "American Express",           "ticker": "AXP",  "category": "financial_services"},
    {"cik": "1403161",  "firm": "Visa",                       "ticker": "V",    "category": "financial_services"},
    {"cik": "1141391",  "firm": "Mastercard",                 "ticker": "MA",   "category": "financial_services"},
    {"cik": "1633917",  "firm": "PayPal Holdings",            "ticker": "PYPL", "category": "financial_services"},
    {"cik": "1393612",  "firm": "Discover Financial Services","ticker": "DFS",  "category": "financial_services"},
    {"cik": "316888",   "firm": "Charles Schwab",             "ticker": "SCHW", "category": "financial_services"},
    {"cik": "33185",    "firm": "Equifax",                    "ticker": "EFX",  "category": "financial_services"},
    {"cik": "1023023",  "firm": "TransUnion",                 "ticker": "TRU",  "category": "financial_services"},
    {"cik": "1136893",  "firm": "Fidelity National Information Services", "ticker": "FIS", "category": "financial_services"},
    {"cik": "798354",   "firm": "Fiserv",                     "ticker": "FI",   "category": "financial_services"},
    # Healthcare — breach volumes highest of any sector post-2019
    {"cik": "731766",   "firm": "UnitedHealth Group",         "ticker": "UNH",  "category": "healthcare"},
    {"cik": "1156039",  "firm": "Elevance Health",            "ticker": "ELV",  "category": "healthcare"},
    {"cik": "49071",    "firm": "Humana",                     "ticker": "HUM",  "category": "healthcare"},
    {"cik": "860730",   "firm": "HCA Healthcare",             "ticker": "HCA",  "category": "healthcare"},
    {"cik": "64803",    "firm": "CVS Health",                 "ticker": "CVS",  "category": "healthcare"},
    {"cik": "720858",   "firm": "Universal Health Services",  "ticker": "UHS",  "category": "healthcare"},
    {"cik": "920148",   "firm": "Laboratory Corporation",     "ticker": "LH",   "category": "healthcare"},
    {"cik": "920110",   "firm": "Quest Diagnostics",          "ticker": "DGX",  "category": "healthcare"},
    {"cik": "804212",   "firm": "Cerner Corporation",         "ticker": "CERN", "category": "healthcare"},
    {"cik": "1444598",  "firm": "Change Healthcare",          "ticker": "CHNG", "category": "healthcare"},
    # Technology — cybersecurity vendors and high-profile breach targets
    {"cik": "789019",   "firm": "Microsoft",                  "ticker": "MSFT", "category": "technology"},
    {"cik": "1652044",  "firm": "Alphabet",                   "ticker": "GOOGL","category": "technology"},
    {"cik": "858877",   "firm": "Cisco Systems",              "ticker": "CSCO", "category": "technology"},
    {"cik": "51143",    "firm": "IBM",                        "ticker": "IBM",  "category": "technology"},
    {"cik": "1341439",  "firm": "Oracle",                     "ticker": "ORCL", "category": "technology"},
    {"cik": "1108524",  "firm": "Salesforce",                 "ticker": "CRM",  "category": "technology"},
    {"cik": "1327567",  "firm": "Palo Alto Networks",         "ticker": "PANW", "category": "technology"},
    {"cik": "1517396",  "firm": "CrowdStrike Holdings",       "ticker": "CRWD", "category": "technology"},
    {"cik": "1262039",  "firm": "Fortinet",                   "ticker": "FTNT", "category": "technology"},
    {"cik": "1660134",  "firm": "Okta",                       "ticker": "OKTA", "category": "technology"},
    {"cik": "1420580",  "firm": "Splunk",                     "ticker": "SPLK", "category": "technology"},
    {"cik": "1739942",  "firm": "SolarWinds",                 "ticker": "SWI",  "category": "technology"},
    {"cik": "1127703",  "firm": "Mandiant",                   "ticker": "MNDT", "category": "technology"},
    {"cik": "1462120",  "firm": "Qualys",                     "ticker": "QLYS", "category": "technology"},
    {"cik": "1560327",  "firm": "Rapid7",                     "ticker": "RPD",  "category": "technology"},
    {"cik": "1660417",  "firm": "Tenable Holdings",           "ticker": "TENB", "category": "technology"},
    {"cik": "1023767",  "firm": "SS&C Technologies",          "ticker": "SSNC", "category": "technology"},
    # Retail / hospitality — point-of-sale and guest-data breaches
    {"cik": "27419",    "firm": "Target Corporation",         "ticker": "TGT",  "category": "retail_hospitality"},
    {"cik": "354950",   "firm": "Home Depot",                 "ticker": "HD",   "category": "retail_hospitality"},
    {"cik": "1014473",  "firm": "Marriott International",     "ticker": "MAR",  "category": "retail_hospitality"},
    {"cik": "1501268",  "firm": "Hilton Worldwide",           "ticker": "HLT",  "category": "retail_hospitality"},
    {"cik": "789570",   "firm": "MGM Resorts International",  "ticker": "MGM",  "category": "retail_hospitality"},
    {"cik": "1722684",  "firm": "Wyndham Hotels and Resorts", "ticker": "WH",   "category": "retail_hospitality"},
    {"cik": "732717",   "firm": "AT&T",                       "ticker": "T",    "category": "retail_hospitality"},
    {"cik": "1283699",  "firm": "T-Mobile US",                "ticker": "TMUS", "category": "retail_hospitality"},
    {"cik": "101830",   "firm": "Verizon Communications",     "ticker": "VZ",   "category": "retail_hospitality"},
]
YEARS_A = [2019, 2020, 2021, 2022, 2023, 2024]


# ── Scenario B: Consumer ESG and Greenwashing Risk (2019-2024) ───────────
# ~60 firms across consumer staples, consumer discretionary, food & beverage,
# and retail — sectors facing heightened scrutiny from investors, regulators,
# and litigants over sustainability claims. Anchor events: SEC ESG disclosure
# proposals (2022), FTC Green Guides review (2022-2023), EU taxonomy
# (spillover to US disclosures), high-profile greenwashing suits (2021-2024).
SCENARIO_B = [
    # Consumer staples — household and personal care products
    {"cik": "80424",    "firm": "Procter and Gamble",         "ticker": "PG",   "category": "consumer_staples"},
    {"cik": "21665",    "firm": "Colgate-Palmolive",          "ticker": "CL",   "category": "consumer_staples"},
    {"cik": "21175",    "firm": "Clorox Company",             "ticker": "CLX",  "category": "consumer_staples"},
    {"cik": "55607",    "firm": "Kimberly-Clark",             "ticker": "KMB",  "category": "consumer_staples"},
    {"cik": "313927",   "firm": "Church and Dwight",          "ticker": "CHD",  "category": "consumer_staples"},
    {"cik": "1001250",  "firm": "Estee Lauder Companies",     "ticker": "EL",   "category": "consumer_staples"},
    {"cik": "890547",   "firm": "Revlon",                     "ticker": "REV",  "category": "consumer_staples"},
    {"cik": "1102119",  "firm": "Spectrum Brands",            "ticker": "SPB",  "category": "consumer_staples"},
    {"cik": "1365135",  "firm": "Central Garden and Pet",     "ticker": "CENT", "category": "consumer_staples"},
    # Consumer discretionary — apparel, footwear, luxury
    {"cik": "320187",   "firm": "Nike",                       "ticker": "NKE",  "category": "consumer_discretionary"},
    {"cik": "94845",    "firm": "Levi Strauss",               "ticker": "LEVI", "category": "consumer_discretionary"},
    {"cik": "1037038",  "firm": "Ralph Lauren",               "ticker": "RL",   "category": "consumer_discretionary"},
    {"cik": "78239",    "firm": "PVH Corp",                   "ticker": "PVH",  "category": "consumer_discretionary"},
    {"cik": "1359841",  "firm": "Hanesbrands",                "ticker": "HBI",  "category": "consumer_discretionary"},
    {"cik": "103379",   "firm": "VF Corporation",             "ticker": "VFC",  "category": "consumer_discretionary"},
    {"cik": "1116132",  "firm": "Tapestry",                   "ticker": "TPR",  "category": "consumer_discretionary"},
    {"cik": "1530721",  "firm": "Capri Holdings",             "ticker": "CPRI", "category": "consumer_discretionary"},
    {"cik": "1397187",  "firm": "Lululemon Athletica",        "ticker": "LULU", "category": "consumer_discretionary"},
    {"cik": "39911",    "firm": "Gap",                        "ticker": "GPS",  "category": "consumer_discretionary"},
    {"cik": "1336917",  "firm": "Under Armour",               "ticker": "UA",   "category": "consumer_discretionary"},
    # Food and beverage — sustainability claims under scrutiny
    {"cik": "1637459",  "firm": "Kraft Heinz",                "ticker": "KHC",  "category": "food_beverage"},
    {"cik": "16160",    "firm": "Campbell Soup Company",      "ticker": "CPB",  "category": "food_beverage"},
    {"cik": "40704",    "firm": "General Mills",              "ticker": "GIS",  "category": "food_beverage"},
    {"cik": "55793",    "firm": "Kellanova",                  "ticker": "K",    "category": "food_beverage"},
    {"cik": "1103982",  "firm": "Mondelez International",     "ticker": "MDLZ", "category": "food_beverage"},
    {"cik": "47111",    "firm": "Hershey Company",            "ticker": "HSY",  "category": "food_beverage"},
    {"cik": "91419",    "firm": "JM Smucker Company",         "ticker": "SJM",  "category": "food_beverage"},
    {"cik": "63754",    "firm": "McCormick and Company",      "ticker": "MKC",  "category": "food_beverage"},
    {"cik": "86312",    "firm": "Sysco Corporation",          "ticker": "SYY",  "category": "food_beverage"},
    {"cik": "1418819",  "firm": "Lamb Weston Holdings",       "ticker": "LW",   "category": "food_beverage"},
    {"cik": "1370946",  "firm": "TreeHouse Foods",            "ticker": "THS",  "category": "food_beverage"},
    {"cik": "1396033",  "firm": "Darling Ingredients",        "ticker": "DAR",  "category": "food_beverage"},
    {"cik": "1041514",  "firm": "Hain Celestial Group",       "ticker": "HAIN", "category": "food_beverage"},
    # Retail — sustainability disclosures and supply chain claims
    {"cik": "104169",   "firm": "Walmart",                    "ticker": "WMT",  "category": "retail"},
    {"cik": "27419",    "firm": "Target Corporation",         "ticker": "TGT",  "category": "retail"},
    {"cik": "909832",   "firm": "Costco Wholesale",           "ticker": "COST", "category": "retail"},
    {"cik": "354950",   "firm": "Home Depot",                 "ticker": "HD",   "category": "retail"},
    {"cik": "764478",   "firm": "Best Buy",                   "ticker": "BBY",  "category": "retail"},
    {"cik": "794367",   "firm": "Macys",                      "ticker": "M",    "category": "retail"},
    {"cik": "1096752",  "firm": "Kohls Corporation",          "ticker": "KSS",  "category": "retail"},
    {"cik": "72333",    "firm": "Nordstrom",                  "ticker": "JWN",  "category": "retail"},
    {"cik": "1666700",  "firm": "Dollar General",             "ticker": "DG",   "category": "retail"},
    {"cik": "40533",    "firm": "Dollar Tree",                "ticker": "DLTR", "category": "retail"},
    {"cik": "1018724",  "firm": "Amazon",                     "ticker": "AMZN", "category": "retail"},
    {"cik": "1531152",  "firm": "Five Below",                 "ticker": "FIVE", "category": "retail"},
    {"cik": "49519",    "firm": "Genuine Parts Company",      "ticker": "GPC",  "category": "retail"},
    {"cik": "886780",   "firm": "AutoZone",                   "ticker": "AZO",  "category": "retail"},
    {"cik": "866787",   "firm": "Advance Auto Parts",         "ticker": "AAP",  "category": "retail"},
    {"cik": "898173",   "firm": "OReilly Automotive",         "ticker": "ORLY", "category": "retail"},
]
YEARS_B = [2019, 2020, 2021, 2022, 2023, 2024]


# ── Scenario C: Pharmaceutical Liability and Opioid Litigation (2015-2024) ─
# ~55 firms across big pharma, specialty/generic pharma, wholesale
# distributors, and pharmacy chains. Long 10-year window captures the full
# litigation arc: early lawsuits (2017-2018), DOJ investigations, state AG
# settlements (2021-2022), and post-settlement disclosure evolution.
# Litigation status: "defendant" (named in opioid suits), "adjacent" (sector
# peers not named), "distributor", "pharmacy".
SCENARIO_C = [
    # Defendants — directly named in opioid litigation
    {"cik": "78003",    "firm": "Pfizer",                     "ticker": "PFE",  "category": "defendant", "litigation_status": "defendant"},
    {"cik": "200406",   "firm": "Johnson and Johnson",        "ticker": "JNJ",  "category": "defendant", "litigation_status": "defendant"},
    {"cik": "712034",   "firm": "Mallinckrodt",               "ticker": "MNK",  "category": "defendant", "litigation_status": "defendant"},
    {"cik": "1593034",  "firm": "Endo International",         "ticker": "ENDP", "category": "defendant", "litigation_status": "defendant"},
    {"cik": "310158",   "firm": "Merck",                      "ticker": "MRK",  "category": "defendant", "litigation_status": "defendant"},
    {"cik": "884629",   "firm": "Allergan",                   "ticker": "AGN",  "category": "defendant", "litigation_status": "defendant"},
    {"cik": "14272",    "firm": "Bristol-Myers Squibb",       "ticker": "BMY",  "category": "defendant", "litigation_status": "defendant"},
    {"cik": "1551152",  "firm": "AbbVie",                     "ticker": "ABBV", "category": "defendant", "litigation_status": "defendant"},
    {"cik": "1792044",  "firm": "Viatris",                    "ticker": "VTRS", "category": "defendant", "litigation_status": "defendant"},
    {"cik": "1423689",  "firm": "Amneal Pharmaceuticals",     "ticker": "AMRX", "category": "defendant", "litigation_status": "defendant"},
    # Wholesale distributors — named in state and federal suits
    {"cik": "927653",   "firm": "McKesson Corporation",       "ticker": "MCK",  "category": "distributor", "litigation_status": "defendant"},
    {"cik": "721371",   "firm": "Cardinal Health",            "ticker": "CAH",  "category": "distributor", "litigation_status": "defendant"},
    {"cik": "1140859",  "firm": "AmerisourceBergen",          "ticker": "ABC",  "category": "distributor", "litigation_status": "defendant"},
    {"cik": "897429",   "firm": "Henry Schein",               "ticker": "HSIC", "category": "distributor", "litigation_status": "adjacent"},
    {"cik": "732834",   "firm": "Patterson Companies",        "ticker": "PDCO", "category": "distributor", "litigation_status": "adjacent"},
    # Pharmacy chains
    {"cik": "64803",    "firm": "CVS Health",                 "ticker": "CVS",  "category": "pharmacy_chain", "litigation_status": "defendant"},
    {"cik": "1318284",  "firm": "Walgreens Boots Alliance",   "ticker": "WBA",  "category": "pharmacy_chain", "litigation_status": "defendant"},
    {"cik": "84129",    "firm": "Rite Aid",                   "ticker": "RAD",  "category": "pharmacy_chain", "litigation_status": "defendant"},
    # Specialty and generic pharma — adjacent or smaller defendants
    {"cik": "1267565",  "firm": "Collegium Pharmaceutical",   "ticker": "COLL", "category": "specialty_pharma", "litigation_status": "adjacent"},
    {"cik": "1555280",  "firm": "Avanir Pharmaceuticals",     "ticker": "AVNR", "category": "specialty_pharma", "litigation_status": "adjacent"},
    {"cik": "1091596",  "firm": "Jazz Pharmaceuticals",       "ticker": "JAZZ", "category": "specialty_pharma", "litigation_status": "adjacent"},
    {"cik": "1131554",  "firm": "BioDelivery Sciences",       "ticker": "BDSI", "category": "specialty_pharma", "litigation_status": "adjacent"},
    # Large pharma peers — sector context, not directly named
    {"cik": "59478",    "firm": "Eli Lilly and Company",      "ticker": "LLY",  "category": "big_pharma", "litigation_status": "adjacent"},
    {"cik": "318154",   "firm": "Amgen",                      "ticker": "AMGN", "category": "big_pharma", "litigation_status": "adjacent"},
    {"cik": "875045",   "firm": "Biogen",                     "ticker": "BIIB", "category": "big_pharma", "litigation_status": "adjacent"},
    {"cik": "868780",   "firm": "Gilead Sciences",            "ticker": "GILD", "category": "big_pharma", "litigation_status": "adjacent"},
    {"cik": "872589",   "firm": "Regeneron Pharmaceuticals",  "ticker": "REGN", "category": "big_pharma", "litigation_status": "adjacent"},
    {"cik": "875320",   "firm": "Vertex Pharmaceuticals",     "ticker": "VRTX", "category": "big_pharma", "litigation_status": "adjacent"},
    {"cik": "1095565",  "firm": "Alexion Pharmaceuticals",    "ticker": "ALXN", "category": "big_pharma", "litigation_status": "adjacent"},
    {"cik": "1374690",  "firm": "BioMarin Pharmaceutical",    "ticker": "BMRN", "category": "big_pharma", "litigation_status": "adjacent"},
    {"cik": "1492426",  "firm": "Horizon Therapeutics",       "ticker": "HZNP", "category": "big_pharma", "litigation_status": "adjacent"},
    # Pharmacy benefit managers and health services
]
YEARS_C = [2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024]


# ── Scenario D: Real Estate and Interest Rate Risk (2018-2024) ────────────
# ~65 firms across office, industrial, retail, and residential REITs, plus
# commercial real estate services. The 2018-2024 window captures the low-rate
# expansion, COVID disruption (2020), and the 2022-2023 rate hike cycle
# (Fed funds rate 0.25% → 5.50%), which repriced cap rates and triggered
# significant disclosure shifts around debt maturity, refinancing risk,
# and occupancy assumptions.
SCENARIO_D = [
    # Industrial REITs — strongest fundamentals through the cycle
    {"cik": "1045609",  "firm": "Prologis",                   "ticker": "PLD",  "category": "industrial_reit"},
    {"cik": "783280",   "firm": "Duke Realty",                "ticker": "DRE",  "category": "industrial_reit"},
    {"cik": "49600",    "firm": "EastGroup Properties",       "ticker": "EGP",  "category": "industrial_reit"},
    {"cik": "1571082",  "firm": "Rexford Industrial Realty",  "ticker": "REXR", "category": "industrial_reit"},
    {"cik": "921825",   "firm": "First Industrial Realty",    "ticker": "FR",   "category": "industrial_reit"},
    {"cik": "1520566",  "firm": "STAG Industrial",            "ticker": "STAG", "category": "industrial_reit"},
    {"cik": "731802",   "firm": "Terreno Realty",             "ticker": "TRNO", "category": "industrial_reit"},
    # Office REITs — most exposed to WFH disruption and rate hikes
    {"cik": "899689",   "firm": "Vornado Realty Trust",       "ticker": "VNO",  "category": "office_reit"},
    {"cik": "1040971",  "firm": "SL Green Realty",            "ticker": "SLG",  "category": "office_reit"},
    {"cik": "1037540",  "firm": "Boston Properties",          "ticker": "BXP",  "category": "office_reit"},
    {"cik": "790816",   "firm": "Brandywine Realty Trust",    "ticker": "BDN",  "category": "office_reit"},
    {"cik": "921082",   "firm": "Highwoods Properties",       "ticker": "HIW",  "category": "office_reit"},
    {"cik": "803649",   "firm": "Equity Commonwealth",        "ticker": "EQC",  "category": "office_reit"},
    {"cik": "1383312",  "firm": "Paramount Group",            "ticker": "PGRE", "category": "office_reit"},
    {"cik": "1617356",  "firm": "Easterly Government Properties","ticker": "DEA","category": "office_reit"},
    {"cik": "1411059",  "firm": "Columbia Property Trust",    "ticker": "CXP",  "category": "office_reit"},
    # Retail REITs — COVID decimated; rate hike secondary stress
    {"cik": "1063761",  "firm": "Simon Property Group",       "ticker": "SPG",  "category": "retail_reit"},
    {"cik": "912093",   "firm": "Macerich Company",           "ticker": "MAC",  "category": "retail_reit"},
    {"cik": "1937926",  "firm": "Brookfield Asset Management", "ticker": "BAM",  "category": "retail_reit"},
    {"cik": "910606",   "firm": "Regency Centers",            "ticker": "REG",  "category": "retail_reit"},
    {"cik": "1286043",  "firm": "Kite Realty Group Trust",    "ticker": "KRG",  "category": "retail_reit"},
    {"cik": "885508",   "firm": "PREIT",                      "ticker": "PEI",  "category": "retail_reit"},
    {"cik": "73124",    "firm": "CBL and Associates",         "ticker": "CBL",  "category": "retail_reit"},
    {"cik": "68875",    "firm": "Washington Prime Group",     "ticker": "WPG",  "category": "retail_reit"},
    # Residential REITs — rate hikes compressed multifamily valuations
    {"cik": "915912",   "firm": "AvalonBay Communities",      "ticker": "AVB",  "category": "residential_reit"},
    {"cik": "906107",   "firm": "Equity Residential",         "ticker": "EQR",  "category": "residential_reit"},
    {"cik": "74260",    "firm": "UDR",                        "ticker": "UDR",  "category": "residential_reit"},
    {"cik": "906163",   "firm": "Camden Property Trust",      "ticker": "CPT",  "category": "residential_reit"},
    {"cik": "922522",   "firm": "Essex Property Trust",       "ticker": "ESS",  "category": "residential_reit"},
    {"cik": "765880",   "firm": "Healthpeak Properties",      "ticker": "PEAK", "category": "residential_reit"},
    {"cik": "766704",   "firm": "Welltower",                  "ticker": "WELL", "category": "residential_reit"},
    {"cik": "740260",   "firm": "Ventas",                     "ticker": "VTR",  "category": "residential_reit"},
    # Data centre and specialty REITs
    {"cik": "1053507",  "firm": "American Tower",             "ticker": "AMT",  "category": "specialty_reit"},
    {"cik": "1051512",  "firm": "Crown Castle",               "ticker": "CCI",  "category": "specialty_reit"},
    {"cik": "1101239",  "firm": "Equinix",                    "ticker": "EQIX", "category": "specialty_reit"},
    {"cik": "1297996",  "firm": "Digital Realty Trust",       "ticker": "DLR",  "category": "specialty_reit"},
    {"cik": "1289490",  "firm": "Extra Space Storage",        "ticker": "EXR",  "category": "specialty_reit"},
    {"cik": "1393311",  "firm": "Public Storage",             "ticker": "PSA",  "category": "specialty_reit"},
    {"cik": "726728",   "firm": "Realty Income Corporation",  "ticker": "O",    "category": "specialty_reit"},
    {"cik": "1552198",  "firm": "STORE Capital",              "ticker": "STOR", "category": "specialty_reit"},
    {"cik": "1023600",  "firm": "National Retail Properties", "ticker": "NNN",  "category": "specialty_reit"},
    {"cik": "1277406",  "firm": "Spirit Realty Capital",      "ticker": "SRC",  "category": "specialty_reit"},
    {"cik": "1042776",  "firm": "Agree Realty",               "ticker": "ADC",  "category": "specialty_reit"},
    # Commercial real estate services — fee-for-service, rate sensitivity
    {"cik": "1138118",  "firm": "CBRE Group",                 "ticker": "CBRE", "category": "re_services"},
    {"cik": "896429",   "firm": "Jones Lang LaSalle",         "ticker": "JLL",  "category": "re_services"},
    {"cik": "1628871",  "firm": "Cushman and Wakefield",      "ticker": "CWK",  "category": "re_services"},
    {"cik": "1287098",  "firm": "Marcus and Millichap",       "ticker": "MMI",  "category": "re_services"},
    {"cik": "1577552",  "firm": "Newmark Group",              "ticker": "NMRK", "category": "re_services"},
    {"cik": "29989",    "firm": "Colliers International Group","ticker": "CIGI", "category": "re_services"},
    {"cik": "1585389",  "firm": "RMR Group",                  "ticker": "RMR",  "category": "re_services"},
]
YEARS_D = [2018, 2019, 2020, 2021, 2022, 2023, 2024]


# ---------------------------------------------------------------------------
# EDGAR helpers  (rate limiting and retry logic)
# ---------------------------------------------------------------------------

SESSION = requests.Session()
SESSION.headers.update(HEADERS)
_last_request = 0.0


def edgar_get(url: str, retries: int = 3) -> requests.Response:
    global _last_request
    elapsed = time.time() - _last_request
    if elapsed < RATE_SLEEP:
        time.sleep(RATE_SLEEP - elapsed)
    for attempt in range(retries):
        try:
            r = SESSION.get(url, timeout=30)
            _last_request = time.time()
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 10))
                log.warning("Rate-limited; sleeping %d s", wait)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r
        except requests.exceptions.Timeout:
            log.warning("Timeout on %s (attempt %d)", url, attempt + 1)
            time.sleep(5)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code < 500:
                raise
            log.warning("HTTP %s on %s (attempt %d)", e.response.status_code, url, attempt + 1)
            time.sleep(5)
    raise RuntimeError(f"Failed after {retries} attempts: {url}")


def get_submissions(cik: str) -> dict:
    url = f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"
    return edgar_get(url).json()


def find_10k_filings(cik: str, target_fiscal_years: list) -> list:
    subs = get_submissions(cik)
    results = []
    seen_years = set()

    def _scan_block(block):
        forms      = block.get("form", [])
        dates      = block.get("filingDate", [])
        accessions = block.get("accessionNumber", [])
        periods    = block.get("reportDate", [""] * len(forms))
        pdocs      = block.get("primaryDocument", [""] * len(forms))
        for form, date, acc, period, pdoc in zip(forms, dates, accessions, periods, pdocs):
            if form not in ("10-K", "10-K/A"):
                continue
            if period and len(period) >= 4:
                fy = int(period[:4])
            else:
                filing_year  = int(date[:4])
                filing_month = int(date[5:7])
                fy = filing_year - 1 if filing_month <= 4 else filing_year
            if fy in target_fiscal_years and fy not in seen_years:
                seen_years.add(fy)
                results.append({
                    "accession":   acc.replace("-", ""),
                    "filing_date": date,
                    "fiscal_year": fy,
                    "primary_doc": pdoc,
                })

    _scan_block(subs.get("filings", {}).get("recent", {}))

    for extra in subs.get("filings", {}).get("files", []):
        if len(seen_years) >= len(target_fiscal_years):
            break
        url = "https://data.sec.gov/submissions/" + extra["name"]
        try:
            extra_data = edgar_get(url).json()
            _scan_block(extra_data)
        except Exception as e:
            log.warning("Could not fetch extra filings page %s: %s", extra["name"], e)

    return results


def get_filing_doc_url(cik: str, accession: str, primary_doc: str = "") -> str | None:
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession}"

    if primary_doc and primary_doc.lower().endswith((".htm", ".html")):
        return f"{base}/{primary_doc}"

    acc_fmt = f"{accession[:10]}-{accession[10:12]}-{accession[12:]}"
    idx_url = f"{base}/index.json"
    try:
        idx = edgar_get(idx_url).json()
    except Exception as e:
        log.warning("Cannot fetch filing index %s: %s", acc_fmt, e)
        return None

    def _size(item):
        try:
            return int(item.get("size", 0))
        except (ValueError, TypeError):
            return 0

    items = idx.get("directory", {}).get("item", [])
    htm_items = [it for it in items if it["name"].lower().endswith((".htm", ".html"))]
    typed = sorted([it for it in htm_items if it.get("type") == "10-K"],
                   key=_size, reverse=True)
    if typed:
        return f"{base}/{typed[0]['name']}"
    others = sorted(htm_items, key=_size, reverse=True)
    if others:
        return f"{base}/{others[0]['name']}"
    return None


# ---------------------------------------------------------------------------
# Section extraction
# ---------------------------------------------------------------------------

SECTIONS = [
    (
        "item_1a",
        re.compile(r"item\s+1a[\.\-\s]*risk\s+factors", re.IGNORECASE),
        re.compile(r"item\s+1b[\.\-\s]|item\s+2[\.\-\s]", re.IGNORECASE),
    ),
    (
        "item_7",
        re.compile(r"item\s+7[\.\-\s]+management.{0,30}discussion", re.IGNORECASE),
        re.compile(r"item\s+7a[\s\.\-]|item\s+8[\s\.\-]", re.IGNORECASE),
    ),
]


def _html_to_text(html_bytes: bytes) -> str:
    soup = BeautifulSoup(html_bytes, "lxml")
    for tag in soup.find_all(style=re.compile(r"display\s*:\s*none", re.I)):
        tag.decompose()
    text = soup.get_text(separator=" ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def extract_section(text: str, start_pat: re.Pattern, end_pat: re.Pattern) -> str | None:
    MIN_BODY_CHARS = 100
    pos = 0
    for _ in range(6):
        m_start = start_pat.search(text, pos)
        if not m_start:
            return None
        tail = text[m_start.end():]
        m_end = end_pat.search(tail)
        body = tail[: m_end.start()] if m_end else tail[:600_000]
        body = re.sub(r"\s+", " ", body).strip()
        if len(body) >= MIN_BODY_CHARS:
            return body
        pos = m_start.end()
    return None


def download_sections(firm: dict, fiscal_year: int, filing: dict) -> list[dict]:
    cik = firm["cik"]
    acc = filing["accession"]

    doc_url = get_filing_doc_url(cik, acc, filing.get("primary_doc", ""))
    if not doc_url:
        log.warning("  No document URL: %s %s FY%d", firm["firm"], acc, fiscal_year)
        return []

    try:
        resp = edgar_get(doc_url)
    except Exception as e:
        log.warning("  Download failed: %s %s: %s", firm["firm"], acc, e)
        return []

    text = _html_to_text(resp.content)
    base = {k: firm.get(k, "") for k in ("cik", "firm", "ticker", "category")}
    base.update({
        "year":             fiscal_year,
        "filing_date":      filing["filing_date"],
        "accession_number": f"{acc[:10]}-{acc[10:12]}-{acc[12:]}",
    })
    # Scenario-specific extra columns
    if "litigation_status" in firm:
        base["litigation_status"] = firm["litigation_status"]

    rows = []
    for section_key, start_pat, end_pat in SECTIONS:
        body = extract_section(text, start_pat, end_pat)
        if body:
            row = dict(base)
            row["section"]    = section_key
            row["text"]       = body
            row["word_count"] = len(body.split())
            rows.append(row)
            log.info("  %s FY%d  %s  %d words", firm["firm"], fiscal_year, section_key, row["word_count"])
        else:
            log.warning("  %s FY%d  %s  NOT FOUND", firm["firm"], fiscal_year, section_key)

    return rows


# ---------------------------------------------------------------------------
# Scenario builders
# ---------------------------------------------------------------------------

COLUMNS = ["cik", "firm", "ticker", "category", "year", "section",
           "filing_date", "accession_number", "text", "word_count"]


def build_scenario(label: str, firms: list, target_years_fn, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "corpus.csv"

    done_keys: set[tuple] = set()
    rows: list[dict] = []
    if out_path.exists():
        existing = pd.read_csv(out_path, dtype=str)
        rows = existing.to_dict("records")
        done_keys = {(r["cik"], str(r["year"])) for r in rows}
        log.info("Resuming Scenario %s: %d rows already saved", label, len(rows))

    total_firms = len(firms)
    for i, firm in enumerate(firms, 1):
        cik  = firm["cik"]
        name = firm["firm"]
        target_years = target_years_fn(firm)

        log.info("[%s] %d/%d  %s (CIK %s)  years=%s", label, i, total_firms, name, cik, target_years)

        try:
            filings = find_10k_filings(cik, target_years)
        except Exception as e:
            log.error("  Cannot get submissions for %s: %s", name, e)
            continue

        if not filings:
            log.warning("  No 10-K filings found for %s in %s", name, target_years)
            continue

        for filing in filings:
            fy  = filing["fiscal_year"]
            key = (cik, str(fy))
            if key in done_keys:
                log.info("  Skipping %s FY%d (already saved)", name, fy)
                continue
            new_rows = download_sections(firm, fy, filing)
            rows.extend(new_rows)
            done_keys.add(key)

        if rows:
            pd.DataFrame(rows).to_csv(out_path, index=False)

    if rows:
        df = pd.DataFrame(rows)
        extra_cols = [c for c in df.columns if c not in COLUMNS]
        df[COLUMNS + extra_cols].to_csv(out_path, index=False)
        log.info("Scenario %s complete: %d rows -> %s", label, len(df), out_path)
    else:
        log.error("Scenario %s: no rows collected", label)


# ---------------------------------------------------------------------------
# Target-year helpers
# ---------------------------------------------------------------------------

def years_a(firm):  return YEARS_A
def years_b(firm):  return YEARS_B
def years_c(firm):  return YEARS_C
def years_d(firm):  return YEARS_D


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build AG983 assignment corpora from EDGAR")
    parser.add_argument("--scenario", choices=["A", "B", "C", "D", "all"],
                        default="all", help="Which scenario to build (default: all)")
    args = parser.parse_args()

    scenarios = {
        "A": (SCENARIO_A, years_a, DATA_ROOT / "scenario_a"),
        "B": (SCENARIO_B, years_b, DATA_ROOT / "scenario_b"),
        "C": (SCENARIO_C, years_c, DATA_ROOT / "scenario_c"),
        "D": (SCENARIO_D, years_d, DATA_ROOT / "scenario_d"),
    }

    to_run = ["A", "B", "C", "D"] if args.scenario == "all" else [args.scenario]

    for key in to_run:
        firms, year_fn, out_dir = scenarios[key]
        log.info("=" * 60)
        log.info("Starting Scenario %s  (%d firms)", key, len(firms))
        log.info("=" * 60)
        build_scenario(key, firms, year_fn, out_dir)

    log.info("All done. Output files:")
    for key in to_run:
        p = scenarios[key][2] / "corpus.csv"
        if p.exists():
            df = pd.read_csv(p)
            log.info("  scenario_%s/corpus.csv  %d rows", key.lower(), len(df))
        else:
            log.warning("  scenario_%s/corpus.csv  NOT FOUND", key.lower())
