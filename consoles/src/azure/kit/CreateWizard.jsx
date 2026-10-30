/* The portal's create experience: tabbed wizard (Basics, Advanced, …, Tags, Review + create)
 * with the sticky Previous / Next / "Review + create" footer. Moving to "Review + create"
 * runs validation; "Create" calls the service's native create. */
import { useState } from "react";
import { Button, MessageBar, MessageBarBody, MessageBarTitle, Tab, TabList } from "@fluentui/react-components";
import { TitleRow } from "./ResourceBlade.jsx";

export const REVIEW = "review";

export function FormSection({ title, description, children }) {
  return (
    <section className="vy-form-section">
      {title && <h3>{title}</h3>}
      {description && <p>{description}</p>}
      {children}
    </section>
  );
}

/** One label + control row (portal forms are two-column: label left, control right). */
export function FormRow({ label, required, htmlFor, children, info }) {
  return (
    <div className="vy-form-row">
      <label htmlFor={htmlFor} className={required ? "req" : undefined} title={info}>{label}</label>
      <div>{children}</div>
    </div>
  );
}

/** tabs: [{id, label, content, validate?() → string[]}] ; the Review + create tab is appended. */
export default function CreateWizard({ title, subtitle, closeHref, glyph, tabs, review, onCreate, reviewLabel = "Review + create" }) {
  const all = [...tabs, { id: REVIEW, label: reviewLabel }];
  const [tab, setTab] = useState(all[0].id);
  const [errors, setErrors] = useState([]);
  const [busy, setBusy] = useState(false);
  const idx = all.findIndex((t) => t.id === tab);
  const validate = () => tabs.flatMap((t) => (t.validate ? t.validate() : []).map((m) => `${t.label}: ${m}`));
  const go = (id) => {
    if (id === REVIEW) setErrors(validate());
    setTab(id);
  };
  const create = async () => {
    const errs = validate();
    setErrors(errs);
    if (errs.length) return;
    setBusy(true);
    try { await onCreate(); } finally { setBusy(false); }
  };
  return (
    <div className="vy-wizard">
      <TitleRow title={title} subtitle={subtitle} glyph={glyph} closeHref={closeHref} />
      <div className="vy-wizard-body">
        <TabList selectedValue={tab} onTabSelect={(_, d) => go(d.value)} aria-label={`${title} steps`}>
          {all.map((t) => <Tab key={t.id} value={t.id}>{t.label}</Tab>)}
        </TabList>
        {tab === REVIEW ? (
          <div className="vy-review">
            {errors.length > 0 ? (
              <MessageBar intent="error"><MessageBarBody><MessageBarTitle>Validation failed.</MessageBarTitle>
                <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{errors.map((e) => <li key={e}>{e}</li>)}</ul></MessageBarBody></MessageBar>
            ) : (
              <MessageBar intent="success"><MessageBarBody><MessageBarTitle>Validation passed</MessageBarTitle></MessageBarBody></MessageBar>
            )}
            {review()}
          </div>
        ) : all[idx].content}
      </div>
      <div className="vy-wizard-foot">
        {tab === REVIEW ? (
          <>
            <Button onClick={() => go(all[idx - 1].id)}>Previous</Button>
            <Button disabled>Next</Button>
            <Button appearance="primary" disabled={busy || errors.length > 0} onClick={create}>{busy ? "Creating..." : "Create"}</Button>
          </>
        ) : (
          <>
            <Button disabled={idx === 0} onClick={() => go(all[idx - 1].id)}>Previous</Button>
            <Button onClick={() => go(all[idx + 1].id)}>Next</Button>
            <Button appearance="primary" onClick={() => go(REVIEW)}>{reviewLabel}</Button>
          </>
        )}
      </div>
    </div>
  );
}
