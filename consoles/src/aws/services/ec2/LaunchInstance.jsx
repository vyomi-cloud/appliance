import { useState } from "react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Form from "@cloudscape-design/components/form";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Checkbox from "@cloudscape-design/components/checkbox";
import Textarea from "@cloudscape-design/components/textarea";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import Grid from "@cloudscape-design/components/grid";
import Box from "@cloudscape-design/components/box";
import Modal from "@cloudscape-design/components/modal";
import Alert from "@cloudscape-design/components/alert";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { ErrorAlert, NotSimulated } from "../../kit/common.jsx";
import * as api from "./api.js";

const opt = (v, l) => ({ value: v, label: l || v });

export default function LaunchInstance({ query }) {
  const notify = useNotify();
  const cat = useAsync(() => Promise.all([api.describeImages({ Owner: ["amazon", "self"] }), api.describeInstanceTypes(), api.describeKeyPairs(), api.describeSecurityGroups(), api.describePlacementGroups()])
    .then(([images, types, keyPairs, sgs, pgs]) => ({ images, types, keyPairs, sgs, pgs })), []);

  const [name, setName] = useState("");
  const [search, setSearch] = useState("");
  const [quickStart, setQuickStart] = useState("Amazon Linux");
  const [amiId, setAmiId] = useState(query.ami || "");
  const [arch, setArch] = useState("64-bit (x86)");
  const [allGen, setAllGen] = useState(false);
  const [instanceType, setInstanceType] = useState("t3.micro");
  const [keyName, setKeyName] = useState("");
  const [firewall, setFirewall] = useState("create");
  const [allowSsh, setAllowSsh] = useState(true);
  const [allowHttps, setAllowHttps] = useState(false);
  const [allowHttp, setAllowHttp] = useState(false);
  const [existingSg, setExistingSg] = useState("");
  const [rootSize, setRootSize] = useState("8");
  const [rootType, setRootType] = useState("gp3");
  const [extraVolumes, setExtraVolumes] = useState([]);
  const [purchasing, setPurchasing] = useState("None");
  const [iamProfile, setIamProfile] = useState("");
  const [hostnameType, setHostnameType] = useState("IP name");
  const [autoRecovery, setAutoRecovery] = useState("Default");
  const [shutdownBehavior, setShutdownBehavior] = useState("Stop");
  const [hibernate, setHibernate] = useState("Disable");
  const [termProtect, setTermProtect] = useState("Disable");
  const [stopProtect, setStopProtect] = useState("Disable");
  const [monitoring, setMonitoring] = useState("Disable");
  const [creditSpec, setCreditSpec] = useState("Standard");
  const [placementGroup, setPlacementGroup] = useState("");
  const [tenancy, setTenancy] = useState("Shared - Run a shared hardware instance");
  const [metaAccessible, setMetaAccessible] = useState("Enabled");
  const [metaVersion, setMetaVersion] = useState("V2 only (token required)");
  const [userData, setUserData] = useState("");
  const [count, setCount] = useState("1");
  const [preview, setPreview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const images = cat.data?.images || [];
  const types = cat.data?.types || [];
  const quickImage = images.find((i) => i.name?.startsWith(quickStart));
  const effectiveAmiId = amiId || quickImage?.imageId || "";
  const searchedImages = search ? images.filter((i) => i.name?.toLowerCase().includes(search.toLowerCase())) : images;
  const visibleTypes = allGen ? types : types.filter((t) => t.InstanceType !== "t2.small" && t.InstanceType !== "m4.large");
  const macOs = quickStart === "macOS";

  const build = () => {
    const perms = [];
    if (firewall === "create") {
      if (allowSsh) perms.push({ IpProtocol: "tcp", FromPort: 22, ToPort: 22, cidr: "0.0.0.0/0" });
      if (allowHttps) perms.push({ IpProtocol: "tcp", FromPort: 443, ToPort: 443, cidr: "0.0.0.0/0" });
      if (allowHttp) perms.push({ IpProtocol: "tcp", FromPort: 80, ToPort: 80, cidr: "0.0.0.0/0" });
    }
    return perms;
  };

  const cliPreview = () => {
    const parts = ["aws", "ec2", "run-instances", "--image-id", effectiveAmiId, "--instance-type", instanceType, "--count", count];
    if (keyName) parts.push("--key-name", keyName);
    if (name) parts.push("--tag-specifications", `'ResourceType=instance,Tags=[{Key=Name,Value=${name}}]'`);
    return parts.join(" ");
  };

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      let sgId = existingSg;
      if (firewall === "create") {
        sgId = await api.createSecurityGroup(`launch-wizard-${Date.now().toString(36)}`, `launch-wizard-${name || "sg"}`);
        const perms = build();
        if (perms.length) await api.authorizeIngress(sgId, perms);
      }
      const insts = await api.runInstances({
        ImageId: effectiveAmiId, InstanceType: instanceType, MinCount: Number(count) || 1, MaxCount: Number(count) || 1,
        KeyName: keyName || undefined, SecurityGroupId: sgId ? [sgId] : undefined,
        Monitoring: { Enabled: monitoring === "Enable" }, DisableApiTermination: termProtect === "Enable",
        InstanceInitiatedShutdownBehavior: shutdownBehavior.toLowerCase(),
        IamInstanceProfile: iamProfile ? { Name: iamProfile } : undefined,
        CreditSpecification: { CpuCredits: creditSpec.toLowerCase() },
        Placement: { GroupName: placementGroup || undefined, Tenancy: tenancy.startsWith("Dedicated host") ? "host" : tenancy.startsWith("Dedicated") ? "dedicated" : "default" },
        MetadataOptions: { HttpTokens: metaVersion.startsWith("V2") ? "required" : "optional", HttpEndpoint: metaAccessible.toLowerCase() },
        HibernationOptions: { Configured: hibernate === "Enable" }, MaintenanceOptions: { AutoRecovery: autoRecovery.toLowerCase() },
        PrivateDnsNameOptions: { HostnameType: hostnameType === "IP name" ? "ip-name" : "resource-name" },
        UserData: userData ? api.b64(userData) : undefined,
        BlockDeviceMapping: [{ Ebs: { VolumeSize: Number(rootSize), VolumeType: rootType } }],
        TagSpecification: name ? [{ ResourceType: "instance", Tag: [{ Key: "Name", Value: name }] }] : undefined,
      });
      if (stopProtect === "Enable") await Promise.all(insts.map((i) => api.modifyInstanceAttribute(i.instanceId, { "DisableApiStop.Value": true })));
      for (const v of extraVolumes) {
        for (const inst of insts) {
          const vol = await api.createVolume({ Size: Number(v.size), VolumeType: v.type, AvailabilityZone: insts[0].placement?.availabilityZone });
          await api.attachVolume(vol.volumeId, inst.instanceId, v.device);
        }
      }
      notify.success(`Successfully launched ${insts.length > 1 ? `${insts.length} instances` : "instance"} (${insts.map((i) => i.instanceId).join(", ")}).`);
      navigate("ec2", "instances");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Launch an instance</Header>}>
      <Grid gridDefinition={[{ colspan: 8 }, { colspan: 4 }]}>
        <Form errorText={error && <ErrorAlert error={error} />}>
          <SpaceBetween size="l">
            <Container header={<Header variant="h2">Name and tags</Header>}>
              <FormField label="Name"><Input value={name} onChange={({ detail }) => setName(detail.value)} placeholder="e.g. My Web Server" ariaLabel="Name" /></FormField>
            </Container>

            <Container header={<Header variant="h2">Application and OS Images (Amazon Machine Image)</Header>}>
              <SpaceBetween size="l">
                <FormField label="Search our full catalog including 1000s of application and OS images">
                  <Input placeholder="Search our full catalog including 1000s of application and OS images" ariaLabel="Search our full catalog including 1000s of application and OS images"
                    value={search} onChange={({ detail }) => setSearch(detail.value)} type="search" />
                </FormField>
                <FormField label="Quick Start">
                  <RadioGroup value={quickStart} onChange={({ detail }) => { setQuickStart(detail.value); setAmiId(""); }}
                    items={["Amazon Linux", "macOS", "Ubuntu", "Windows", "Red Hat", "SUSE Linux", "Debian"].map((v) => ({ value: v, label: v }))} />
                </FormField>
                {macOs && <Alert type="info">macOS requires a Dedicated Host, which Vyomi doesn't model — pick another Quick Start option to launch.</Alert>}
                <FormField label="Amazon Machine Image (AMI)" description="Free tier eligible">
                  <Select selectedOption={effectiveAmiId ? opt(effectiveAmiId, images.find((i) => i.imageId === effectiveAmiId)?.name || effectiveAmiId) : null}
                    onChange={({ detail }) => setAmiId(detail.selectedOption.value)}
                    options={searchedImages.map((i) => opt(i.imageId, `${i.name} (${i.imageId})`))} loadingText="Loading AMIs" statusType={cat.loading ? "loading" : "finished"} ariaLabel="Amazon Machine Image (AMI)" />
                </FormField>
                <FormField label="Architecture">
                  <Select selectedOption={opt(arch, arch)} onChange={({ detail }) => setArch(detail.selectedOption.value)} options={[opt("64-bit (x86)"), opt("64-bit (Arm)")]} ariaLabel="Architecture" />
                </FormField>
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2">Instance type</Header>}>
              <SpaceBetween size="l">
                <FormField label="Instance type">
                  <Select selectedOption={opt(instanceType)} onChange={({ detail }) => setInstanceType(detail.selectedOption.value)}
                    options={visibleTypes.map((t) => opt(t.InstanceType, `${t.InstanceType} (${t.VCpuCount} vCPU, ${(t.MemoryMiB / 1024).toFixed(0)} GiB Memory)`))}
                    loadingText="Loading instance types" statusType={cat.loading ? "loading" : "finished"} ariaLabel="Instance type" />
                </FormField>
                <Checkbox checked={allGen} onChange={({ detail }) => setAllGen(detail.checked)}>All generations</Checkbox>
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2">Key pair (login)</Header>}>
              <FormField label="Key pair name" description="You can use a key pair to securely connect to your instance."
                secondaryControl={<Button href={href("ec2", "create-key-pair")} onFollow={follow}>Create new key pair</Button>}>
                <Select selectedOption={keyName ? opt(keyName) : null} onChange={({ detail }) => setKeyName(detail.selectedOption.value)}
                  placeholder="Select a key pair" options={(cat.data?.keyPairs || []).map((k) => opt(k.keyName))} ariaLabel="Key pair name" />
              </FormField>
            </Container>

            <Container header={<Header variant="h2">Network settings</Header>}>
              <SpaceBetween size="l">
                <FormField label="Firewall (security groups)">
                  <RadioGroup value={firewall} onChange={({ detail }) => setFirewall(detail.value)}
                    items={[{ value: "create", label: "Create security group" }, { value: "existing", label: "Select existing security group" }]} />
                </FormField>
                {firewall === "create" ? (
                  <SpaceBetween size="xs">
                    <Checkbox checked={allowSsh} onChange={({ detail }) => setAllowSsh(detail.checked)}>Allow SSH traffic from Anywhere</Checkbox>
                    <Checkbox checked={allowHttps} onChange={({ detail }) => setAllowHttps(detail.checked)}>Allow HTTPS traffic from the internet</Checkbox>
                    <Checkbox checked={allowHttp} onChange={({ detail }) => setAllowHttp(detail.checked)}>Allow HTTP traffic from the internet</Checkbox>
                  </SpaceBetween>
                ) : (
                  <FormField label="Common security groups">
                    <Select selectedOption={existingSg ? opt(existingSg) : null} onChange={({ detail }) => setExistingSg(detail.selectedOption.value)}
                      placeholder="Select security groups" options={(cat.data?.sgs || []).map((g) => opt(g.GroupId, `${g.GroupName} (${g.GroupId})`))} ariaLabel="Common security groups" />
                  </FormField>
                )}
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2">Configure storage</Header>}>
              <SpaceBetween size="l">
                <FormField label="Root volume" description="Size (GiB), volume type">
                  <SpaceBetween direction="horizontal" size="xs">
                    <Input type="number" value={rootSize} onChange={({ detail }) => setRootSize(detail.value)} ariaLabel="Root volume size (GiB)" />
                    <Select selectedOption={opt(rootType)} onChange={({ detail }) => setRootType(detail.selectedOption.value)}
                      options={["gp3", "gp2", "io1", "io2", "sc1", "st1", "standard"].map(opt)} ariaLabel="Root volume type" />
                  </SpaceBetween>
                </FormField>
                {extraVolumes.map((v, idx) => (
                  <SpaceBetween key={idx} direction="horizontal" size="xs">
                    <Input type="number" value={v.size} onChange={({ detail }) => setExtraVolumes((xs) => xs.map((x, i) => (i === idx ? { ...x, size: detail.value } : x)))} ariaLabel={`Volume ${idx + 2} size`} />
                    <Select selectedOption={opt(v.type)} onChange={({ detail }) => setExtraVolumes((xs) => xs.map((x, i) => (i === idx ? { ...x, type: detail.selectedOption.value } : x)))} options={["gp3", "gp2"].map(opt)} ariaLabel={`Volume ${idx + 2} type`} />
                    <Button iconName="close" ariaLabel="Remove volume" onClick={() => setExtraVolumes((xs) => xs.filter((_, i) => i !== idx))} />
                  </SpaceBetween>
                ))}
                <Button onClick={() => setExtraVolumes((xs) => [...xs, { size: "8", type: "gp3", device: `/dev/sd${String.fromCharCode(102 + xs.length)}` }])}>Add new volume</Button>
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2">Advanced details</Header>}>
              <SpaceBetween size="l">
                <FormField label="Purchasing option">
                  <RadioGroup value={purchasing} onChange={({ detail }) => setPurchasing(detail.value)} items={["None", "Capacity Blocks", "Spot instances"].map((v) => ({ value: v, label: v }))} />
                </FormField>
                {purchasing !== "None" && <NotSimulated feature={purchasing} note="Vyomi launches a regular on-demand instance regardless of the purchasing option chosen." />}
                <FormField label="IAM instance profile" secondaryControl={<Button onClick={() => navigate("ec2", "create-iam-profile")}>Create new IAM profile</Button>}>
                  <Input value={iamProfile} onChange={({ detail }) => setIamProfile(detail.value)} placeholder="None" ariaLabel="IAM instance profile" />
                </FormField>
                <SelectField label="Hostname type" value={hostnameType} setValue={setHostnameType} options={["IP name", "Resource name"]} />
                <SelectField label="Instance auto-recovery" value={autoRecovery} setValue={setAutoRecovery} options={["Default", "Disable"]} />
                <SelectField label="Shutdown behavior" value={shutdownBehavior} setValue={setShutdownBehavior} options={["Stop", "Terminate"]} />
                <SelectField label="Stop - Hibernate behavior" value={hibernate} setValue={setHibernate} options={["Disable", "Enable"]} />
                <SelectField label="Termination protection" value={termProtect} setValue={setTermProtect} options={["Disable", "Enable"]} />
                <SelectField label="Stop protection" value={stopProtect} setValue={setStopProtect} options={["Disable", "Enable"]} />
                <SelectField label="Detailed CloudWatch monitoring" value={monitoring} setValue={setMonitoring} options={["Disable", "Enable"]} />
                <SelectField label="Credit specification" value={creditSpec} setValue={setCreditSpec} options={["Standard", "Unlimited"]} />
                <FormField label="Placement group">
                  <Select selectedOption={placementGroup ? opt(placementGroup) : null} onChange={({ detail }) => setPlacementGroup(detail.selectedOption.value)}
                    placeholder="No preference" options={(cat.data?.pgs || []).map((g) => opt(g.groupName))} ariaLabel="Placement group" />
                </FormField>
                <SelectField label="Tenancy" value={tenancy} setValue={setTenancy} options={["Shared - Run a shared hardware instance", "Dedicated - Run a dedicated instance", "Dedicated host - Launch this instance on a dedicated host"]} />
                <SelectField label="Metadata accessible" value={metaAccessible} setValue={setMetaAccessible} options={["Enabled", "Disabled"]} />
                <SelectField label="Metadata version" value={metaVersion} setValue={setMetaVersion} options={["V1 and V2 (token optional)", "V2 only (token required)"]} />
                <FormField label="User data - optional">
                  <Textarea value={userData} onChange={({ detail }) => setUserData(detail.value)} rows={6} ariaLabel="User data - optional" />
                </FormField>
              </SpaceBetween>
            </Container>
          </SpaceBetween>
        </Form>

        <Container header={<Header variant="h2">Summary</Header>}>
          <SpaceBetween size="l">
            <FormField label="Number of instances"><Input type="number" value={count} onChange={({ detail }) => setCount(detail.value)} ariaLabel="Number of instances" /></FormField>
            <Box variant="awsui-key-label">Software Image (AMI)</Box><div>{images.find((i) => i.imageId === effectiveAmiId)?.name || "-"}</div>
            <Box variant="awsui-key-label">Virtual server type (instance type)</Box><div>{instanceType}</div>
            <Box variant="awsui-key-label">Firewall (security group)</Box><div>{firewall === "create" ? "New security group" : existingSg || "-"}</div>
            <Box variant="awsui-key-label">Storage (volumes)</Box><div>{1 + extraVolumes.length} volume(s) - {rootSize} GiB</div>
            <SpaceBetween direction="horizontal" size="xs">
              <Button formAction="none" href={href("ec2", "instances")} onFollow={follow}>Cancel</Button>
              <Button formAction="none" onClick={() => setPreview(true)}>Preview code</Button>
            </SpaceBetween>
            <Button variant="primary" loading={busy} disabled={!effectiveAmiId || macOs} onClick={submit}>Launch instance</Button>
          </SpaceBetween>
        </Container>
      </Grid>
      <Modal visible={preview} onDismiss={() => setPreview(false)} header="Preview code" size="large" footer={<Box float="right"><Button onClick={() => setPreview(false)}>Close</Button></Box>}>
        <Box variant="code">{cliPreview()}</Box>
      </Modal>
    </ContentLayout>
  );
}

function SelectField({ label, value, setValue, options }) {
  return <FormField label={label}><Select selectedOption={opt(value)} onChange={({ detail }) => setValue(detail.selectedOption.value)} options={options.map((v) => opt(v))} ariaLabel={label} /></FormField>;
}
