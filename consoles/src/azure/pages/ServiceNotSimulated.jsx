/* Browse blade for a service that has no v4 module yet: honest gap + the classic console. */
import { Button } from "@fluentui/react-components";
import { Glyph, NotSimulated } from "../kit/common.jsx";
import { TitleRow } from "../kit/ResourceBlade.jsx";
import { classicHref } from "../services/registry.js";
import { VyomiMark, vy } from "../../common/VyomiMark.jsx";

export default function ServiceNotSimulated({ svc }) {
  return (
    <>
      <TitleRow title={svc.title} subtitle={vy("Vyomi simulator (default directory)")} glyph={<Glyph id={svc.icon} />} closeHref="#/" />
      <div className="vy-page">
        <NotSimulated feature={`The v4 ${svc.title} blade`}
          note={<><VyomiMark /> simulates {svc.title} ({svc.type}); its page has not moved to the v4 portal lens yet. Use the classic console meanwhile.</>} />
        <Button as="a" href={classicHref()} appearance="primary" style={{ marginTop: 12 }}><span>Open {svc.title} in the classic <VyomiMark /> console</span></Button>
      </div>
    </>
  );
}
