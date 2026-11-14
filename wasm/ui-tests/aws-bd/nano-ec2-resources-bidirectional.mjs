/* GENUINE NANO: EC2 resources beyond instances/keys/SGs — volumes (create/attach/detach/delete), snapshots, Elastic IPs (allocate/associate/disassociate/release),
 * AMI from instance + deregister, launch templates, instance reboot + monitoring + tags, SG inbound rule edit, load balancer / target group.
 * UI action -> native EC2/ELBv2 wire verification FIRST, then API -> UI. Output tests/conformance/hourly/out/aws-nano-ec2-resources-bidirectional.md */
import { boot, ck, rec, N, sleep, xf, xall } from "./nano-bd-lib.mjs";
const H = await boot(); const { page } = H;
const ec2 = (A, p) => H.query("ec2", A, p);
const elb = (A, p) => H.query("elasticloadbalancing", A, p, "2015-12-01");
const parseVol = (c) => ({ id: xf(c, "volumeId"), size: xf(c, "size"), type: xf(c, "volumeType"), az: xf(c, "availabilityZone"), status: (c.match(/<\/attachmentSet>[\s\S]*?<status>([^<]*)/) || c.match(/<status>([^<]*)/) || [])[1], att: xf(c.split("<attachmentSet>")[1] || "", "instanceId"), tags: c.match(/<key>Name<\/key><value>([^<]*)/)?.[1] });
const vols = async () => {   // one DescribeVolumes per id (the attachment <item> also starts with volumeId, so a flat split would truncate)
  const ids = xall((await ec2("DescribeVolumes")).text.replace(/<attachmentSet>[\s\S]*?<\/attachmentSet>/g, ""), "volumeId");
  const out = []; for (const id of ids) out.push(parseVol((await ec2("DescribeVolumes", { "VolumeId.1": id })).text)); return out;
};
const waitFor = async (fn, ms = 40000) => { const t0 = Date.now(); let v; while (Date.now() - t0 < ms) { v = await fn(); if (v) return v; await sleep(2000); } return v; };
const created = { inst: [], vol: [], snap: [], eip: [], img: [], lt: [], sg: [], lb: [], tg: [] };
try {
  await H.go("ec2/instances");
  // fixture instance (launch UI path is covered by nano-ec2-bidirectional.mjs)
  var imgId = xf((await ec2("DescribeImages", { "Owner.1": "amazon" })).text, "imageId");
  var iname = N("fx");
  var ri = await ec2("RunInstances", { ImageId: imgId, InstanceType: "t3.micro", MinCount: "1", MaxCount: "1", "TagSpecification.1.ResourceType": "instance", "TagSpecification.1.Tag.1.Key": "Name", "TagSpecification.1.Tag.1.Value": iname });
  var iid = xf(ri.text, "instanceId"); created.inst.push(iid);
  ck("(fixture) RunInstances for resource tests", !!iid, `HTTP ${ri.status}`);
  await waitFor(async () => /<name>running<\/name>/.test((await ec2("DescribeInstances", { "InstanceId.1": iid })).text));

  var SEC = '== Volumes';
  try {
  var uiVol = N("uivol"), apiVol = N("apivol");
  await H.go("ec2/create-volume");
  await page.locator('input[aria-label="Size (GiB)"]').fill("3");
  // Name tag via the tag editor
  await page.getByRole("button", { name: /Add new tag/ }).first().click().catch(() => {});
  await page.locator('input[placeholder*="key" i]').first().fill("Name").catch(() => {}); await page.locator('input[placeholder*="value" i]').first().fill(uiVol).catch(() => {});
  await H.click(/^Create volume$/);
  var v1 = await waitFor(async () => (await vols()).find((v) => v.tags === uiVol));
  ck("(vol) UI->API: volume created in console is in DescribeVolumes (size 3, gp3, Name tag)", !!v1 && v1.size === "3" && v1.type === "gp3", JSON.stringify(v1 || (await vols()).slice(-2)));
  if (v1) created.vol.push(v1.id);
  var cv = await ec2("CreateVolume", { AvailabilityZone: "us-east-1a", Size: "2", VolumeType: "gp3", "TagSpecification.1.ResourceType": "volume", "TagSpecification.1.Tag.1.Key": "Name", "TagSpecification.1.Tag.1.Value": apiVol });
  var apiVolId = xf(cv.text, "volumeId"); if (apiVolId) created.vol.push(apiVolId);
  ck("(vol) API->UI: volume created over the API is listed in the console", !!apiVolId && await H.listHas("ec2/volumes", apiVol), `HTTP ${cv.status}`);
  if (v1) {
    // attach in UI
    await H.selectRow("ec2/volumes", uiVol); await H.menu(/^Actions$/, /Attach volume/);
    await H.pick("Instance", new RegExp(iid), "Select an instance"); await H.click(/^Attach volume$/).catch(() => {});
    const att = await waitFor(async () => (await vols()).find((v) => v.id === v1.id && v.att === iid));
    ck("(vol) UI->API: Attach volume in console -> DescribeVolumes shows attachment to the instance", !!att, JSON.stringify((await vols()).find((v) => v.id === v1.id)));
    ck("(vol) API->UI: volume list shows attached instance + in-use", await H.listHas("ec2/volumes", iid) && /in-use/.test(await H.body()));
    await H.selectRow("ec2/volumes", uiVol); await H.menu(/^Actions$/, /Detach volume/); await sleep(1500);
    const det = await waitFor(async () => (await vols()).find((v) => v.id === v1.id && !v.att && v.status === "available"));
    ck("(vol) UI->API: Detach volume in console -> available, no attachment", !!det, JSON.stringify((await vols()).find((v) => v.id === v1.id)));
  }
  if (apiVolId) {
    const aa = await ec2("AttachVolume", { VolumeId: apiVolId, InstanceId: iid, Device: "/dev/sdg" });
    await sleep(1500); await H.go("ec2/volumes"); const rt = await H.row(apiVol).innerText().catch(() => "");
    ck("(vol) API->UI: AttachVolume over the API shows in console row (instance id)", aa.status === 200 && rt.includes(iid), rt.replace(/\s+/g, " ").slice(0, 120));
    await ec2("DetachVolume", { VolumeId: apiVolId }); await waitFor(async () => (await vols()).find((v) => v.id === apiVolId && !v.att));
  }
  // snapshot (UI create from volume)
  if (v1) {
    await H.go("ec2/create-snapshot"); await H.pick("Volume ID", new RegExp(v1.id), "Select a volume"); await H.click(/^Create snapshot$/);
    const sn = await waitFor(async () => { const t = (await ec2("DescribeSnapshots", { "Owner.1": "self" })).text; return t.includes(v1.id) ? xf(t.split(v1.id)[0].split("<item>").pop() + v1.id + t.split(v1.id)[1], "snapshotId") : null; });
    const sid = (await ec2("DescribeSnapshots", { "Owner.1": "self" })).text.split(/<item><snapshotId>/).slice(1).map((c) => ({ id: c.split("<")[0], vol: xf(c, "volumeId") })).find((s) => s.vol === v1.id)?.id;
    ck("(snap) UI->API: snapshot created in console is in DescribeSnapshots for that volume", !!sid, sid || "none");
    if (sid) {
      created.snap.push(sid);
      ck("(snap) API->UI: snapshot listed in console", await H.listHas("ec2/snapshots", sid));
      await H.selectRow("ec2/snapshots", sid); await H.menu(/^Actions$/, /Delete snapshot/); await H.confirmDelete();
      const gone = await waitFor(async () => !(await ec2("DescribeSnapshots", { "Owner.1": "self" })).text.includes(sid), 20000);
      ck("(snap) UI delete -> API: snapshot gone from DescribeSnapshots", !!gone);
    }
  }
  var as = await ec2("CreateSnapshot", { VolumeId: apiVolId || v1?.id, Description: N("apisnap") });
  var asid = xf(as.text, "snapshotId"); if (asid) created.snap.push(asid);
  ck("(snap) API->UI: snapshot created over the API is listed", !!asid && await H.listHas("ec2/snapshots", asid), `HTTP ${as.status}`);
  if (asid) { await ec2("DeleteSnapshot", { SnapshotId: asid }); await H.go("ec2/snapshots"); ck("(snap) API delete -> UI: snapshot gone from list", await H.waitUntilGone(asid)); }
  // delete volumes both ways
  if (v1) {
    await H.selectRow("ec2/volumes", uiVol); await H.menu(/^Actions$/, /Delete volume/); await H.confirmDelete();
    ck("(vol) UI delete -> API: volume deleted in console is gone from DescribeVolumes", !!(await waitFor(async () => !(await vols()).some((v) => v.id === v1.id), 20000)));
  }
  if (apiVolId) { await ec2("DeleteVolume", { VolumeId: apiVolId }); await H.go("ec2/volumes"); ck("(vol) API delete -> UI: volume gone from list", await H.waitUntilGone(apiVol)); }

  } catch (e) { rec("(section) aborted: "+SEC, "FAIL", String(e.message).split("\n")[0]); await page.screenshot({ path: (process.env.SHOT_DIR || ".") + "/res-"+SEC.replace(/\W+/g,"_")+".png" }).catch(() => {}); }
  var SEC = '== Elastic IPs';
  try {
  await H.go("ec2/allocate-elastic-ip"); await H.click(/^Allocate$/);
  var addrs = async () => (await ec2("DescribeAddresses")).text.split("<item><publicIp>").slice(1).map((c) => ({ alloc: xf(c, "allocationId"), ip: c.split("<")[0], inst: xf(c, "instanceId"), assoc: xf(c, "associationId") }));
  var a1 = await waitFor(async () => (await addrs())[0]);
  ck("(eip) UI->API: Allocate in console -> DescribeAddresses has an allocation", !!a1, JSON.stringify(a1));
  if (a1) {
    created.eip.push(a1.alloc);
    ck("(eip) API->UI: EIP listed in console by public IP", await H.listHas("ec2/elastic-ips", a1.ip));
    await H.selectRow("ec2/elastic-ips", a1.ip); await H.menu(/^Actions$/, /^Associate Elastic IP address$/);
    await H.pick("Instance", new RegExp(iid), "Select an instance"); await H.click(/^Associate$/);
    const as1 = await waitFor(async () => (await addrs()).find((a) => a.alloc === a1.alloc && a.inst === iid));
    ck("(eip) UI->API: Associate in console -> DescribeAddresses InstanceId set", !!as1, JSON.stringify((await addrs()).find((a) => a.alloc === a1.alloc)));
    const di = (await ec2("DescribeInstances", { "InstanceId.1": iid })).text;
    ck("(eip) UI->API: instance now reports the Elastic IP as its public IP", xf(di, "ipAddress") === a1.ip, `instance ip ${xf(di, "ipAddress")} eip ${a1.ip}`);
    await H.selectRow("ec2/elastic-ips", a1.ip); await H.menu(/^Actions$/, /^Disassociate Elastic IP address$/);
    ck("(eip) UI->API: Disassociate in console -> no InstanceId", !!(await waitFor(async () => (await addrs()).find((a) => a.alloc === a1.alloc && !a.inst))), "");
    await H.selectRow("ec2/elastic-ips", a1.ip); await H.menu(/^Actions$/, /^Release Elastic IP addresses$/); await H.confirmDelete().catch(() => {});
    ck("(eip) UI->API: Release in console -> allocation gone", !!(await waitFor(async () => !(await addrs()).some((a) => a.alloc === a1.alloc), 20000)), "");
  }
  var ea = await ec2("AllocateAddress", { Domain: "vpc" }); const eaId = xf(ea.text, "allocationId"), eaIp = xf(ea.text, "publicIp"); if (eaId) created.eip.push(eaId);
  ck("(eip) API->UI: address allocated over the API is listed", !!eaId && await H.listHas("ec2/elastic-ips", eaIp));
  if (eaId) { await ec2("AssociateAddress", { AllocationId: eaId, InstanceId: iid }); await H.go("ec2/elastic-ips"); const r = await H.row(eaIp).innerText().catch(() => ""); ck("(eip) API->UI: associate over API shows instance in row", r.includes(iid), r.replace(/\s+/g, " ").slice(0, 100)); await ec2("DisassociateAddress", { AssociationId: (await addrs()).find((a) => a.alloc === eaId)?.assoc || "x" }); await ec2("ReleaseAddress", { AllocationId: eaId }); }

  } catch (e) { rec("(section) aborted: "+SEC, "FAIL", String(e.message).split("\n")[0]); await page.screenshot({ path: (process.env.SHOT_DIR || ".") + "/res-"+SEC.replace(/\W+/g,"_")+".png" }).catch(() => {}); }
  var SEC = '== Instance actions: reboot, monitoring, create image';
  try {
  await H.selectRow("ec2/instances", iname); await H.menu(/^Instance state$/, /Reboot instance/);
  await page.getByRole("button", { name: /^Reboot$/ }).last().dispatchEvent("click").catch(() => {}); await sleep(3000);
  var after = (await ec2("DescribeInstances", { "InstanceId.1": iid })).text;
  ck("(inst) UI reboot: instance remains running in API after Reboot instance", /<name>running<\/name>/.test(after), "");
  await H.selectRow("ec2/instances", iname); await H.menu(/^Actions$/, /Enable detailed monitoring/).catch(() => rec("(inst) monitoring menu", "NOT-AUTOMATED", "menu not reachable"));
  await sleep(1500);
  ck("(inst) UI->API: enable detailed monitoring -> DescribeInstances monitoring=enabled", /<monitoring><state>enabled/.test((await ec2("DescribeInstances", { "InstanceId.1": iid })).text), "");
  var imgName = N("uiimg");
  await H.go(`ec2/instances/${iid}/create-image`);
  await page.locator('input[aria-label="Image name"]').fill(imgName).catch(async () => { await page.getByLabel("Image name").fill(imgName); });
  await H.click(/^Create image$/);
  var mine = async () => (await ec2("DescribeImages", { "Owner.1": "self" })).text.split(/<item><imageId>/).slice(1).map((c) => ({ id: c.split("<")[0], name: xf(c, "name"), src: xf(c, "sourceInstanceId") }));
  var im = await waitFor(async () => (await mine()).find((i) => i.name === imgName));
  ck("(ami) UI->API: Create image from instance in console -> DescribeImages(self) has it", !!im, JSON.stringify((await mine()).slice(-3)));
  if (im) {
    created.img.push(im.id);
    ck("(ami) API->UI: AMI listed in console AMIs", await H.listHas("ec2/amis", imgName));
    await H.selectRow("ec2/amis", imgName); await H.menu(/^Actions$/, /Deregister AMI/); await H.confirmDelete();
    ck("(ami) UI Deregister -> API: image gone from DescribeImages(self)", !!(await waitFor(async () => !(await mine()).some((i) => i.id === im.id), 20000)));
  }
  var ci = await ec2("CreateImage", { InstanceId: iid, Name: N("apiimg") }); const ciId = xf(ci.text, "imageId"); if (ciId) created.img.push(ciId);
  ck("(ami) API->UI: AMI created over the API from instance is listed", !!ciId && await H.listHas("ec2/amis", N("apiimg")), `HTTP ${ci.status}`);

  } catch (e) { rec("(section) aborted: "+SEC, "FAIL", String(e.message).split("\n")[0]); await page.screenshot({ path: (process.env.SHOT_DIR || ".") + "/res-"+SEC.replace(/\W+/g,"_")+".png" }).catch(() => {}); }
  var SEC = '== Launch templates';
  try {
  var lt = N("uilt");
  await H.go("ec2/create-launch-template"); await page.getByLabel("Launch template name").fill(lt); await H.click(/^Create launch template$/);
  var ltq = async () => (await ec2("DescribeLaunchTemplates")).text;
  var lok = await waitFor(async () => (await ltq()).includes(lt));
  ck("(lt) UI->API: launch template created in console is in DescribeLaunchTemplates", !!lok, (await ltq()).slice(0, 150));
  if (lok) {
    ck("(lt) API->UI: listed in console", await H.listHas("ec2/launch-templates", lt));
    await H.selectRow("ec2/launch-templates", lt); await H.menu(/^Actions$/, /Delete template/); await H.confirmDelete();
    ck("(lt) UI delete -> API: template gone", !!(await waitFor(async () => !(await ltq()).includes(lt), 20000)));
  }
  var alt = await ec2("CreateLaunchTemplate", { LaunchTemplateName: N("apilt"), "LaunchTemplateData.InstanceType": "t3.micro", "LaunchTemplateData.ImageId": imgId });
  ck("(lt) API->UI: template created over the API is listed", alt.status === 200 && await H.listHas("ec2/launch-templates", N("apilt")), `HTTP ${alt.status}`);
  created.lt.push(N("apilt"));

  } catch (e) { rec("(section) aborted: "+SEC, "FAIL", String(e.message).split("\n")[0]); await page.screenshot({ path: (process.env.SHOT_DIR || ".") + "/res-"+SEC.replace(/\W+/g,"_")+".png" }).catch(() => {}); }
  var SEC = '== Security group rule edit in UI';
  try {
  var sgn = N("rulesg"); const sgc = await ec2("CreateSecurityGroup", { GroupName: sgn, GroupDescription: "rules" }); const sgid = xf(sgc.text, "groupId"); created.sg.push(sgid);
  await H.go(`ec2/security-groups/${sgid}/edit-inbound-rules`);
  await page.getByRole("button", { name: /^Add rule$/ }).first().click().catch(() => {}); await sleep(600);
  await page.locator('input[aria-label*="Port range" i], input[placeholder*="port" i]').first().fill("8080").catch(() => {});
  await page.locator('input[aria-label="Source"]').first().fill("10.1.0.0/16");
  await H.click(/^Save rules$/);
  var perm = (await ec2("DescribeSecurityGroups", { "GroupId.1": sgid })).text;
  ck("(sg) UI->API: inbound rule added in console shows in DescribeSecurityGroups (8080 from 10.1.0.0/16)", perm.includes("<fromPort>8080") && perm.includes("10.1.0.0/16"), perm.slice(perm.indexOf("<ipPermissions>"), perm.indexOf("<ipPermissions>") + 300));
  await ec2("AuthorizeSecurityGroupIngress", { GroupId: sgid, "IpPermissions.1.IpProtocol": "tcp", "IpPermissions.1.FromPort": "9090", "IpPermissions.1.ToPort": "9090", "IpPermissions.1.IpRanges.1.CidrIp": "10.2.0.0/16" });
  await H.go(`ec2/security-groups/${sgid}`); await sleep(1500); const sgt = await H.body();
  ck("(sg) API->UI: rule added over the API shows in SG detail", sgt.includes("9090") || (await (async () => { await H.nav(`ec2/security-groups/${sgid}/edit-inbound-rules`); return (await H.body()).includes("9090"); })()), "");

  } catch (e) { rec("(section) aborted: "+SEC, "FAIL", String(e.message).split("\n")[0]); await page.screenshot({ path: (process.env.SHOT_DIR || ".") + "/res-"+SEC.replace(/\W+/g,"_")+".png" }).catch(() => {}); }
  var SEC = '== Load balancer + target group (UI create -> API)';
  try {
  var tgn = N("uitg");
  await H.go("ec2/create-target-group");
  await page.locator('input[aria-label="Target group name"]').fill(tgn);
  await H.pick("VPC", /vpc-/, "Select a VPC");
  await H.click(/^Create target group$/); await sleep(1500);
  var tgq = async () => (await elb("DescribeTargetGroups")).text;
  var tok = await waitFor(async () => (await tgq()).includes(tgn), 15000);
  ck("(tg) UI->API: target group created in console is in elbv2 DescribeTargetGroups", !!tok, (await tgq()).slice(0, 160));
  var atg = await elb("CreateTargetGroup", { Name: N("apitg"), Protocol: "HTTP", Port: "80", VpcId: xf((await ec2("DescribeVpcs")).text, "vpcId") });
  var atgArn = xf(atg.text, "TargetGroupArn"); if (atgArn) created.tg.push(atgArn);
  ck("(tg) API->UI: target group created over the API is listed", atg.status === 200 && await H.listHas("ec2/target-groups", N("apitg")), `HTTP ${atg.status} ${atg.text.slice(0, 120)}`);
  var sub = (await ec2("DescribeSubnets")).text; const subIds = xall(sub, "subnetId").slice(0, 2);
  var alb = await elb("CreateLoadBalancer", { Name: N("apilb"), "Subnets.member.1": subIds[0], "Subnets.member.2": subIds[1] || subIds[0], Type: "application" });
  var albArn = xf(alb.text, "LoadBalancerArn"); if (albArn) created.lb.push(albArn);
  ck("(lb) API->UI: load balancer created over the API is listed", alb.status === 200 && await H.listHas("ec2/load-balancers", N("apilb")), `HTTP ${alb.status} ${alb.text.slice(0, 120)}`);
  if (albArn) {
    await H.selectRow("ec2/load-balancers", N("apilb")); await H.menu(/^Actions$/, /^Delete$/); await H.confirmDelete();
    ck("(lb) UI delete -> API: load balancer gone from DescribeLoadBalancers", !!(await waitFor(async () => !(await elb("DescribeLoadBalancers")).text.includes(N("apilb")), 20000)), "");
    created.lb = [];
  }

  } catch (e) { rec("(section) aborted: "+SEC, "FAIL", String(e.message).split("\n")[0]); await page.screenshot({ path: (process.env.SHOT_DIR || ".") + "/res-"+SEC.replace(/\W+/g,"_")+".png" }).catch(() => {}); }
} catch (e) {
  rec("(run) harness ran to completion", "FAIL", String(e.message).split("\n")[0]);
  await page.screenshot({ path: (process.env.SHOT_DIR || ".") + "/ec2-res-fail.png" }).catch(() => {});
}
for (const id of created.inst) await ec2("TerminateInstances", { "InstanceId.1": id }).catch(() => {});
for (const a of created.tg) await elb("DeleteTargetGroup", { TargetGroupArn: a }).catch(() => {});
for (const a of created.lb) await elb("DeleteLoadBalancer", { LoadBalancerArn: a }).catch(() => {});
for (const n of created.lt) await ec2("DeleteLaunchTemplate", { LaunchTemplateName: n }).catch(() => {});
await H.finish("AWS Nano EC2 resources console <-> native wire bi-directional report", "aws-nano-ec2-resources-bidirectional.md");
