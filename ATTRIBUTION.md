# Licensing and attribution

This repository uses a **split license**: the software and the educational content are
licensed differently on purpose.

| What | License | File |
|---|---|---|
| **Source code** — the Flask app, templates, scripts, tooling | **Apache License 2.0** | [`LICENSE`](LICENSE) |
| **Educational content** — question bank, explanations, lessons, misconception library, key-term glossary | **CC BY-NC-SA 4.0** | [`LICENSE-CONTENT`](LICENSE-CONTENT) |
| **Third-party material** | per its own license | this file, below |

## Why the split

The code carries no competitive value — permissive licensing maximises adoption, which is
the point of releasing it. The content is the asset, and a NonCommercial + ShareAlike license
is what stops someone from taking the question bank behind a closed paywall. It is also the
same posture OpenStax itself now uses, so there is no inconsistency between what we ship and
what we build on — and, as it happens, it is the *only* posture available to us, because the
source material this bank was built from is itself NonCommercial (see below).

Under **CC BY-NC-SA 4.0** you may use, adapt and redistribute the content freely for
non-commercial purposes, as long as you attribute it, keep it under the same license, and
indicate any changes. Commercial use requires written permission from Mu2 Solutions, LLC.

> **Note for anyone planning to commercialise a derivative:** because the source textbooks are
> licensed CC BY-NC-SA 4.0, this content cannot be relicensed commercially without replacing the
> source material. That is a deliberate consequence, not an oversight.

---

# Third-party attribution

## OpenStax — science and mathematics source material

Question explanations, lesson text, and key-term definitions in this project are derived from
OpenStax textbooks. Each of the editions used is licensed
**Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0)**
by Rice University. The required attribution for each follows.

### Anatomy and Physiology 2e

> J. Gordon Betts, Peter DeSaix, Eddie Johnson, Jody E. Johnson, Oksana Korol, Dean Kruse,
> Brandon Poe, James A. Wise, Mark Womble, and Kelly A. Young. **Anatomy and Physiology 2e.**
> OpenStax, Rice University, 2026.
> <https://openstax.org/details/books/anatomy-and-physiology-2e>

### Chemistry 2e

> Paul Flowers, Klaus Theopold, Richard Langley, and William R. Robinson. **Chemistry 2e.**
> OpenStax, Rice University, 2026.
> <https://openstax.org/details/books/chemistry-2e>

### College Physics 2e

> Paul Peter Urone and Roger Hinrichs. **College Physics 2e.**
> OpenStax, Rice University, 2026.
> <https://openstax.org/details/books/college-physics-2e>

### Elementary Algebra 2e

> Lynn Marecek, MaryAnne Anthony-Smith, and Andrea Honeycutt Mathis. **Elementary Algebra 2e.**
> OpenStax, Rice University, 2026.
> <https://openstax.org/details/books/elementary-algebra-2e>

### Prealgebra 2e

> Lynn Marecek, MaryAnne Anthony-Smith, and Andrea Honeycutt Mathis. **Prealgebra 2e.**
> OpenStax, Rice University, 2026.
> <https://openstax.org/details/books/prealgebra-2e>

### Microbiology

> Nina Parker, Mark Schneegurt, Anh-Hue Thi Tu, Philip Lister, and Brian M. Forster.
> **Microbiology.** OpenStax, Rice University, 2026.
> <https://openstax.org/details/books/microbiology>

**License for all of the above:**
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) · © 2026 Rice University.

**Changes made.** Textbook content was used as source material for writing original
examination-preparation questions, answer explanations, and short key-term definitions. Text
is paraphrased and restructured for exam preparation; no chapter is reproduced verbatim, and
no OpenStax assessment item, end-of-chapter question, or answer key is reproduced. Where a
definition is close to the source wording, it is attributed to the title above.

### On editions

The editions used here are the **2026 OpenStax releases, which carry the NonCommercial
license**. Earlier editions of several of these titles were published under **CC BY 4.0**
(attribution only, no NonCommercial restriction), and a Creative Commons grant is
irrevocable — so a project that harvested an *earlier* printing of the same title could
lawfully treat that material differently. This project used the 2026 editions and is
therefore bound by the NonCommercial term. **Do not assume a title's license from its name:
re-read the copyright page of the exact edition in hand before reusing it.**

---

## Fonts — self-hosted, both SIL Open Font License 1.1

The app ships its own copies of the two type families it uses. Nothing is loaded from a
third-party font service, so no visitor's IP address leaves this site to render a page.
Both families are open-source fonts, redistributed here under the same license they carry
upstream, unmodified except for subsetting to the Latin and Latin Extended ranges.

| Family | Used for | Copyright | License | Upstream |
|---|---|---|---|---|
| **Libre Baskerville** | headings, display | © 2012 Pablo Impallari, Rodrigo Fuenzalida | SIL OFL 1.1 | <https://github.com/impallari/Libre-Baskerville> |
| **Source Sans 3** | body text, UI | © Adobe | SIL OFL 1.1 | <https://github.com/adobe-fonts/source-sans> |

Files: `static/fonts/*.woff2` (six files: Latin and Latin Extended, roman and italic for
Libre Baskerville, roman for Source Sans 3). Declarations: `static/css/fonts.css`.

The OFL permits use, study, modification and redistribution, including bundled with
software, provided the font software is not sold on its own and no modified version uses a
Reserved Font Name. Subsetting for web delivery is a permitted modification; these files
keep their upstream names and are not sold. Full text: <https://scripts.sil.org/OFL>.

---

## Exam names and testing companies

**TEAS** is a registered trademark of **Assessment Technologies Institute, LLC (ATI)**.
**HESI A2** is a registered trademark of **Elsevier Inc.** This project is **not affiliated
with, endorsed by, or sponsored by** ATI or Elsevier, and it reproduces no ATI or Elsevier
material. All practice questions, answer keys, and explanations here are original work by
Mu2 Solutions, LLC, written to the publicly published content outlines for those exams.

## Mu2 Solutions original content

All 2,506 practice questions, answer keys, per-distractor explanations, Study Coach logic,
and misconception library are **written by Mu2 Solutions, LLC** and are licensed
**CC BY-NC-SA 4.0** (see [`LICENSE-CONTENT`](LICENSE-CONTENT)).

## Everything else

Fonts, icons, and any other third-party assets remain the property of their respective owners
and are governed by their own licenses.

---

## Reporting a problem

If you believe material here is misattributed or used outside its license, please open an
issue and it will be corrected promptly.
