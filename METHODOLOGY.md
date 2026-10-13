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

### Recommended survey (Genie Code, adapted from the Databricks guide)

1. What is your role? (data engineer, data scientist, analyst, ...)
2. How often do you use Genie Code? (daily, weekly, monthly, rarely)
3. Where do you use it? (SQL editor, notebooks, both)
4. What do you use it for? (writing code, debugging, explaining code, documentation, ...)
5. How satisfied are you with Genie Code? (1-5)
6. How much has Genie Code improved your productivity? (1-5)
7. Roughly what share of your coding time does it save? (0%, 1-10%, 10-30%, 30-50%, 50-70%, 70%+)
8. Any other feedback?

Enter the average time-saved answer in the *Survey-based estimate* section of the Overview tab.
