# SPASE Author Finder — Candidate List

**Record:** spase://ESA/NumericalData/PROBA2/LYRA/Flarelist/PT24H
**Date:** 2026-06-18

| Candidate | Evidence (source) | Confidence | Person Record | ORCID | Affiliation | Active Period |
|---|---|---|---|---|---|---|
| Marie Dominique | Record Contacts (GeneralContact); LYRA Instrument record names her **Principal Investigator**; lead author of the LYRA description paper (Dominique et al. 2013) | Strong | spase://SMWG/Person/Marie.Dominique | — | Royal Observatory of Belgium | Current PI (2022 revision set her as General Contact) |
| Ingolf E. Dammasch ("IED") | Provider Flarelist page credits compiler "IED"; "IED's Homepage" (sidc.be/users/dammasch) hosts the LYRA Flare List; co-author #4 of the LYRA description paper (Dominique et al. 2013). The product compiler/maintainer, distinct from the instrument PI. | Strong | No (checked Ingolf.E.Dammasch, Ingolf.Dammasch, I.E.Dammasch — all 404) | — | SIDC, Royal Observatory of Belgium | Compiler/maintainer of the flare list (page dated through 2026) |
| Jean-François Hochedez | Co-author #2 of the LYRA description paper (Dominique et al. 2013); original LYRA instrument lead/PI in early mission | Medium | No (Jean-Francois.Hochedez 404) | — | (not surfaced; ROB/LATMOS) | Early LYRA instrument lead |
| Lee Frost Bargatze | Record Contacts (MetadataContact); named in RevisionHistory ("reviewed by LFB") | Low (metadata curator, not data author) | spase://SMWG/Person/Lee.Frost.Bargatze | — | Dept. of Earth, Planetary, and Space Sciences, UCLA (lfb@igpp.ucla.edu) | Metadata contact; 2022 revision |

## Considered and excluded
- **Werner Schmutz, A. I. Shapiro, M. Kretzschmar, A. N. Zhukov, D. Gillotay, Y. Stockman, A. BenMoussa** — remaining co-authors (#3, #5–#10) of the LYRA description paper. The long tail of description-paper co-authors is background, not candidates, unless corroborated by another source for *this data product*. None appeared on the Flarelist/provider pages, the record Contacts, or the Instrument record. Excluded as background.
- **Melanie Heil (melanie.heil@esa.int)** — named in RevisionHistory only as the person who *submitted* the 2022 metadata ("Metadata submitted by melanie.heil@esa.int"). Metadata-submitter, not a data author. No SMWG Person record (404).
- **swap-lyra@lists.observatory.be** — mailing-list address found on the PROBA2 contact page; excluded (mailing-list addresses are not candidates).
- **Institutional credits** — ESA, Royal Observatory of Belgium / SIDC, Centre Spatial de Liège, PMOD, Belspo, STCE, AFFECTS (from the PROBA2 acknowledgements page); NOAA SWPC / GOES (upstream event source). Institutional thank-yous, not people.

## Notes
- **Strongest signal beyond the existing Contacts:** the provider's Flarelist page credits compiler **"IED"**, which resolves to **Ingolf E. Dammasch** (SIDC/ROB) — confirmed via his SIDC homepage hosting the LYRA Flare List and his co-authorship on the LYRA description paper. He is the product's compiler/maintainer and is *not* currently in the record's Contacts, so he is the most important addition for a human reviewer to consider.
- **Derived-product provenance:** the flare list is not a raw instrument product — it cross-references LYRA observations against NOAA SWPC "Edited Events" GOES/G16 X-ray classifications. This introduces NOAA SWPC as an upstream data source (institutional, recorded above), not an individual contributor.
- **PI history:** Dominique is the current PI; Hochedez was an early LYRA lead/PI. The "Active Period" distinction is recorded for the downstream role agent (e.g. PI vs FormerPI); it was not used to include/exclude anyone.
- **No PublicationInfo** exists on the record. The Crossref entry for the description paper (DOI 10.1007/s11207-013-0252-5) returned author names but no affiliations or ORCIDs, so ORCID/affiliation columns are mostly blank (opportunistic-only).
- **Naming-convention caution for downstream:** no SMWG Person record currently exists for Dammasch under three tried slugs; a new record will likely be needed, and the canonical slug should be confirmed (full middle initial "E").

## Sources
- [SPASE record (HTML)](https://spase-metadata.org/ESA/NumericalData/PROBA2/LYRA/Flarelist/PT24H)
- [LYRA Instrument SPASE record](https://spase-metadata.org/SMWG/Instrument/PROBA2/LYRA.html)
- [PROBA2 LYRA Flarelist page](https://proba2.sidc.be/lyra/data/Flarelist/Flarelist.html)
- [Dominique et al. 2013, LYRA description paper (ADS)](https://ui.adsabs.harvard.edu/abs/2013SoPh..286...21D/abstract)
- [Crossref: 10.1007/s11207-013-0252-5](https://api.crossref.org/works/10.1007/s11207-013-0252-5)
- [IED's Homepage (Dammasch / SIDC)](https://www.sidc.be/users/dammasch/)
