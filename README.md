# Thriving Culture — Website

A fast, branded marketing site for **Thriving Culture, LLC**. Elegant, polished
motion; built with plain HTML/CSS/JS so it loads instantly and deploys anywhere
with **no build step**.

The design system is pulled straight from the logo — the green → teal → blue
faceted gem — and the content is built around the real four values:
**Authenticity, Courage, Community, Sustainability.**

## What's here

```
index.html          The full one-page site
css/style.css       Brand system + all styling
js/main.js          Motion: scroll reveals, count-ups, cursor-reactive hero
assets/             Logo + favicon
blog/               (reserved for future article pages)
```

## Run it locally

No tooling required — just open `index.html`, or serve it:

```bash
# any static server works
python3 -m http.server 8000
# then visit http://localhost:8000
```

## Deploy it (pick one)

All three connect directly to this GitHub repo and auto-publish on every push.

- **GitHub Pages** — Settings → Pages → Deploy from branch → `main` / root. Free, done.
- **Netlify** — "Add new site" → import this repo. No build command; publish dir `/`.
- **Vercel** — "New Project" → import this repo → framework preset "Other".

To use a custom domain (e.g. `thrivingculturellc.com`), add it in your host's
domain settings and point your DNS there.

## Things to make it yours

- **Newsletter form** (`js/main.js`) currently shows a success state on the
  front end only. Wire the `TODO` line to Mailchimp, ConvertKit, or your backend
  to actually capture emails.
- **Booking link** — the "Book a call" buttons open an email. Swap in your
  Calendly / booking URL if you'd rather.
- **Stats & testimonials** — the numbers in the hero, stats band, and approach
  badges are illustrative placeholders. Replace with your real figures.
- **Insights** — three sample article cards link to `#`. Point them at real
  posts (add pages under `blog/`) when you're ready.

## Sections

Hero · Trust strip · Services · Values (dark) · Approach · Stats · Insights ·
Newsletter · Contact · Footer
