/* A portal-style blade: a full-height panel anchored right over a scrim. level 2 stacks above a level-1 blade (picker over wizard). */
import "./pickers.css";
import { Button } from "@fluentui/react-components";
import { Dismiss24Regular } from "@fluentui/react-icons";

export default function Blade({ title, subtitle, onClose, width = "min(1100px, 100vw)", level = 1, footer, children, label, testid }) {
  return (
    <div className={`vy-blade-scrim${level === 2 ? " vy-l2" : ""}`} data-testid={testid}>
      <section className="vy-pblade" style={{ width }} role="dialog" aria-label={label || title}>
        <header>
          <h1>{title}{subtitle && <p>{subtitle}</p>}</h1>
          <Button appearance="subtle" icon={<Dismiss24Regular />} aria-label="Close" onClick={onClose} />
        </header>
        <div className="vy-pbody">{children}</div>
        {footer && <footer>{footer}</footer>}
      </section>
    </div>
  );
}
