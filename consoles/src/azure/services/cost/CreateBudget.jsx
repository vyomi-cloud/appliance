import { useEffect, useState } from "react";
import { Button, Input, Select, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow } from "@fluentui/react-components";
import { Add20Regular, Delete20Regular } from "@fluentui/react-icons";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { listResourceGroups } from "../../kit/arm.js";
import { budgetTimePeriod, putBudget, RESET_PERIOD_LABEL, RESET_PERIODS, toBudgetFilter } from "./api.js";

export default function CreateBudget() {
  const [name, setName] = useState("");
  const [resetPeriod, setResetPeriod] = useState("Monthly");
  const [amount, setAmount] = useState("100");
  const [resourceGroup, setResourceGroup] = useState("");
  const [rgs, setRgs] = useState([]);
  const [conditions, setConditions] = useState([{ type: "Actual", percent: "80", amount: "", actionGroup: "" }]);
  const [recipients, setRecipients] = useState([{ email: "" }]);
  const [language, setLanguage] = useState("Default");

  useEffect(() => { listResourceGroups().then(setRgs).catch(() => setRgs([])); }, []);

  const period = budgetTimePeriod(resetPeriod);

  const basics = (
    <>
      <FormSection title="Budget scoping">
        <FormRow label="Scope"><Input readOnly value="Vyomi subscription" aria-label="Scope" /></FormRow>
        <FormRow label="Filters">
          <Select value={resourceGroup} onChange={(_, d) => setResourceGroup(d.value)} aria-label="Filters">
            <option value="">Add filter — resource group: all</option>
            {rgs.map((rg) => <option key={rg.name} value={rg.name}>Resource group: {rg.name}</option>)}
          </Select>
        </FormRow>
      </FormSection>
      <FormSection title="Budget Details">
        <FormRow label="Name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Name" /></FormRow>
        <FormRow label="Reset period">
          <Select value={resetPeriod} onChange={(_, d) => setResetPeriod(d.value)} aria-label="Reset period">
            {RESET_PERIODS.map((p) => <option key={p} value={p}>{RESET_PERIOD_LABEL[p]}</option>)}
          </Select>
        </FormRow>
        <FormRow label="Creation date"><Input readOnly value={period.startDate.slice(0, 10)} aria-label="Creation date" /></FormRow>
        <FormRow label="Expiration date"><Input readOnly value={period.endDate.slice(0, 10)} aria-label="Expiration date" /></FormRow>
      </FormSection>
      <FormSection title="Budget Amount">
        <FormRow label="Amount" required><Input type="number" min="1" value={amount} onChange={(_, d) => setAmount(d.value)} aria-label="Amount" /></FormRow>
      </FormSection>
    </>
  );

  const update = (list, setList, i, patch) => setList(list.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  const alerts = (
    <>
      <FormSection title="Alert conditions">
        <Table size="small" aria-label="Alert conditions">
          <TableHeader><TableRow><TableHeaderCell>Type</TableHeaderCell><TableHeaderCell>% of budget</TableHeaderCell><TableHeaderCell>Amount</TableHeaderCell><TableHeaderCell>Action group</TableHeaderCell><TableHeaderCell /></TableRow></TableHeader>
          <TableBody>
            {conditions.map((c, i) => (
              <TableRow key={i}>
                <TableCell>
                  <Select value={c.type} onChange={(_, d) => update(conditions, setConditions, i, { type: d.value })} aria-label="Alert type">
                    <option>Actual</option><option>Forecasted</option>
                  </Select>
                </TableCell>
                <TableCell><Input type="number" value={c.percent} onChange={(_, d) => update(conditions, setConditions, i, { percent: d.value })} style={{ width: 80 }} aria-label="% of budget" /></TableCell>
                <TableCell>{amount && c.percent ? `$${(Number(amount) * Number(c.percent) / 100).toFixed(2)}` : "--"}</TableCell>
                <TableCell><Input value={c.actionGroup} onChange={(_, d) => update(conditions, setConditions, i, { actionGroup: d.value })} placeholder="(none)" aria-label="Action group" /></TableCell>
                <TableCell><Button icon={<Delete20Regular />} appearance="subtle" aria-label="Remove condition" onClick={() => setConditions(conditions.filter((_, j) => j !== i))} /></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <Button icon={<Add20Regular />} onClick={() => setConditions([...conditions, { type: "Actual", percent: "100", amount: "", actionGroup: "" }])}>Add a condition</Button>
      </FormSection>
      <FormSection title="Alert recipients (email)">
        <Table size="small" aria-label="Alert recipients (email)">
          <TableHeader><TableRow><TableHeaderCell>Email</TableHeaderCell><TableHeaderCell /></TableRow></TableHeader>
          <TableBody>
            {recipients.map((r, i) => (
              <TableRow key={i}>
                <TableCell><Input type="email" value={r.email} onChange={(_, d) => update(recipients, setRecipients, i, { email: d.value })} aria-label="Email" /></TableCell>
                <TableCell><Button icon={<Delete20Regular />} appearance="subtle" aria-label="Remove recipient" onClick={() => setRecipients(recipients.filter((_, j) => j !== i))} /></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <Button icon={<Add20Regular />} onClick={() => setRecipients([...recipients, { email: "" }])}>Add an email recipient</Button>
      </FormSection>
      <FormSection title="Language preference">
        <FormRow label="Language preference">
          <Select value={language} onChange={(_, d) => setLanguage(d.value)} aria-label="Language preference">
            <option>Default</option><option>English</option>
          </Select>
        </FormRow>
      </FormSection>
    </>
  );

  const notifications = () => Object.fromEntries(conditions.filter((c) => c.percent).map((c, i) => [
    `${c.type}_GreaterThan_${c.percent}_${i}`,
    { enabled: true, operator: "GreaterThan", threshold: Number(c.percent), thresholdType: c.type,
      contactEmails: recipients.map((r) => r.email).filter(Boolean), locale: language === "Default" ? "en-us" : "en-us" },
  ]));

  const body = () => ({
    properties: {
      category: "Cost", amount: Number(amount), timeGrain: resetPeriod, timePeriod: period,
      filter: toBudgetFilter(resourceGroup), notifications: notifications(),
    },
  });

  return (
    <CreateWizard title="Create budget" closeHref="#/cost/budgets"
      tabs={[
        { id: "basics", label: "Create a budget", content: basics, validate: () => (name ? [] : ["Name is required."]).concat(Number(amount) > 0 ? [] : ["Amount must be greater than 0."]) },
        { id: "alerts", label: "Set alerts", content: alerts },
      ]}
      review={() => (
        <FormSection title="Summary">
          <FormRow label="Name"><span>{name}</span></FormRow>
          <FormRow label="Scope"><span>{resourceGroup ? `Resource group: ${resourceGroup}` : "Subscription"}</span></FormRow>
          <FormRow label="Reset period"><span>{RESET_PERIOD_LABEL[resetPeriod]}</span></FormRow>
          <FormRow label="Amount"><span>${amount}</span></FormRow>
          <FormRow label="Alert conditions"><span>{conditions.length}</span></FormRow>
        </FormSection>
      )}
      onCreate={async () => { await putBudget(name, body()); location.hash = "#/cost/budgets"; }}
    />
  );
}
