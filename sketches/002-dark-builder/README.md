## Variant: Dark Builder

### Design stance
A Monitor surface styled on the Linear system: near-black canvas, one indigo accent, translucent white borders. Signals "data engineer / modern data stack" — the current convention for dev and ML portfolio sites.

### Key choices
- **Surface:** Monitor — same compact identity header strip, no hero; density via luminance steps rather than boxes.
- **Typography:** Inter with `cv01`,`ss03` OpenType features (Linear's signature geometric Inter), JetBrains Mono for labels.
- **Color:** `#08090a` base, `#f7f8f8` text (never pure white), single indigo accent `#5e6ad2`/`#7170ff`; green reserved for status only.
- **Layout:** Sticky panel nav → header strip → 4-stat strip → 2-col chart grid → pipeline strip.
- **Interaction:** Same date-range segmented toggle, re-rendering the line.

### Trade-offs
- **Strong at:** Technical identity — instantly reads "builder," and the sparse accent feels engineered.
- **Weak at:** Less universally trusted by non-technical business audiences, who may read dark + mono as "developer tool" rather than "analytics product."

### Best for
Data-team leads and technical stakeholders; also the natural aesthetic for a personal-site *shell* wrapping the light dashboard.