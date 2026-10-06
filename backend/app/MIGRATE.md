# SCAN model migration — 5 Oct 2026

Brings VBC's scoring into line with the client's live workbook.
**All 8 real assessments now match exactly** — score, best, tolerance and
verdict, not just the verdict.

```
Before:  8/8 verdicts agree, 0/8 scores agree
After:   8/8 everything agrees
Suite:   573 passed, 52 skipped   (was 529 passed, 43 xfailed)
```

---

## 1. Replace these 10 files

| From this folder | Goes to |
|---|---|
| `domain/types.py` | `backend/app/domain/types.py` |
| `domain/scoring.py` | `backend/app/domain/scoring.py` |
| `catalog/scan.py` | `backend/app/catalog/scan.py` |
| `catalog/manual_fields.py` | `backend/app/catalog/manual_fields.py` |
| `catalog/surveillance.py` | `backend/app/catalog/surveillance.py` |
| `api/routes.py` | `backend/app/api/routes.py` |
| `tests/fixtures.py` | `backend/app/tests/fixtures.py` |
| `tests/test_scoring.py` | `backend/app/tests/test_scoring.py` |
| `tests/test_policy.py` | `backend/app/tests/test_policy.py` |
| `tests/test_workbook_parity.py` | `backend/app/tests/test_workbook_parity.py` |

Then, from `backend`:

```powershell
python -m pytest -q
```

Expect **573 passed, 52 skipped**. Stop here if it isn't.

---

## 2. Six defects fixed

| | Was | Now |
|---|---|---|
| 1 | Weights S .2 / C .1 / **A .6 / N .1** | **A .4 / N .3** |
| 2 | A = result, site visit, conflict, references | **A = the psychometric test's four dimensions** · site visit and conflict moved to N |
| 3 | A pillar counted parameters | **Weighted blend** (Integrity .5, Acumen .3, Risk .1, Problem Solving .1) — totals are fractional |
| 4 | `">10 Years"` unrecognised · `"Private Ltd"` = Green | **Spelling-insensitive matching** · `"Private Ltd"` = **Yellow** |
| 5 | `positives = G + Y // 2` — an odd Yellow thrown away | **`G + Y / 2`** — half a Green, as the workbook computes |
| 6 | Conflict of Interest: `"Positive"` = Green | **`"Negative"` = Green** — the ratings were backwards |

**Defect 6 is the one to read twice.** "Negative" means the conflict check came
back negative — no client employee behind this vendor. A vendor *with* a
conflict scored Green. It was written inverted and rated inverted, so the two
cancelled out in the total and showed the wrong colour on the report.

**Defect 4 is the one that did the damage.** An unrecognised option drops the
parameter from *both* sides of the fraction, so the vendor is measured only
against the questions we understood. Every approved vendor scored 100%.
Innovatiview showed as 100% where the client had them at 62.3% — barely over
the bar.

---

## 3. Also changed

**Turnover no longer writes a score.** It was `N3 "Turnover of the Vendor"`,
this codebase's own improvement on the client's model — an analyst estimate
replaced by a filed XBRL fact. Genuinely better, and not in the client's
workbook. `fin` still runs and revenue and net worth still render in the facts
layer; the figure just stopped silently moving a score under a heading nobody
agreed to. If the client wants it back it is a **new parameter with a new id**
— `N3` now means Conflict of Interest, and reusing the id would make two
different questions share one column of history.

Same for **Market References** (old A4) and **Big Players in Clientele**
(old N2). The manual field "Reference feedback" is kept but unmapped — useful
context for an analyst, no longer part of the arithmetic.

**Azahan's S3 is now `None`, not `"No"`.** Its `cdx` check is SKIPPED, and a
check that never ran must not write a rating. That is the difference between
"we looked and found nothing" and "we never looked".

---

## 4. Deploy

```bash
ssh root@46.202.164.88
cd /var/www/VBC && git pull
cd backend && source .venv/bin/activate
python -m app.db.seed          # REQUIRED — see below
systemctl restart vbc-api
```

**The seeder is not optional.** Catalog versions are content-hashed: changing
the parameters changes the hash, and `active_catalog_version()` raises rather
than guessing if no row matches the running code. Skip the seeder and scoring
fails loudly — which is the correct behaviour, and will look like a broken
deploy if you are not expecting it.

Existing `vendor_scores` rows keep their old `catalog_version_id` and stay
reconstructable. Nothing historical is rewritten.

---

## 5. The data fix — two real rows

From the server audit: three vendors, almost all Not-Applicable placeholders.
Exactly two rows hold anything that needs handling.

```sql
BEGIN;

-- 1. Move the one real site-surveillance result from A2 to N2.
--    A2 now means "Business Acumen"; leaving "Positive" there would make a
--    field visit read as a psychometric score.
INSERT INTO scan_ratings (vendor_id, param_id, value, rating, set_by, set_at)
SELECT vendor_id, 'N2', value, rating, set_by, set_at
  FROM scan_ratings
 WHERE param_id = 'A2' AND value IS NOT NULL
ON CONFLICT (vendor_id, param_id) DO UPDATE
   SET value  = EXCLUDED.value,
       rating = EXCLUDED.rating,
       set_by = EXCLUDED.set_by,
       set_at = EXCLUDED.set_at;

-- 2. Clear the old A pillar entirely. None of these vendors took the
--    psychometric test, and every A row is either the moved surveillance
--    result or a Not-Applicable placeholder under a heading that has
--    changed meaning.
DELETE FROM scan_ratings WHERE param_id IN ('A1', 'A2', 'A3', 'A4');

-- 3. "Private Ltd" is Yellow now, not Green.
UPDATE scan_ratings SET rating = 'Y'
 WHERE param_id = 'S1' AND value = 'Private Ltd';

COMMIT;
```

Then confirm:

```sql
SELECT param_id, value, rating, set_by, COUNT(*)
  FROM scan_ratings GROUP BY 1,2,3,4 ORDER BY 1;
```

You should see `N2 | Positive | G | surveillance` and
`S1 | Private Ltd | Y | system`, and no `A1`–`A4` rows at all.

**Stored `">10 Years"` spellings need no fix.** `ScanParameter.rate()` now
compares on letters and digits only, so `"> 10 Years"` and `">10 Years"`
resolve to the same answer. Old rows keep working; that was deliberate.

---

## 6. What this changes about the numbers

The two internal demo fixtures move, and both move in the honest direction:

| | Before | After |
|---|---|---|
| Meridian (the healthy case) | 97.4% | **89.7%** |
| Azahan (the thin audit) | 60.0%, passing | **70.0% on 5 of 18 parameters** |

Meridian drops because "Private Ltd" stopped being a free Green. Azahan's
headline went *up* while its coverage got thinner — which is exactly why
`coverage_note` travels with every score and why the default policy gates it
to senior review rather than trusting the percentage.

One structural improvement falls out of defect 2: **nothing automated feeds
the A pillar any more.** Conflict of Interest used to sit there, it is free,
and it passes by default — so the cheapest check in the catalogue could help
satisfy an assessment floor. The only way to satisfy A now is to actually run
the psychometric test on the vendor. `test_no_free_check_can_satisfy_the_assessment_floor`
pins that shut.
