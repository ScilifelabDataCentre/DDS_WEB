## Read this before submitting the PR

1. Always create a Draft PR first
2. Go through sections 1-5 below, fill them in and check all the boxes
3. Make sure that the branch is updated; if there's an "Update branch" button at the bottom of the PR, rebase or update branch.
4. When all boxes are checked, information is filled in, and the branch is updated: mark as Ready For Review and tag reviewers (top right)
5. Once there is a submitted review, implement the suggestions (if reasonable, otherwise discuss) and request an new review.

If there is a field which you are unsure about, enter the edit mode of this description or go to the [PR template](../.github/pull_request_template.md); There are invisible comments providing descriptions which may be of help.

## 1. Description / Summary

_Add a summary of the changes in this PR and the related issue._

## 2. Jira task / GitHub issue

_Link to the github issue or add the Jira task ID here._

## 3. Type of change

What _type of change(s)_ does the PR contain?

**Check the relevant boxes below. For an explanation of the different sections, enter edit mode of this PR description template.**

- [ ] New feature
  - [ ] Breaking: _Why / How? Add info here._ <!-- Should be checked if the changes in this PR will cause existing functionality to not work as expected. E.g. with the master branch of the `dds_cli` -->
  - [ ] Non-breaking <!-- Should be checked if the changes will not cause existing functionality to fail. "Non-breaking" is just an addition of a new feature. -->
- [ ] Database change: _Remember the to include a new migration version, **or** explain here why it's not needed._ <!-- Should be checked when you've changed something in `models.py`. For a guide on how to add the a new migration version, look at the "Database changes" section in the README.md. -->
- [ ] Bug fix <!-- Should be checked when a bug is fixed in existing functionality. If the bug fix also is a breaking change (see above), add info about that beside this check box. -->
- [ ] Security Alert fix <!-- Should be checked if the PR attempts to solve a security vulnerability, e.g. reported by the "Security" tab in the repo. -->
  - [ ] Package update <!-- Should be checked if the Security alert fix consists of updating a package / dependency version -->
    - [ ] Major version update <!-- Should be checked if the package / dependency version update is a major upgrade, e.g. 1.0.0 to 2.0.0 -->
- [ ] Documentation <!-- Should be checked if the PR adds or updates documentation such as e.g. Technical Overview or a architecture decision (dds_web/doc/architecture/decisions.) -->
- [ ] Workflow <!-- Should be checked if the PR includes a change in e.g. the github actions files (dds_web/.github/*) or another type of workflow change. Anything that alters our or the codes workflow. -->
- [ ] Tests **only** <!-- Should only be checked if the PR only contains tests, none of the other types of changes listed above. -->

## 4. Additional information

- [ ] [Sprintlog](../SPRINTLOG.md) <!-- Add a row at the bottom of the SPRINTLOG.md file (not needed if PR contains only tests). Follow the format of previous rows. If the PR is the first in a new sprint, add a new sprint header row (follow the format of previous sprints). -->
- [ ] Blocking PRs <!-- Should be checked if there are blocking PRs or other tasks that need to be merged prior to this. Add link to PR or Jira card if this is the case. -->
  - [ ] Merged <!-- Should be checked if the "Blocking PRs" box was checked AND all blocking PRs have been merged / fixed. -->
- [ ] PR to `master` branch: \_If checked, read [the release instructions](../doc/procedures/new_release.md) <!-- Check this if the PR is made to the `master` branch. Only the `dev` branch should be doing this. -->
  - [ ] I have followed steps 1-8. <!-- Should be checked if the "PR to `master` branch" box is checked AND the specified steps in the release instructions have been followed. -->

## 5. Actions / Scans

_Check the boxes when the specified checks have passed._

**For information on what the different checks do and how to fix it if they're failing, enter edit mode of this description or go to the [PR template](../.github/pull_request_template.md).**

- [ ] **Black**
<!--
  What: Python code formatter.
  How to fix: Run `black .` locally to execute formatting.
-->
- [ ] **Prettier**
<!--
  What: General code formatter. Our use case: MD and yaml mainly.
  How to fix: Run npx prettier --write . locally to execute formatting.
-->
- [ ] **Yamllint**
<!--
  What: Linting of yaml files.
  How to fix: Manually fix any errors locally.
-->
- [ ] **Tests**
<!--
  What: Pytest to verify that functionality works as expected.
  How to fix: Manually fix any errors locally. Follow the instructions in the "Run tests" section of the README.md to run the tests locally.
  Additional info: The PR should ALWAYS include new tests or fixed tests when there are code changes. When pytest action has finished, it will post a codecov report; Look at this report and verify the files you have changed are listed. "90% <100.00%> (+0.8%)" means "Tests cover 90% of the changed file, <100 % of this PR's code changes are tested>, and (the code changes and added tests increased the overall test coverage with 0.8%)
-->
- [ ] **CodeQL**
<!--
  What: Scan for security vulnerabilities, bugs, errors.
  How to fix: Go through the alerts and either manually fix, dismiss or ignore. Add info on ignored or dismissed alerts.
-->
- [ ] **Trivy**
<!--
  What: Security scanner.
  How to fix: Go through the alerts and either manually fix, dismiss or ignore. Add info on ignored or dismissed alerts.
-->
- [ ] **Snyk**
<!--
  What: Security scanner.
  How to fix: Go through the alerts and either manually fix, dismiss or ignore. Add info on ignored or dismissed alerts.
-->
