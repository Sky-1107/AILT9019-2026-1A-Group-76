# GitHub Pages site

This folder is a standalone, static project site. It uses local HTML and CSS only; it
does not depend on a JavaScript bundle, an external font, or a CDN.

## Publish from this folder

1. Commit and push the `docs/` files to the repository's `main` branch.
2. In GitHub, open **Settings > Pages**.
3. Under **Build and deployment**, choose **Deploy from a branch**.
4. Select branch **main** and folder **/docs**, then save.
5. Wait for the Pages deployment to finish and use the URL shown in the Pages settings.

The site is not published merely by adding these files. Verify the deployed page on a
phone-sized viewport, test the section links and keyboard focus, and confirm the
repository links work after the files are pushed.

## Assessment scope

The site covers the project overview, target users, workflow, team-built application
work, domain customisation, setup, a genuine local mock-mode run, test evidence, a
refusal boundary, privacy, and limitations. It does not claim that a live provider
request, a classroom learning outcome, or a public deployment has been validated.

The presentation and demonstration videos are separate submission items. Publish the
actual videos and provide their YouTube URLs in the required submission links file;
this site intentionally does not invent or reserve video URLs.

## Video evidence checklist

The repository cannot produce the team recordings. Before submission, record and
review both videos against these checks:

### Presentation (3 minutes maximum)

- Explain the target user and planning problem, then the application's approach.
- Distinguish the team's application work from existing frameworks and model/provider
  components.
- Show how the teaching-domain customization is supported by a real example or test.
- State limitations and avoid claiming learning outcomes the project did not measure.
- Ensure every team member speaks and their name is visible while they speak.

### Application demonstration (continuous recording)

- Show the actual application from entering a brief through processing to the returned
  plan; do not cut away during that flow.
- Use mock mode for a repeatable, key-free success run. Show the editable plan and
  time calculator, then demonstrate a real safety refusal (for example, a grading
  request) or feasibility refusal (a 15-minute lesson with 10 objectives).
- Show the current test result from `python -m pytest -q`; explain that protocol tests
  use a local fake provider and do not prove live-provider quality or learning gains.
- Keep the screen readable, provide clear audio and narration, identify each speaker,
  and do not show API keys, student information, or other sensitive material.

Keep the videos separate, check that their YouTube links are accessible to the
assessors, and enter the actual URLs in the required submission links file. A checklist
or a site screenshot is not a substitute for the recordings.

## Update the example or evidence

The example in `index.html` is from an actual local `POST /api/generate` request with
`MOCK_MODE=1`. Keep it labelled as mock mode. If the example, test results, runtime
behavior, repository, or setup instructions change, verify the application and update
this page to match the code before publishing.
