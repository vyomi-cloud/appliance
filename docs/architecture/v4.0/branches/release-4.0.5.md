# v4/release-4.0.5

**Why:** ship the simulator fixes found by the vyomi-endurance mission (branches v4/endurance-aws-serverless, -aws-observability, -gcp, -proof) and the Nano/Mesh UI work already on trunk.

**Changes:** merges of those four branches (estate Terraform conflicts resolved by keeping every module and output), a fix for a regression the proof branch's F501 caused in the bedrock-agent suites (knowledge-base lists are real POSTs; the GET rewrite is now a fallback), VERSION 4.0.5, CHANGELOG, notes.

**Not included:** v4/endurance-azure (still running at merge time).

**Open:** full AWS stage 1-8 gate needs >=10 GB free disk for the instance; trunk-wide failures predating this release are listed in CHANGELOG known limits.
