## Variant: Light Premium BI

### Design stance
A Monitor surface styled on the Vercel system: white canvas, shadow-as-border, restrained achromatic chrome. Signals "I ship production-grade analytics," not "I am a developer portfolio."

### Key choices
- **Surface:** Monitor — compact identity *header strip*, not a marketing hero; the chart grid carries the page.
- **Typography:** Geist (Google Fonts), negative letter-spacing at headings, three weights (400/500/600).
- **Color:** Achromatic `#171717`→`#ffffff`; chart color enters only in series (blue/purple/pink from Vercel's console palette).
- **Layout:** Sticky nav → header strip (eyebrow + headline + health line) → 4-stat strip → 2-col chart grid → pipeline strip.
- **Interaction:** Date-range segmented toggle (`7d/90d/1y/5y`) re-renders the line chart.

### Trade-offs
- **Strong at:** Trust and "production polish" — reads closest to a real BI tool a client already knows.
- **Weak at:** Technical "builder" cred — does not telegraph data-engineering identity as loudly as a dark, mono-accented look.

### Best for
Business stakeholders who evaluate freelancers by "does this look like the dashboards my team already uses."