import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Form from "@cloudscape-design/components/form";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import Textarea from "@cloudscape-design/components/textarea";
import Checkbox from "@cloudscape-design/components/checkbox";
import RadioGroup from "@cloudscape-design/components/radio-group";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import TagEditor from "@cloudscape-design/components/tag-editor";
import Box from "@cloudscape-design/components/box";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import { TAG_I18N } from "./InstanceDetail.jsx";
import * as api from "./api.js";

const opt = (v) => ({ value: v, label: v });

export function LaunchTemplates() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const t = useAsync(() => api.describeLaunchTemplates(), []);
  return (
    <ContentLayout header={<Header variant="h1">New launch template</Header>}>
      <ResourceTable
        resourceName="Launch templates"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="launchTemplateId"
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search"
        columns={[
          { id: "id", header: "Launch template ID", isRowHeader: true, cell: (x) => x.launchTemplateId },
          { id: "name", header: "Launch template name", cell: (x) => x.launchTemplateName },
          { id: "def", header: "Default version", cell: (x) => x.defaultVersionNumber },
          { id: "latest", header: "Latest version", cell: (x) => x.latestVersionNumber },
          { id: "created", header: "Create time", cell: (x) => x.createTime },
          { id: "by", header: "Created by", cell: (x) => x.createdBy },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown disabled={!sel.length} items={[{ id: "delete", text: "Delete template" }]} onItemClick={async () => {
              await api.deleteLaunchTemplate(sel[0].launchTemplateId); notify.success(`Deleted launch template "${sel[0].launchTemplateName}".`); setSel([]); t.reload();
            }}>Actions</ButtonDropdown>
            <Button variant="primary" href={href("ec2", "create-launch-template")} onFollow={follow}>Create launch template</Button>
          </SpaceBetween>
        }
        empty={{ title: "No launch templates", action: <Button href={href("ec2", "create-launch-template")} onFollow={follow}>Create launch template</Button> }}
      />
    </ContentLayout>
  );
}

