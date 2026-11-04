### How the KPIs are calculated

Databricks recommends measuring AI/BI Genie and Genie Code along three axes: **adoption**, **engagement** and
**user satisfaction** ([Measure Genie Code impact](https://docs.databricks.com/aws/en/genie-code/impact)).
System tables cover the first two plus in-product feedback; satisfaction and time saved should be backed by a
short internal survey.

| KPI | Definition | Source |
|---|---|---|
| Genie Code interactions | User-submitted chat, agent-mode and inline-assistant requests | `system.access.assistant_events` |
| Genie Code active users (DAU / MAU), active user-days | Distinct `initiated_by` per day / month; distinct (user, day) pairs | `system.access.assistant_events` |
| New vs returning users | First month seen vs also active the previous month | both |
| Genie questions | Successful (HTTP 200) `createConversationMessage`, `createAgenticResponse` and their API equivalents | `system.access.audit` (`aibiGenie`) |
| Genie conversations, active users, active spaces | Distinct conversation / user / space ids on question events | `system.access.audit` |
| Positive feedback rate | Thumbs up / (up + down), from `updateConversationMessageFeedback` | `system.access.audit` |
| Regeneration rate, failed attempts | `regenerateConversationMessage`; message events with a non-200 status | `system.access.audit` |
| Curation effort | Instruction, sample/benchmark question and benchmark-run events | `system.access.audit` |
| Genie SQL success rate, average duration, slow-query rate (> 10 s), data read | Queries with `query_source.genie_space_id` set | `system.query.history` |
| Genie compute cost (estimate) | Genie share of execution time × warehouse list cost | `system.query.history`, `system.billing.usage`, `system.billing.list_prices` |

### Value model

* **Genie Code**: active user-days × minutes saved per day of use. Interaction counts are not used for value:
  agent mode and scripted clients can log thousands of events per user per day.
* **Genie spaces, business users**: answered questions × minutes saved per question (time not spent waiting
  for or building a report).
* **Genie spaces, analyst deflection**: answered questions × share that would otherwise be an analyst request ×
  analyst minutes per request.
* **Answered questions** = successful questions − thumbs down (conservative).
* **ROI** = (value − cost) / cost.

All minute and cost figures are **assumptions** set in the sidebar. Calibrate them with a time study or the
survey below before presenting results.

### Limitations

* `assistant_events` counts from before 7 May 2026 include background requests (autocomplete, quick fixes) and
  are inflated.
* Compute cost uses **list prices** and attributes shared warehouse cost by execution time; it is an estimate.
* Genie Code usage cost is not included.
* *Human users only* keeps identities with an email address; it excludes service principals, but not scripts
  running under a user's identity. Check the top-users tables for outliers.
* Few users give thumbs up/down, so the positive feedback rate is based on a small sample.
* Space names are only resolved for spaces in the app's own workspace that the app's service principal can see.
* Data is as of the last refresh job run (daily); system table data itself lands within about an hour.
* Conversations are counted per day, so one spanning several days is counted once per day.

### Survey

The survey app (`survey/` in the repository) asks the questions below and saves anonymous answers. When it is
set up, the averages become the default assumptions in the sidebar. The hourly cost is never taken from the
survey: get it from Finance.

| Question | Feeds |
|---|---|
| Genie Code: on a day you use it, how much time does it save you? | Minutes saved per active user-day |
| Genie Code: hours of coding per week, and share of that time saved | Survey-based estimate |
| Genie: questions asked to get one answer | Divides the time saved and the analyst share per question |
| Genie: time to get an answer with Genie, and before Genie | Business-user minutes saved |
| Genie: would you still have looked for these answers without Genie? | Answers not looked for before count for zero |
| Genie: how often would you have asked an analyst? | % of questions that would otherwise be an analyst request |
| Genie: how much analyst time did a request take? | Analyst minutes per request |

Role, frequency, satisfaction, trust and comments describe adoption and do not change the ROI.
