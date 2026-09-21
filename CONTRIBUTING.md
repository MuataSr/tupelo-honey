# Contributing to Tupelo Honey

Thank you for wanting to help. Tupelo Honey is a free, open study aid for the
ATI TEAS and HESI A2 nursing admission exams, and it gets better when people
contribute. There is no Discord to join and no gatekeeper to impress —
everything happens here, in the issue tracker and in pull requests, on your
schedule.

## The two things this project always needs

1. **Better content.** The question bank and the explanations are the heart of
   Tupelo Honey. If you spot a question with a wrong fact, a key that doesn't
   match its explanation, a distractor that isn't really wrong, or a topic
   that's under-covered, that's the most valuable report you can make. Nursing
   faculty and students who have actually sat the TEAS or HESI are especially
   welcome.
2. **Bug reports.** Something broken on the site? Open an issue with what you
   did, what you expected, and what happened. A screenshot or the
   browser/device helps.

## Reporting a content error

Open an issue and include:

- The question text (or the question ID, shown in the app)
- What you believe is wrong — the key, an option, or the explanation
- Your reasoning, and a source if the claim is factual

Content corrections are the highest-value contribution here. A bank is only as
good as its answer key.

## Reporting a bug

Open an issue and include:

- What you were doing
- What you expected
- What actually happened
- Browser and device, if relevant

## Contributing code

1. Fork the repository and create a branch.
2. Make your change. Keep it small and focused — one fix or feature per pull
   request is much easier to review than five.
3. Run the test suite before you open the PR:

   ```bash
   python3 -m unittest discover -s tests -t .
   ```

4. Open the pull request and describe *what* you changed and *why*.

There are no style gatekeepers, but please match the surrounding code and keep
changes readable. If a change touches behavior, add or update a test.

## Contributing content

Questions and explanations are data in `data/tupelo.db`. If you're adding or
correcting content, open an issue first describing the change and the source
you're drawing on — factual claims need a source. Pull requests that add
content should note the source in the PR description so it can go into
`ATTRIBUTION.md`.

**Never reference an option by its letter in an explanation.** Write the
rationale from the content of the option ("dividing by the original value",
"the passive construction"), because options are shuffled at serve time and a
letter reference silently breaks. This is enforced by a checker in CI.

## Licensing your contribution

By contributing you agree to license:

- **code** under [Apache-2.0](LICENSE), and
- **content** under [CC BY-NC-SA 4.0](LICENSE-CONTENT).

That keeps Tupelo Honey free and open, now and for everyone who forks it.

## Ground rules

- Be kind. This is an educational resource for students, not a battleground.
- No unsolicited "AI can fix everything" rewrites of the Study Coach. The coach
  is deliberately deterministic — that is a design decision, not a gap. See the
  README.
- The maintainer reviews on his own schedule. A slow response isn't a rejection.

Thank you.
