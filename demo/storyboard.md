# Intake public walkthrough storyboard

This storyboard defines the reproducible 75 to 90 second walkthrough used for the first public release.

## Audience and promise

- Audience: international engineering leads and small software teams.
- Promise: show one raw customer request becoming accepted, traceable work.
- Principle: AI proposes; a person makes every consequential decision.
- Delivery target: a real Issue in `ZiniSoft/intake-demo`.

## Synthetic fixture

| Field | Demo value |
| --- | --- |
| Project | Nova |
| Project code | `nova` |
| Intake key | `NVA` |
| Engineering lead | Alex Morgan |
| Developer | Maya Chen |
| Source | Customer support chat |
| Raw request | Customers cannot export the monthly report. The export times out after about 30 seconds. |
| Normalized title | Monthly report export times out |
| Type | Bug |
| Priority | P1 |
| Delivery system | GitHub |
| Repository | `ZiniSoft/intake-demo` |
| Plan | Maya Chen, morning, 3 hours |

Every email address uses `example.test`. No real customer, employee, host, token, project, or provider name may appear in the recording.

## Shot list

| Time | Screen and action | Narration focus | Required evidence |
| --- | --- | --- | --- |
| 00:00 to 00:07 | Open Create Intake with the raw support message ready to paste. | Requests arrive before they are clean tickets. | English UI, fictional project, no browser bookmarks or notifications. |
| 00:07 to 00:18 | Select Nova, paste the request, and create the Intake. | Capture the original request and connect it to a project. | Raw text stays visible long enough to read. |
| 00:18 to 00:32 | Open the normalized result and highlight title, summary, type, priority, and open questions. | AI organizes the request but does not decide. | The original and normalized versions are visibly separate. |
| 00:32 to 00:45 | Review P1 and GitHub, then approve and sync. | A person chooses priority and destination. | Confirmation step and audit language are visible. |
| 00:45 to 00:55 | Show sync success and open the real GitHub Issue in `ZiniSoft/intake-demo`. | Intake creates traceable delivery work. | Issue title and body match the approved snapshot. No token or settings page is shown. |
| 00:55 to 01:10 | Return to Daily Planning, assign Maya Chen for the morning, set 3 hours, and approve the plan. | Plan the work against ownership and capacity. | Assignee, slot, hours, and source Issue are visible. |
| 01:10 to 01:22 | Open the Intake journey and move attention across completed steps. | The request, decision, Issue, and plan stay connected. | Capture, approval, Issue, planning, and acceptance states are readable. |
| 01:22 to 01:30 | End card with repository URL and product principles. | Self-hosted, human-in-the-loop, GitHub and GitLab ready. | `github.com/ZiniSoft/intake` and Apache-2.0 are visible. |

## Recording rules

1. Rehearse with a local mock. Use the real GitHub integration only for the final take.
2. Record at 1920 by 1080, 30 FPS, with the browser at 100 percent zoom.
3. Hide bookmarks, extensions, operating-system notifications, and the desktop taskbar.
4. Never open Settings, environment files, developer tools, network panels, or credential dialogs.
5. Keep the pointer motion slow and intentional. Avoid typing secrets on camera.
6. Record the clean browser track first. Add narration, captions, zooms, and callouts in post-production.
7. Review every frame at normal speed and at 0.25 speed before publishing.
8. Upload the final H.264 MP4 to a GitHub Release and YouTube. Do not commit the MP4 to Git history.

## Acceptance checklist

- The video creates at most one real demo Issue.
- All visible data matches the synthetic fixture.
- English narration and captions match the final UI actions.
- No private identifier or credential appears in pixels, metadata, subtitles, or filenames.
- The final Issue remains useful as a public example after both repositories are published.