export function CreateLaunchTemplate() {
  const notify = useNotify();
  const cat = useAsync(() => Promise.all([api.describeImages({ Owner: ["amazon", "self"] }), api.describeInstanceTypes(), api.describeKeyPairs(), api.describeSecurityGroups(), api.describeSubnets()])
    .then(([images, types, keyPairs, sgs, subnets]) => ({ images, types, keyPairs, sgs, subnets })), []);
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [asGuidance, setAsGuidance] = useState(false);
  const [tags, setTags] = useState([]);
  const [amiId, setAmiId] = useState("");
  const [instanceType, setInstanceType] = useState("");
  const [keyName, setKeyName] = useState("");
  const [firewall, setFirewall] = useState("existing");
  const [sgId, setSgId] = useState("");
  const [iamProfile, setIamProfile] = useState("");
  const [shutdownBehavior, setShutdownBehavior] = useState("");
  const [termProtect, setTermProtect] = useState("");
  const [subnetId, setSubnetId] = useState("");
  const [userData, setUserData] = useState("");
  const [extraVolumes, setExtraVolumes] = useState([]);
  const [resourceTags, setResourceTags] = useState([]);
  const [eniNote, setEniNote] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const blockDevices = extraVolumes.map((v, idx) => ({ DeviceName: `/dev/sd${String.fromCharCode(102 + idx)}`, Ebs: { VolumeSize: Number(v.size), VolumeType: v.type } }));
      const resTags = resourceTags.filter((t) => !t.markedForRemoval && t.key);
      await api.createLaunchTemplate(name, {
        ImageId: amiId || undefined, InstanceType: instanceType || undefined, KeyName: keyName || undefined,
        SubnetId: subnetId || undefined, SecurityGroupIds: sgId ? [sgId] : undefined, IamInstanceProfile: iamProfile ? { Name: iamProfile } : undefined,
        InstanceInitiatedShutdownBehavior: shutdownBehavior || undefined, DisableApiTermination: termProtect === "Enable",
        UserData: userData ? api.b64(userData) : undefined, BlockDeviceMapping: blockDevices.length ? blockDevices : undefined,
        TagSpecification: resTags.length ? [{ ResourceType: "instance", Tag: resTags.map((t) => ({ Key: t.key, Value: t.value })) }] : undefined,
      }, desc, Object.fromEntries(tags.filter((t) => !t.markedForRemoval && t.key).map((t) => [t.key, t.value])));
      notify.success(`Launch template "${name}" created.`);
      navigate("ec2", "launch-templates");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create launch template</Header>}>
      <Form errorText={error && <ErrorAlert error={error} />} actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button formAction="none" href={href("ec2", "launch-templates")} onFollow={follow}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!name} onClick={submit}>Create launch template</Button>
        </SpaceBetween>
      }>
        <SpaceBetween size="l">
          <Container header={<Header variant="h2">Launch template name and description</Header>}>
            <SpaceBetween size="l">
              <FormField label="Launch template name" constraintText="Up to 128 characters; no spaces or '&*@'">
                <Input value={name} onChange={({ detail }) => setName(detail.value)} placeholder="MyTemplate" ariaLabel="Launch template name" />
              </FormField>
              <FormField label="Template version description"><Textarea value={desc} onChange={({ detail }) => setDesc(detail.value)} placeholder="A prod webserver for MyApp" ariaLabel="Template version description" /></FormField>
              <Checkbox checked={asGuidance} onChange={({ detail }) => setAsGuidance(detail.checked)}>Auto Scaling guidance</Checkbox>
            </SpaceBetween>
          </Container>
          <Container header={<Header variant="h2">Template tags</Header>}>
            <FormField label="Tags"><TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} i18nStrings={TAG_I18N} /></FormField>
          </Container>
          <Container header={<Header variant="h2">Source template</Header>}>
            <FormField label="Source template"><Select selectedOption={{ value: "", label: "Don't use a source template" }} options={[{ value: "", label: "Don't use a source template" }]} ariaLabel="Source template" /></FormField>
          </Container>
          <Container header={<Header variant="h2">Application and OS Images (Amazon Machine Image)</Header>}>
            <FormField label="Amazon Machine Image (AMI)">
              <Select selectedOption={amiId ? opt(amiId) : { value: "", label: "Don't include in launch template" }} onChange={({ detail }) => setAmiId(detail.selectedOption.value)}
                options={[{ value: "", label: "Don't include in launch template" }, ...(cat.data?.images || []).map((i) => ({ value: i.imageId, label: `${i.name} (${i.imageId})` }))]} ariaLabel="Amazon Machine Image (AMI)" />
            </FormField>
          </Container>
          <Container header={<Header variant="h2">Instance type</Header>}>
            <FormField label="Instance type">
              <Select selectedOption={instanceType ? opt(instanceType) : { value: "", label: "Don't include in launch template" }} onChange={({ detail }) => setInstanceType(detail.selectedOption.value)}
                options={[{ value: "", label: "Don't include in launch template" }, ...(cat.data?.types || []).map((t) => opt(t.InstanceType))]} ariaLabel="Instance type" />
            </FormField>
          </Container>
          <Container header={<Header variant="h2">Key pair (login)</Header>}>
            <FormField label="Key pair name" secondaryControl={<Button href={href("ec2", "create-key-pair")} onFollow={follow}>Create new key pair</Button>}>
              <Select selectedOption={keyName ? opt(keyName) : { value: "", label: "Don't include in launch template" }} onChange={({ detail }) => setKeyName(detail.selectedOption.value)}
                options={[{ value: "", label: "Don't include in launch template" }, ...(cat.data?.keyPairs || []).map((k) => opt(k.keyName))]} ariaLabel="Key pair name" />
            </FormField>
          </Container>
          <Container header={<Header variant="h2">Network settings</Header>}>
            <SpaceBetween size="l">
              <FormField label="Subnet">
                <Select selectedOption={subnetId ? opt(subnetId) : { value: "", label: "Don't include in launch template" }} onChange={({ detail }) => setSubnetId(detail.selectedOption.value)}
                  options={[{ value: "", label: "Don't include in launch template" }, ...(cat.data?.subnets || []).map((s) => ({ value: s.subnetId, label: `${s.subnetId} (${s.availabilityZone})` }))]} ariaLabel="Subnet" />
              </FormField>
              <FormField label="Firewall (security groups)">
                <RadioGroup value={firewall} onChange={({ detail }) => setFirewall(detail.value)} items={[{ value: "existing", label: "Select existing security group" }, { value: "create", label: "Create security group" }]} />
              </FormField>
              <FormField label="Security groups" secondaryControl={<Button onClick={() => navigate("ec2", "compare-security-group-rules")}>Compare security group rules</Button>}>
                <Select selectedOption={sgId ? opt(sgId) : null} onChange={({ detail }) => setSgId(detail.selectedOption.value)} placeholder="Select security groups"
                  options={(cat.data?.sgs || []).map((g) => ({ value: g.GroupId, label: `${g.GroupName} (${g.GroupId})` }))} ariaLabel="Security groups" />
              </FormField>
              <FormField label="Advanced network configuration">
                <SpaceBetween size="xs">
                  <Button onClick={() => setEniNote(true)}>Add network interface</Button>
                  {eniNote && <Box variant="small" color="text-body-secondary">Additional network interfaces aren't included in templates created by Vyomi — the template launches with its default primary interface only.</Box>}
                </SpaceBetween>
              </FormField>
            </SpaceBetween>
          </Container>
          <Container header={<Header variant="h2">Storage (volumes)</Header>}>
            <SpaceBetween size="s">
              {extraVolumes.map((v, idx) => (
                <SpaceBetween key={idx} direction="horizontal" size="xs">
                  <Input type="number" value={v.size} onChange={({ detail }) => setExtraVolumes((xs) => xs.map((x, i) => (i === idx ? { ...x, size: detail.value } : x)))} ariaLabel={`Volume ${idx + 2} size`} />
                  <Select selectedOption={opt(v.type)} onChange={({ detail }) => setExtraVolumes((xs) => xs.map((x, i) => (i === idx ? { ...x, type: detail.selectedOption.value } : x)))} options={["gp3", "gp2"].map(opt)} ariaLabel={`Volume ${idx + 2} type`} />
                  <Button iconName="close" ariaLabel="Remove volume" onClick={() => setExtraVolumes((xs) => xs.filter((_, i) => i !== idx))} />
                </SpaceBetween>
              ))}
              <Button onClick={() => setExtraVolumes((xs) => [...xs, { size: "8", type: "gp3" }])}>Add new volume</Button>
            </SpaceBetween>
          </Container>
          <Container header={<Header variant="h2" description="Tags applied to instances launched from this template.">Resource tags</Header>}>
            <TagEditor tags={resourceTags} onChange={({ detail }) => setResourceTags(detail.tags)} i18nStrings={TAG_I18N} />
          </Container>
          <Container header={<Header variant="h2">Advanced details</Header>}>
            <SpaceBetween size="l">
              <FormField label="IAM instance profile" secondaryControl={<Button onClick={() => navigate("ec2", "create-iam-profile")}>Create new IAM profile</Button>}>
                <Input value={iamProfile} onChange={({ detail }) => setIamProfile(detail.value)} placeholder="Don't include in launch template" ariaLabel="IAM instance profile" />
              </FormField>
              <FormField label="Shutdown behavior">
                <Select selectedOption={shutdownBehavior ? opt(shutdownBehavior) : { value: "", label: "Don't include in launch template" }} onChange={({ detail }) => setShutdownBehavior(detail.selectedOption.value)}
                  options={[{ value: "", label: "Don't include in launch template" }, opt("stop"), opt("terminate")]} ariaLabel="Shutdown behavior" />
              </FormField>
              <FormField label="Termination protection">
                <Select selectedOption={opt(termProtect || "Don't include in launch template")} onChange={({ detail }) => setTermProtect(detail.selectedOption.value)} options={["Don't include in launch template", "Enable", "Disable"].map(opt)} ariaLabel="Termination protection" />
              </FormField>
              <FormField label="User data"><Textarea value={userData} onChange={({ detail }) => setUserData(detail.value)} ariaLabel="User data" /></FormField>
            </SpaceBetween>
          </Container>
          <Container header={<Header variant="h2">Summary</Header>}>
            <SpaceBetween size="l">
              <div>Software Image (AMI): {cat.data?.images.find((i) => i.imageId === amiId)?.name || "-"}</div>
              <div>Virtual server type (instance type): {instanceType || "-"}</div>
              <div>Firewall (security group): {sgId || "-"}</div>
              <div>Storage (volumes): root volume only</div>
              <Button formAction="none" href={href("ec2", "launch-templates")} onFollow={follow}>Cancel</Button>
            </SpaceBetween>
          </Container>
        </SpaceBetween>
      </Form>
    </ContentLayout>
  );
}
