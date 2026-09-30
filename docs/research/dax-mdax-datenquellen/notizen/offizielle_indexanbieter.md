# Official index-provider sources for DAX/MDAX constituents (STOXX / Deutsche Börse / ISS STOXX), status 29 Sep 2026

Method note: all "observed" statements below come from direct HTTP requests (curl, browser User-Agent, and curl's default UA) made on 2026-09-29 from a German residential IPv6 address. HTTP status codes and file contents are quoted as observed. Where a URL is cited as the source of an observation, it is the URL I fetched.

## 1. Which official pages/files exist today listing DAX/MDAX composition?

### Takeaway
Of all the official files, only one is both free and complete: the **monthly "Public Selection List"** (`slpublic_<symbol>_<YYYYMMDD>.csv`) on stoxx.com. It ranks all ~360 eligible stocks and has an `Index Membership` column (DAXK / MKDX / SDXK). Filtering that column gives exactly 40 DAX and 50 MDAX members with ISIN and RIC. The daily composition/components files do exist, but they are for licensees only. The public index pages show only the top 10 components.

### Cited Findings
- **Public Selection List (verified, works without login).** Observed `https://www.stoxx.com/document/Reports/DAXSelectionList/2026/September/slpublic_daxk_20260902.csv` → HTTP 200, `text/csv`, 39 KB. Header: `Creation_Date;Index_Symbol;Index_Name;Index ISIN;Internal_Key;ISIN;RIC;Instrument_Name;Country;Currency;Exchange;Index Membership;Rank (FINAL);Rank (PREVIOUS);Comment;Rank 2 (FINAL);Rank 2 (PREVIOUS)`. The file has 357 rows. `Index Membership` counts: DAXK=40, MKDX=50, SDXK=70, empty=197. — [slpublic_daxk_20260902.csv](https://www.stoxx.com/document/Reports/DAXSelectionList/2026/September/slpublic_daxk_20260902.csv)
- The MDAX file `slpublic_mkdx_YYYYMMDD.csv` has the same structure and the same ranked universe, with Index_Symbol=MKDX. The August files `slpublic_daxk_20260804.csv` and `slpublic_mkdx_20260804.csv` also returned 200 / text/csv (~9.8 KB). — [slpublic_mkdx_20260804.csv](https://www.stoxx.com/documents/stoxxnet/Documents/Reports/DAXSelectionList/2026/August/slpublic_mkdx_20260804.csv)
- STOXX's selection-lists page says: "Access to the files with prefix 'slpublic' in the file name is unrestricted. Access to remaining files are reserved to STOXX Index licensees based on valid Third-Party Data Licenses." — [STOXX Selection Lists](https://www.stoxx.com/selection-lists)
- STOXX Technical Information (26 Oct 2023) introduced the `slpublic_xxxxx_YYYYMMDD.csv` naming, replacing the old `sl_xxxxx_YYYYMM.csv`, from the March 2024 publication onwards. It says the files "are disseminated on a monthly basis on the 3rd trading day at 22:00 CET and are publicly available on www.stoxx.com > Resources > Reports > Selection Lists", and that they contain "Internal_key, the RIC (Refinitiv ID) and the Exchange". — [STOXX Technical Information, DAX Selection Lists, 2023-10-26](https://www.stoxx.com/document/News/2023/October/Technical_Information_DAX_Selection_Lists_and_Review_Files_New_file_name_and_format_change_20231026.pdf)
- **Daily composition/components files exist but are licensee-only.** STOXX publishes a public "index reports links" CSV (≈34 MB, `;`-separated) with URL templates per index. For DAX: `.../Indices/Current/Composition_Files/opencomposition_dax_YYYYMMDD.csv`, `closecomposition_dax_YYYYMMDD.csv` and `.../Indices/otherinformation/components/components_P000_daxk_YYYYMMDD.csv`. For MDAX the templates are `..._mdax_...` and `components_P00x_mkdx_...`. The same row also gives the Bloomberg code ("DAX INDEX", "MDAX INDEX") and the Reuters code (".GDAXI", ".MDAXI"). — [index_reports_links.csv](https://www.stoxx.com/document/Resources/Data_Vendor_Codes/index_reports_links.csv)
- Observed: `closecomposition_dax_20260928.csv` with no User-Agent → **HTTP 302 to `https://www.stoxx.com/c/portal/login?redirect=...`**. With a browser User-Agent the same URL, and the `opencomposition`, `closecomposition_mdax` and `components_P000_daxk` URLs for 25/28/29 Sep 2026, returned **HTTP 403 from Cloudflare** ("Sorry, you have been blocked"). So these files need a login and a licence. — [closecomposition_dax_20260928.csv](https://www.stoxx.com/document/Indices/Current/Composition_Files/closecomposition_dax_20260928.csv)
- **Index pages (public HTML) show only the "Top 10 Components".** Examples: DAX lists SIEMENS, SAP, ALLIANZ, … DHL; MDAX lists LUFTHANSA, TALANX, THYSSENKRUPP, … AIXTRON. There is no full list and no ISINs. `https://www.stoxx.com/index-details?symbol=DAX` and the legacy `https://www.dax-indices.com/index-details?isin=DE0008469008` both redirect to `https://stoxx.com/index/DAX/`. — [stoxx.com/index/dax](https://stoxx.com/index/dax/); [stoxx.com/index/mdax](https://stoxx.com/index/mdax/)
- The public quote API linked from the index page, `https://quotes.stoxx.com/api/v2/quote/delayed/series?isin=DE0008467416`, returned HTTP 401 `{"error_message":"Unauthorized"}`. — [quotes.stoxx.com](https://quotes.stoxx.com/api/v2/quote/delayed/series?isin=DE0008467416)
- **Factsheets are public PDFs but stale and incomplete.** `https://www.stoxx.com/document/Bookmarks/CurrentFactsheets/MDAX.pdf` → 200. It shows only the 5 largest components, and its data is "as of December 29, 2023". — [MDAX factsheet](https://www.stoxx.com/document/Bookmarks/CurrentFactsheets/MDAX.pdf)
- **"Historical Index Compositions of DAX Equity Indices" PDF (dated 21 September 2026, public, 200).** It has 59 pages covering DAX, TecDAX, MDAX, SDAX and others. It lists the initial composition and then every change with dates (e.g. DAX 22.06.2026: Porsche Automobil Holding Pref out, Hochtief in). It gives company names only, no ISIN, so it is change history rather than a machine-readable current list. — [Historical_Index_Compositions.pdf](https://www.stoxx.com/document/Indices/Common/Indexguide/Historical_Index_Compositions.pdf)
- **Press releases and index updates:** STOXX publishes review announcements. Example from 3 Sep 2026: no DAX changes; MDAX adds Ströer and removes Hugo Boss; effective 21 Sep 2026; next review 3 Dec 2026. These give names only. — [STOXX announces scheduled adjustments to DAX blue-chip indices (Sep 3, 2026)](https://stoxx.com/stoxx-announces-scheduled-adjustments-to-dax-blue-chip-indices-sep-3-2026/); [Index reviews category](https://stoxx.com/category/index-reviews/); [Index Updates](https://www.stoxx.com/index-updates)
- The DAX Files Guide (Nov 2022, pre-migration) described the Index Composition Report `xxxxx_ICR.YYYYMMDD.xls` as "publicly available on the DAX Website for licensed users". — [DAX_files_guide.pdf](https://www.stoxx.com/documents/dax-indices/Documents/Resources/Brochures/DAX_files_guide.pdf) (via search snippet)
- Observed: `vendor_codes_dax.xls`, which the Data Vendor Codes page links to, returned 404. The `dax_equity_index_family_esg_reports.csv` file is public (200) but contains only index-level ESG metrics, no constituents. — [Data Vendor Codes](https://www.stoxx.com/data-vendor-codes); [esg csv](https://www.stoxx.com/documents/stoxxnet/Documents/Indices/otherinformation/esgreporting/dax_equity_index_family_esg_reports.csv)

### Inferences
- For a weekly screener, the only official, free, machine-readable source is the monthly slpublic file. Filter `Index Membership ∈ {DAXK, MKDX}`. The `daxk` file alone covers both indices, and SDAX as well.
- Either file (daxk or mkdx) is enough, because both contain the whole ranked universe with the membership column.

### Gaps
- I did not look inside the licensee-only composition files, so I cannot say which fields they contain (weights, shares, etc.) beyond what the file guide describes.
- I did not assess Deutsche Börse's exchange site (live.deutsche-boerse.com / boerse-frankfurt.de "zugehörige Werte"). It returned 200, but the full list is rendered client-side: only one ISIN appeared in the static HTML. It is an exchange data portal, not the index provider, so it is out of scope here.

## 2. Login/registration or paid licence? Free files after the migration from dax-indices.com?

### Takeaway
- **Public selection lists:** free, with no login or registration.
- **Daily open/close composition and components files, and weightings:** STOXX login plus a licence (third-party data licence, P000–P003 entitlement codes).
- **Pre-migration dax-indices.com file URLs:** these are dead.

### Cited Findings
- slpublic files: HTTP 200 without cookies, login or special headers, including with curl's default User-Agent. — observed, [slpublic_daxk_20260902.csv](https://www.stoxx.com/document/Reports/DAXSelectionList/2026/September/slpublic_daxk_20260902.csv)
- The file names carry entitlement codes "P###" "to account for the Third-Party data license entitlement". Licensee selection lists are `sl_P###_xxxxx_YYYYMMDD.csv`, and component/underlying data announcements are `qr_P###_xxxxx_YYYYMMDD.csv`. — [Technical Information 2023-10-26](https://www.stoxx.com/document/News/2023/October/Technical_Information_DAX_Selection_Lists_and_Review_Files_New_file_name_and_format_change_20231026.pdf)
- Migration timeline: the new Index Data Distribution System (stoxx.com web and iSFTP) went live for DAX equity indices on **5 March 2024**. The old MD&Si system was terminated on 15 March 2024. — same source
- The STOXX Conditions of Use say component-level data, weightings and historical index adjustments are restricted to licensed subscribers, and prohibit accessing password-protected areas "without first registering a user account ... and/or entering into a License Agreement". — [STOXX Conditions of Use](https://stoxx.com/legal/stoxx-conditions-of-use/)
- Legacy URLs, observed: `https://www.dax-indices.com/` redirects to `https://stoxx.com/`. `https://www.dax-indices.com/document/Resources/WeightingFiles/Composition/2026/September/DAX_ICR.20260928.xls` returned 404, as did the same path on stoxx.com. The old public ranking lists `sl_xxxxx_YYYYMM.csv` were replaced in March 2024. — observed; [Technical Information 2023-10-26](https://www.stoxx.com/document/News/2023/October/Technical_Information_DAX_Selection_Lists_and_Review_Files_New_file_name_and_format_change_20231026.pdf)
- `https://www.qontigo.com/` gave no response (curl connection failure / timeout). Qontigo branding is outdated; the documents now say "ISS STOXX". — observed; [Historical_Index_Compositions.pdf cover](https://www.stoxx.com/document/Indices/Common/Indexguide/Historical_Index_Compositions.pdf)

### Inferences
- **Outdated, pre-March-2024:** any tutorial or GitHub scraper that uses dax-indices.com `*_ICR.*.xls`, `*_RKC.*.xls` or `sl_*_YYYYMM.csv` URLs.
- I found no price for a private STOXX data licence. Licences are aimed at institutions, so this is realistically not an option for a private user.

### Gaps
- I did not obtain a STOXX licence price list for private or non-professional use.

## 3. Exact URLs / URL patterns, stability, scrape-friendliness

### Takeaway
- **Stable part:** the download URL pattern is stable and static CSV.
- **Unpredictable part:** the date in the file name, which is the data/cut-off date (2nd trading day of the month). It is easiest to get from a public JSON endpoint behind the selection-lists page.
- **Blocking risk:** stoxx.com is behind Cloudflare. Some www.stoxx.com paths returned 403 during testing, but the slpublic CSV and the JSON endpoint did not.

### Cited Findings
- File URL pattern (observed working):
  `https://www.stoxx.com/document/Reports/DAXSelectionList/{YYYY}/{MonthName}/slpublic_{daxk|mkdx|sdxk|tdxk}_{YYYYMMDD}.csv`
  The long form `https://www.stoxx.com/documents/stoxxnet/Documents/Reports/DAXSelectionList/...` 307-redirects to the short form. `{MonthName}` is the English month name (e.g. `September`). — observed
- File-name dates, observed: August list `..._20260804.csv`, published "2026-08-05 22:01"; September list `..._20260902.csv`, published "2026-09-03 22:01". The file date is therefore one trading day before publication (publication = 3rd trading day). — observed via the JSON endpoint below
- **JSON discovery endpoint** (used by the page's jQuery; observed working with plain GET, no login):
  `GET https://www.stoxx.com/web/stoxxcom/selection-lists?p_p_id=STOXXNewSelectionlistportlet_WAR_STOXXNewSelectionlistportlet&p_p_lifecycle=2&p_p_state=normal&p_p_mode=view&p_p_cacheability=cacheLevelPage&p_p_col_id=column-1&p_p_col_count=2&_STOXXNewSelectionlistportlet_WAR_STOXXNewSelectionlistportlet_cmd=getDaxSLData&_STOXXNewSelectionlistportlet_WAR_STOXXNewSelectionlistportlet_fromdate=September%202026&_STOXXNewSelectionlistportlet_WAR_STOXXNewSelectionlistportlet_todate=September%202026&_STOXXNewSelectionlistportlet_WAR_STOXXNewSelectionlistportlet_symbols=daxk,mkdx`
  - Returns `{"status_code":"200","data":"[...]"}`. `data` is a JSON string with objects `{symbol, fullName, slpublic: "<a href='documents/stoxxnet/Documents/Reports/DAXSelectionList/2026/September/slpublic_daxk_20260902.csv'>", LastUpdate, ...}`.
  - Month format must be "September 2026"; "2026-09" or "09/2026" return an empty list.
  - The page JS allows at most 10 symbols per request and a range of at most 12 months. `cmd=getStoxxSLData` is the STOXX (non-DAX) variant.
  - The observed request goes to www.stoxx.com/selection-lists (a 307 moves `/web/stoxxcom/` requests there); passing session cookies from a prior page load returned data reliably. — observed; [STOXX Selection Lists page](https://www.stoxx.com/selection-lists)
- Cloudflare behaviour, observed:
  - 403 "Sorry, you have been blocked" (browser UA) for `https://www.stoxx.com/terms-of-use` and `https://www.stoxx.com/web/dax-indices/resources`, and for licensed composition files whose login redirect was followed.
  - slpublic CSVs and the JSON endpoint were never blocked across about 10 requests.
  - robots.txt for www.stoxx.com disallows only one registration URL; robots.txt for stoxx.com (WordPress) has `Disallow:` (nothing disallowed). — [www.stoxx.com/robots.txt](https://www.stoxx.com/robots.txt); [stoxx.com/robots.txt](https://stoxx.com/robots.txt)
- Two-host architecture: stoxx.com (WordPress: index pages, press releases, legal) and www.stoxx.com (Liferay portal: `/document/...` files, selection lists, data vendor codes). — observed (wp-json endpoints on stoxx.com, `p_p_id` portlets on www.stoxx.com)
- Python note from the local test: `requests.get()` on the slpublic URL failed with `SSLCertVerificationError` on this Windows Python 3.11 install, while curl succeeded. This is almost certainly a local CA-bundle issue (fix with `certifi` / an up-to-date image), not STOXX behaviour. — observed

### Inferences
- **Recommended robust approach:**
  1. Call the JSON endpoint for the current month and the previous month.
  2. Take the newest `slpublic_daxk_*.csv` link.
  3. Download it and filter `Index Membership`.
  4. If the endpoint fails, try `YYYYMMDD` candidates for the first 1–5 business days of the month against the file URL pattern.
  5. Keep the existing Wikipedia source and the fallback CSV as backups.
- The pattern has been stable since March 2024, about 2.5 years. The previous pattern change came with the platform migration and was announced about 5 months ahead. The 2023 notice is an example of how STOXX communicates such changes.

### Gaps
- There is no long-term observation of how often Cloudflare blocks datacenter or NAS IPs; testing was from one residential IP only.
- The trading-day logic for the file date is inferred from two months only.

## 4. Identifiers included and mapping to Yahoo tickers

### Takeaway
The slpublic file gives **ISIN**, **Refinitiv RIC** (e.g. `SAPG.DE`), instrument name, country, currency, exchange and ranks. It has **no Xetra/exchange symbol**, and the RIC root usually differs from the Yahoo symbol. The safe mapping key is the **ISIN**.

### Cited Findings
- Example rows from the September 2026 list: `DE0007236101;SIEGn.DE;SIEMENS`, `DE0008404005;ALVG.DE;ALLIANZ`, `DE0007164600;SAPG.DE;SAP`, `DE000AUM0V10;AMV0n.DE;AUMOVIO`, `DE000TKMS001;TKMS.DE;TKMS`, `DE000PAG9113;P911_p.DE;DR ING HC F PORSCHE PREF.`.
  - All 90 DAX/MDAX members have RIC suffix `.DE` and `Exchange` = "Deutsche Boerse".
  - ISIN countries: DE 86, NL 2 (Airbus, Qiagen), LU 2 (Aroundtown, RTL).
  - Preference shares use `_p` (e.g. `VOWG_p.DE`, `HNKG_p.DE`, `SATG_p.DE`, `FPE3_p.DE`). — [slpublic_daxk_20260902.csv](https://www.stoxx.com/document/Reports/DAXSelectionList/2026/September/slpublic_daxk_20260902.csv)
- Index-level vendor codes: DAX Bloomberg "DAX INDEX", Reuters ".GDAXI"; MDAX "MDAX INDEX", ".MDAXI". — [index_reports_links.csv](https://www.stoxx.com/document/Resources/Data_Vendor_Codes/index_reports_links.csv)

### Inferences
- A rule that turns RIC into a Yahoo ticker by stripping the Reuters suffixes (`G`, `n`, `Gn`, and `_p`→`p`) does not work reliably. For example, SIEGn.DE maps to Yahoo SIE.DE, and RHMG.DE maps to RHM.DE; there is no consistent rule.
- **Better:** keep an ISIN→Yahoo mapping table, for example in the project's existing `data/dax_mdax_fallback.csv`. Resolve new ISINs through yfinance search or OpenFIGI, and log any ISIN that is not yet mapped.

### Gaps
- I did not test automated ISIN→Yahoo resolution (yfinance `Search`, OpenFIGI). That belongs to another research strand.

## 5. Terms of use: automated download for private use?

### Takeaway
The STOXX and DAX Conditions of Use **explicitly forbid** crawlers, scrapers, bots and headless browsers, and forbid downloading, saving or redistributing "Data". They also reserve rights against text and data mining (Art. 4(3) of the DSM Directive). This is in tension with the statement that slpublic files are "unrestricted". A weekly automated download is therefore a **legal grey area / technically in breach of the Conditions of Use**, even for private use, unless STOXX gives written permission.

### Cited Findings
- STOXX Conditions of Use:
  - "You may view the Data on screen for your own internal information and reference purposes only, and on a non-commercial basis."
  - "You must not use any crawler, robot, spider, scraper, bot, headless browser or similar automated means to access, copy, monitor or extract any part of the Website or any Data."
  - Downloading, saving, printing, copying and redistributing are prohibited; the prohibition applies to unrestricted, additional and restricted data alike.
  - STOXX reserves rights under Art. 4(3) of Directive (EU) 2019/790 and "does not consent to any text or data mining".
  - "Nothing contained in the Website may be construed as granting any license or right to use any index ... without entering into a License Agreement".
  - The findings above come from a WebFetch summary with verbatim quotes. — [STOXX Conditions of Use](https://stoxx.com/legal/stoxx-conditions-of-use/)
- The DAX Conditions of Use contain the same view-only, no-crawler and no-download clauses, and add that constituent-level data needs licensing. — [DAX Conditions of Use](https://stoxx.com/legal/dax-conditions-of-use/)
- In contrast: "Access to the files with prefix 'slpublic' in the file name is unrestricted." — [STOXX Selection Lists](https://www.stoxx.com/selection-lists)

### Inferences
- "Unrestricted" most plausibly means "no licence entitlement needed to open the file". It does not look like a waiver of the no-scraping clause.
- The practical risks for one GET per week for private screening are low: IP blocking, or the file format changing. The legal risk is not zero.
- **Cleanest option:** email customersupport@iss-stoxx.com (the address shown on the site) and ask for written permission for a weekly private download.
- **Redistribution:** the batch should not publish the constituent list. It is only used internally to pick tickers, and the email report only contains the user's own scores.

### Gaps
- There is no public statement from STOXX on tolerating low-frequency personal automated access. I found no case law or enforcement examples.

## 6. How promptly are changes (reviews, fast entry/exit, spin-offs) reflected?

### Takeaway
The public selection list shows **membership as of its cut-off date** (2nd trading day of the month). Quarterly review changes, which take effect on the Monday after the 3rd Friday of Mar/Jun/Sep/Dec, therefore only appear in the **next** month's list, about 2 weeks late. Spin-offs that were added to the index during the month (Aumovio, TKMS) already show as MDAX members once a list is published after the addition.

### Cited Findings
- September 2026 list (Creation_Date 20260902): Hugo Boss is still `MKDX`, while Ströer is still `SDXK`, rank 90. The review announced on 3 Sep 2026 swaps them effective 21 Sep 2026, so the list lags the effective change. — observed file; [STOXX Sep 3, 2026 announcement](https://stoxx.com/stoxx-announces-scheduled-adjustments-to-dax-blue-chip-indices-sep-3-2026/)
- The same list shows Aumovio (DE000AUM0V10) and TKMS (DE000TKMS001) as `MKDX`, and Hochtief (DE0006070006) as `DAXK`, reflecting the June 2026 DAX change. Porsche Automobil Holding Pref (`PSHG_p.DE`) shows as `MKDX`. — observed file; DAX change of 22.06.2026 per [Historical_Index_Compositions.pdf](https://www.stoxx.com/document/Indices/Common/Indexguide/Historical_Index_Compositions.pdf)
- The DAX index page describes the reviews: "reviewed quarterly based on the Fast Exit and Fast Entry rules and semi-annually based on the Regular Exit and Regular Entry rules". The next scheduled review announcement is 3 Dec 2026. — [stoxx.com/index/dax](https://stoxx.com/index/dax/); [STOXX Sep 3, 2026 announcement](https://stoxx.com/stoxx-announces-scheduled-adjustments-to-dax-blue-chip-indices-sep-3-2026/)
- The Historical Index Compositions PDF was updated for the September 2026 review effective date (cover dated 21 September 2026). — [Historical_Index_Compositions.pdf](https://www.stoxx.com/document/Indices/Common/Indexguide/Historical_Index_Compositions.pdf)

### Inferences
- For a value screener, a lag of up to about 2 weeks in 4 windows per year is irrelevant: one stock too many or too few among 90.
- If exactness matters, apply the announced changes from the press releases manually to the fallback CSV. Alternatively, the "Rank (FINAL)" column lets you anticipate changes.
- **Timing gap:** the Selection List is compiled on the 2nd trading day, but the review announcement (3rd trading day of the review month) uses the same data. So in March/June/Sep/Dec the list the announcement is based on is available the same evening, but the membership column still shows the old composition.

### Gaps
- I did not verify the exact date on which the Aumovio and TKMS spin-off additions first appeared in a slpublic file; that would need the older monthly files (Sep/Oct 2025).
- I did not check whether the October 2026 list (published around 5 Oct 2026) will already show the 21 Sep changes. This is expected but not yet observable.
