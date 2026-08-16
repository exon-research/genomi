"""Verbatim `paperclip search` stdout captures, one per source family.

Paperclip has no JSON search mode, so this display grammar is the only
shape the parser ever sees. Each constant is the unmodified stdout of the
command named above it, captured from gxl-paperclip 0.7.36.
"""

from __future__ import annotations

# paperclip search -s pmc,abstracts "CTLA4 checkpoint blockade" -n 2
PMC_ABSTRACTS_DISPLAY = 'Found 2 papers  [s_6b726a6f]\n\n  1. Antibody-mediated neutralization of soluble MIC significantly enhances CTLA4 blockade therapy\n     Jingyu Zhang, Dai Liu, Guangfu Li, Kevin F. Staveley-O’Carroll, Julie N. Graff, Zihai Li, Jennifer D...\n     PMC5435412 · Science Advances · 2017-05-01\n     https://doi.org/10.1126/sciadv.1602133\n     "This study investigated the combined therapeutic effect of anti-CTLA4 and anti-sMIC antibodies. Soluble MIC neutralization significantly enhances CTLA4 blockade therapy."\n\n  2. CTLA-4 based therapy (MDX-010)\n     A Korman\n     PMC3300183 · Breast Cancer Research : BCR · 2003-01-01\n     https://doi.org/10.1186/bcr731\n\n[307ms, saved to s_6b726a6f]\n[307ms, saved to s_6b726a6f]\n\n'

# paperclip search -s fda "ipilimumab CTLA-4" -n 2
FDA_DISPLAY = 'Found 2 documents  [s_4561f9c3]\n\n  1. Yervoy\n     fda_0100f40f7361\n     BLA125377 · TOC Review · § Study title: Biophysical characterization of protein reagents used in MDX-010 SPR experiments\n     Bristol-Myers Squibb submitted an original biologics licensing application for Yervoy (ipilimumab), a fully human monoclonal antibody that blocks CTLA-4 to enhance T-cell activation against tumor antigens. The FDA conducted a comprehensive pharmacology and toxicology review of nonclinical studies, which utilized tumor-bearing transgenic mice and cynomolgus monkeys to evaluate safety and efficacy. While the drug demonstrated anti-tumor activity, an ongoing developmental toxicity study in monkeys revealed increased incidences of abortion, stillbirth, and infant mortality, leading to a Pregnancy Category C designation. The FDA concluded that the nonclinical data supported the approval of Yervoy for the treatment of unresectable or metastatic melanoma, while requiring a post-marketing study to finalize developmental toxicity assessments.\n\n  2. Yervoy\n     fda_6b679bd504e9\n     BLA125377 · TOC Review · § Market approval status\n     Bristol Myers Squibb submitted a Biologics License Application for ipilimumab, a monoclonal antibody targeting CTLA-4, for the treatment of advanced melanoma. The Office of Clinical Pharmacology evaluated the proposed 3 mg/kg dosing regimen, confirming it was supported by a statistically significant overall survival benefit observed in the registration trial. Pharmacometric analyses demonstrated a positive exposure-response relationship for efficacy, though higher exposures were also associated with an increased incidence of immune-related adverse events. The FDA approved the application, while requiring post-marketing studies to develop more sensitive assays for anti-drug antibodies and to further investigate the genetic determinants of immune-related adverse reactions.\n\n[234ms, saved to s_4561f9c3]\n[234ms, saved to s_4561f9c3]\n\n'

# paperclip search -s trials/jp "melanoma" -n 2
TRIALS_JP_DISPLAY = 'Found 2 documents  [s_974f9f85]\n\n  1. UMIN000028085\n     tri_316b07644307\n     UMIN000028085 · umin_registry · § primary_outcomes\n     "Malignant melanoma Patients with malignant melanoma None Disease specific survival"\n\n  2. UMIN000004073\n     tri_6e3c56bf266b\n     UMIN000004073 · umin_registry · § primary_outcomes\n     "malignant melanoma advanced melanoma none overall survaival"\n\n[1.4s, saved to s_974f9f85]\n[1.4s, saved to s_974f9f85]\n\n'

# paperclip search -s proteins "CTLA4" -n 2
PROTEINS_DISPLAY = 'Found 2 proteins  [s_1818459d]\n\n  1. CTLA4 - Cytotoxic T-lymphocyte protein 4\n     P16410\n     Homo sapiens · 223 aa\n\n  2. CTLA4 - Cytotoxic T-lymphocyte protein 4\n     P42072\n     Oryctolagus cuniculus · 223 aa\n\n[20ms, saved to s_1818459d]\n[20ms, saved to s_1818459d]\n\n'


__all__ = [
    "PMC_ABSTRACTS_DISPLAY",
    "FDA_DISPLAY",
    "TRIALS_JP_DISPLAY",
    "PROTEINS_DISPLAY",
]
