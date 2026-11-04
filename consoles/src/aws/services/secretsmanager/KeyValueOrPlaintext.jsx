/* Shared "Key/value | Plaintext" value editor — used by the Store-a-new-secret wizard's
 * "Other type of secret" step and the Edit-secret-value page. Exactly one tab's value is
 * ever submitted (whichever is selected), matching the real console. */
import SegmentedControl from "@cloudscape-design/components/segmented-control";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import Button from "@cloudscape-design/components/button";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Box from "@cloudscape-design/components/box";

export default function KeyValueOrPlaintext({ tab, setTab, pairs, setPairs, plaintext, setPlaintext }) {
  const setPair = (i, patch) => setPairs(pairs.map((p, idx) => (idx === i ? { ...p, ...patch } : p)));
  return (
    <SpaceBetween size="m">
      <SegmentedControl
        selectedId={tab}
        onChange={({ detail }) => setTab(detail.selectedId)}
        label="Key/value"
        options={[{ text: "Key/value", id: "keyvalue" }, { text: "Plaintext", id: "plaintext" }]}
      />
      {tab === "keyvalue" ? (
        <SpaceBetween size="s">
          {pairs.map((p, i) => (
            <SpaceBetween key={i} direction="horizontal" size="xs">
              <Input placeholder="key" value={p.key} onChange={({ detail }) => setPair(i, { key: detail.value })} ariaLabel="Key" />
              <Input placeholder="value" value={p.value} onChange={({ detail }) => setPair(i, { value: detail.value })} ariaLabel="Value" />
              <Button iconName="close" variant="icon" ariaLabel="Remove row" onClick={() => setPairs(pairs.filter((_, idx) => idx !== i))} />
            </SpaceBetween>
          ))}
          <Button onClick={() => setPairs([...pairs, { key: "", value: "" }])}>Add row</Button>
        </SpaceBetween>
      ) : (
        <FormField label="Plaintext" stretch>
          <Textarea rows={8} value={plaintext} onChange={({ detail }) => setPlaintext(detail.value)} placeholder='{"key":"value"}, or any plaintext string' spellcheck={false} />
        </FormField>
      )}
      <Box variant="small" color="text-body-secondary">Secrets Manager stores whichever tab you fill in as the secret's value.</Box>
    </SpaceBetween>
  );
}
