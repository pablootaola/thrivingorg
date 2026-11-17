---
name: rfp-lifecycle
description: Run one pass of the Thriving Culture RFP lifecycle (source, stage, acquire, screen, price, write, gate, hand off) using the rfp-agent and its sub-agents. Use for "run the RFP agent", "nightly RFP run", "sweep for RFPs", "acquire documents for <bid>", "build the proposal for <bid>".
---

# RFP lifecycle

1. Invoke the `rfp-agent` sub-agent with the run mode: `sweep` (source plus stage), `acquire <bid>`, `screen <bid>`, `build <bid>`, or `nightly` (sweep, acquire every new in-scope row, screen, then advance the two highest-value live builds).
2. The agent boots from Abuelo every time (see `.claude/agents/rfp-agent.md` section 0). Do not skip the boot to save time.
3. Engine quick reference (`rfp-agent/`):
   - `python -m rfp_engine sweep --master master_keys.csv --out runs/<date>`
   - `python -m rfp_engine merge --master master.csv --staging staging.csv --out append.tsv` (the Nightly merge's planner; refuses the 00:30 to 01:30 Madrid window)
   - `python -m rfp_engine acquire-sam <noticeId> --dest <folder> ...`
   - `python -m rfp_engine bidnet-email body.txt`
   - `node proposal/build_pdf.js in.html out.pdf --faces faces.json`
   - `python -m pytest -q` before trusting any change to the engine.
4. Finish with the hand-off in the agent file section 3 and the Abuelo status lines.
