# Vyomi Booster — Terms of Use (DRAFT for owner + legal review)

Status: draft, 2026-11-07. Not legal advice. Not yet on the portal. The portal already has `app/templates/terms.html`
and `privacy.html`; once approved, this becomes a "Booster" section of terms.html and a short summary on the
Launch dialog (user must tick "I agree" before the first launch).

## 1. What the Booster is
The Booster is a temporary compute environment that runs **in your own GitHub account** (a GitHub Codespace and,
optionally, a GitHub Actions runner that hosts the AI model). Vyomi starts and stops it for you through the
Vyomi Booster GitHub App. It runs heavy workloads for your Pro or Max plan: Docker VMs across the three clouds,
language runtimes, and the local AI model. The Nano console in your browser is the only interface.

## 2. Your account and your consent
1. You must own the GitHub account you connect, and you must be allowed to use Codespaces (and Actions) on it.
2. By connecting, you authorise Vyomi to create, start, stop and delete Codespaces (and, if you enable it,
   run the AI workflow) in that account, and nothing else. Vyomi has no access to your Codespaces secrets.
3. You can disconnect at any time (portal → Booster → Disconnect, or uninstall the App on GitHub). Vyomi then
   deletes its stored tokens and stops any running session.
4. GitHub's own terms, quotas and billing apply to your account. Vyomi does not pay for, refund or guarantee your
   GitHub usage. Booster hours count against your GitHub quota as well as your Vyomi allowance.

## 3. Time limits (the rules the system enforces)
| Limit | Value | What happens |
|---|---|---|
| Monthly allowance | Pro 40 h, Max 60 h of Booster time per billing cycle | New launches are refused when used up; a running session is stopped when it reaches the limit |
| Session length (hard cap) | 8 hours per launch (6 hours for a runner-hosted AI model; the runner stops at ~5 h 30 min) | The Booster is stopped and destroyed at the cap, with no extension beyond it |
| **Idle limit** | **60 minutes** | If nothing is deployed or running (see §4), the Booster is **stopped and destroyed automatically** |
| Lost connection | 5 minutes without a heartbeat | The session is ended |
| Start-up | 20 minutes to become ready | The launch is cancelled and the time is not charged to your allowance |

Time is counted from when the environment becomes ready until it is stopped, rounded up to the minute.

## 4. What "idle" means and what happens at 60 minutes
A Booster is **idle** when all of these are true for 60 continuous minutes:
- no Docker VM or container created through Vyomi is running;
- no AI request, API/SDK/CLI call or Nano console action has reached the Booster;
- no workflow or build job is running on it.

When the idle limit is reached Vyomi **destroys** the Booster (it does not only pause it):
- Everything stored inside it is permanently deleted: VMs, containers, images, the model cache, files and
  databases created in it. **Nothing is recoverable.**
- Your Nano browser data (your spaces and the resources held in your browser) is not affected.
- You are shown a notice in the console 10 minutes and 2 minutes before it happens. Any real activity resets the
  60-minute clock. Launching again creates a fresh environment from the template.
- Time used until destruction counts toward your allowance; time after it does not.

## 5. Back up what matters
The Booster is disposable by design. Export or copy any data you want to keep (repositories, database dumps,
VM disks, model outputs) to your own storage before the session ends. Vyomi is not responsible for data lost
when a session ends, expires, is stopped, or is destroyed for any reason in this document.

## 6. Acceptable use
You may use the Booster to develop, test and learn: build and run your own applications and services against
the simulated clouds, run containers and VMs for that purpose, and run the bundled AI model for your own testing.
You must not:
- mine cryptocurrency, run proxies/VPNs/relays for others, host public services, or send spam or attacks;
- run workloads unrelated to developing and testing software, or any use that GitHub's terms or acceptable-use
  policy forbid for Codespaces or Actions;
- try to bypass limits (for example, create extra accounts to get more hours) or share a Booster session;
- store real production secrets, real personal data or regulated data in the Booster or in Vyomi consoles.
Vyomi may stop or destroy a Booster that appears to break these rules, and may suspend Booster access.

## 7. Runner-hosted AI model (optional, off by default)
If you turn it on, Vyomi will start a workflow in a repository in your account that runs the AI model on a GitHub
Actions runner and connects it to your Booster. The same limits apply, plus: the repository's workflow logs may be
publicly visible if the repository is public, so never put secrets or private data in prompts you send while using
it, and the model runs only for the session (it is destroyed at the session end or after the 60-minute idle limit).
Do not turn this on unless GitHub's current terms allow it for your account. (OPEN: confirm with GitHub before launch.)

## 8. Availability and changes
The Booster depends on GitHub and on your GitHub quota. It is provided as-is, with no uptime commitment, and may
be unavailable, slower, or stopped without notice. Vyomi may change limits and prices with notice on the portal.
Pro and Max allowances, prices and the one-cloud rule for Pro are described on the pricing page.

## 9. Liability
To the extent the law allows, Vyomi is not liable for lost data, lost time, GitHub charges or account actions
taken by GitHub, or indirect damages arising from the Booster. Nothing here limits liability that cannot be
limited by law.

---
## Notes for the owner (delete before publishing)
1. **Code does not match this draft yet.** `portal-v4nano/app/booster_session.py` currently sets `IDLE_TIMEOUT_MIN = 5`
   (the Codespace idle stop passed to GitHub), a 5-minute heartbeat timeout and an 8 h hard cap. To honour §3-4:
   set the Codespace idle timeout to 60 (GitHub allows it), add a Vyomi-side idle monitor (no VMs, no API/AI/console
   activity for 60 min → delete the Codespace), and add the 10-min/2-min warnings to the Nano session chip. Today
   "idle" is only a GitHub-side timer for no input, which is not the same thing.
2. "If a user does not deploy a workflow the VM is destroyed after 60 minutes" was read as the **idle limit** above
   (nothing deployed or running for 60 min). If you meant "60 minutes after launch if no workflow is ever started",
   say so and §4 changes to a start-up grace of 60 minutes.
3. Destroy (delete) versus stop: the draft deletes, which frees GitHub storage and forces a clean start, but loses
   the Codespace disk. Stopping instead would keep the disk for GitHub's retention period; that is a one-line change
   in §4 and in the idle monitor.
4. Needs legal review before publishing, especially §2.4 (GitHub quota), §6 (GitHub terms) and §9.
5. Runner-hosted model (§7) is gated on the GitHub terms check noted in `BOOSTER-RUNNER-LLM.md` (spike branch).
