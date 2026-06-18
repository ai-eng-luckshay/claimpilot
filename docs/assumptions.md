# ClaimPilot — Assumptions

This document lists every assumption we made while building the system. Each one
is a decision we had to take without full information. If any of these assumptions
turn out to be wrong, we have noted what would need to change.

---

## 1. How Documents Reach Us

### A1 — Someone else is collecting the documents from the member
We assumed that a separate system — a member portal or mobile app — is responsible
for asking the employee to upload their documents and fill in their claim details.
ClaimPilot only handles what happens *after* that step: it receives the documents
and decides whether to approve, partially approve, or reject the claim.

**If this is wrong:** We would need to build our own submission interface where
members can log in, fill in their claim details, and upload files directly.

---

### A2 — All documents for one claim arrive together in a single submission
We assumed that when a member submits a claim, they upload everything at once —
the prescription, the hospital bill, the lab report — all in one go. There is no
"submit now, add more documents later" flow.

**If this is wrong:** Members would need the ability to attach additional documents
to an already-submitted claim, and the system would need to re-evaluate the claim
after each addition.

---

### A3 — The system only needs to handle photos, scanned PDFs, and digital PDFs
We assumed documents will arrive in one of three formats: a photo taken on a phone
(JPEG/PNG), a scanned PDF (a photo embedded inside a PDF), or a digitally created
PDF (like a document typed and saved on a computer). The system handles all three.

**If this is wrong:** Other formats — such as Word documents or HEIC photos from
iPhones — would need to be added to the supported list before the system can read them.

---

### A4 — The member's claims history is provided to us by the upstream system
To check whether a member is approaching their annual limit, we need to know what
they have already claimed this year. We assumed that the system sending us the
claim will also send this history along with it.

**If this is wrong:** We would need to look up the member's past claims from our
own database instead. The groundwork for this is already built — it just needs
to be switched on.

---

## 2. How We Store Data

### B1 — Once a claim decision is made, it is final and cannot be changed
We assumed that a claim decision — once written — is permanent. There is no
"re-open and re-decide" flow in the system today.

**If this is wrong:** We would need to build a correction or appeals workflow
where an operations team member can override or re-trigger the decision on an
existing claim.

---

### B2 — The member database is not managed by us
We do not maintain a database of members. The member roster — who is covered under
the policy, what their relationship to the primary member is, when they joined —
comes from the policy file. We trust whatever is in that file.

**If this is wrong:** We would need to connect to an external member management
system or build our own, and validate member details at submission time against
that system rather than the policy file.

---

### B3 — Documents are stored on the same server that runs the system
Uploaded documents are saved to a folder on the same machine that processes claims.
This works fine for a demo or small scale, but is not suitable for a production
system handling thousands of claims.

**If this is wrong (or when we scale):** Documents would be moved to a cloud
storage service so they are durable, globally accessible, and not lost if the
server is replaced.

---

## 3. How Policy Rules Are Applied

### C1 — There is one policy that covers all members
We assumed a single set of coverage rules applies to every member — the same
limits, the same exclusions, the same co-pay percentages. Everyone is on the
same plan.

**If this is wrong:** Different companies (or different plan tiers within a company)
have different rules. The system would need to look up the right policy for each
claim before evaluating it.

---

### C2 — Policy terms do not change while the system is running
We assumed the policy file is stable. If Plum updates the coverage rules or adds
a new exclusion, the system needs to be restarted to pick up those changes.

**If this is wrong:** The system would need to be able to refresh its policy rules
automatically — for example, checking for updates every few minutes — without
needing a restart.

---

### C3 — Hospital name matching does not need to be exact
When checking whether a treatment happened at a network hospital, we match on
partial names. "Apollo" will match "Apollo Hospitals Ltd" even if the names
are not identical. We assumed this is good enough because names typed by members
or extracted from documents are rarely perfectly consistent.

**If this is wrong:** A verified hospital registry would be needed so that matching
is based on a unique hospital ID rather than a name string.

---

## Summary

| Area | Assumption | Risk if Wrong |
|---|---|---|
| Document collection | A separate system sends us documents | We need to build our own submission UI |
| Document collection | All documents arrive in one submission | We need a "add documents later" flow |
| Document collection | Photos, scanned PDFs, and digital PDFs only | Other file formats would be rejected |
| Document collection | Claims history is sent by the caller | We query our own database instead (already prepared) |
| Data storage | Claim decisions are final | We need an appeals / correction workflow |
| Data storage | Member roster comes from the policy file | We need a separate member management system |
| Data storage | Files saved on the same server | Cloud storage needed for production scale |
| Policy | One policy covers everyone | Per-company or per-plan policy lookup needed |
| Policy | Policy rules are stable during runtime | Automatic policy refresh needed |
| Policy | Fuzzy hospital name matching is sufficient | A verified hospital registry with unique IDs needed |
