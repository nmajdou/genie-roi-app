### How the KPIs are calculated

Databricks recommends measuring AI/BI Genie and Genie Code along three axes: **adoption**, **engagement** and
**user satisfaction** ([Measure Genie Code impact](https://docs.databricks.com/aws/en/genie-code/impact)).
System tables cover the first two plus in-product feedback; satisfaction and time saved should be backed by a
short internal survey.

| KPI | Definition | Source |
|---|---|---|
| Genie Code interactions | User-submitted chat, agent-mode and inline-assistant requests | `system.access.assistant_events` |
| Genie Code active users (DAU / MAU) | Distinct `initiated_by` per day / month | `system.access.assistant_events` |
| New vs returning users | First month seen vs also active the previous month | both |
| Genie questions | `createConversationMessage`, `createAgenticResponse` and their API equivalents | `system.access.audit` (`aibiGenie`) |
| Genie conversations, active users, active spaces | Distinct conversation / user / space ids on question events | `system.access.audit` |
| Positive feedback rate | Thumbs up / (up + down), from `updateConversationMessageFeedback` | `system.access.audit` |
| Regeneration rate, failed questions | `regenerateConversationMessage`; question events with a non-200 status | `system.access.audit` |
| Curation effort | Instruction, sample/benchmark question and benchmark-run events | `system.access.audit` |
| Genie SQL success rate, latency, data read | Queries with `query_source.genie_space_id` set | `system.query.history` |
| Genie compute cost (estimate) | Genie share of execution time × warehouse list cost | `system.query.history`, `system.billing.usage`, `system.billing.list_prices` |

### Value model

* **Genie Code**: interactions × minutes saved per interaction.
* **Genie spaces, business users**: answered questions × minutes saved per question (time not spent waiting
  for or building a report).
* **Genie spaces, analyst deflection**: answered questions × share that would otherwise be an analyst request ×
  analyst minutes per request.
* **Answered questions** = questions − failed − thumbs down (conservative).
* **ROI** = (value − cost) / cost.

All minute and cost figures are **assumptions** set in the sidebar. Calibrate them with a time study or the
survey below before presenting results.

### Limitations

* `assistant_events` counts from before 7 May 2026 include background requests (autocomplete, quick fixes) and
  are inflated.
* Compute cost uses **list prices** and attributes shared warehouse cost by execution time; it is an estimate.
* Genie Code usage cost is not included.
* Feedback rating values are matched loosely; check *Debug: raw feedback rating values* on the Genie spaces tab.
* Space names are only resolved for spaces in the app's own workspace that the app's service principal can see.
* System table data typically lands within an hour.

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
