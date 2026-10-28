---
name: job-map-weekly-refresh
description: Weekly refresh of Jonathan's job-targeting map with current hiring trends
---

You are refreshing Jonathan Ohayon's "Live Job Targeting Map" so it tracks the current US hiring market. Jonathan's profile: ex Senior Technical Delivery Analyst at Workday/HiredScore (AI B2B SaaS), MBA in Business Analytics (Hult, Boston, Aug 2026), strong in SQL/Python/Looker/Tableau/Power BI/Salesforce, cross-functional delivery, ex-IBM cybersecurity, IDF leadership. He is authorized to work in the US and does not need visa sponsorship. Target geographies: Boston (primary), NYC, Remote-US, Texas. Target role segments (priority order): 1) Business Analytics/BI, 2) Business/Revenue Operations, 3) Account Management/CSM/TAM, 4) GTM Strategy & Ops, 5) Strategy & Ops, 6) Product Marketing (skill gap: marketing experience/cert/portfolio), 7) Sales/AE (skill gap: quota-carrying experience).

Steps each run:
1. Use WebSearch to get the latest 2026 US hiring-trend data for each of the 7 segments (demand/growth %, whether heating or cooling). Note any notable shifts vs. prior week.
2. Check which target companies are actively hiring in the target geographies (public job boards and hiring news). Sponsorship is not a criterion.
3. Open the existing HTML file at /Users/jonathanohayon/Library/Application Support/Claude/local-agent-mode-sessions/3d42ee22-6a1e-4a24-a265-034fe9c1d36c/bcce3103-3689-46d9-9a1f-c37c09e83eb4/local_4e29cba1-ed84-49df-a48d-911113354276/outputs/job_map_live.html, update the DATA object in the <script> (trend labels, score values, company lists, and the refreshed date), keeping the structure intact. Re-rank tiers only if the market shifted meaningfully.
4. Update the artifact by calling create_artifact again with id "johnny-job-targeting-map" pointing at the updated HTML file.
5. Send Jonathan a 4-6 line summary: which segments got hotter/cooler this week, any target companies that started or stopped hiring, and one concrete action for the week. Use real data only — cite sources. Do not invent numbers.