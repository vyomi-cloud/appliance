/* A header action that is honest about not being backed by a Vyomi core: clicking it opens
 * a modal disclosing the gap, instead of either doing nothing (a dead control) or faking a
 * save. Use only for minor, one-off actions inside an otherwise-real page/section — a whole
 * unimplemented section should be <NotSimulatedContainer> instead. */
import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import Modal from "@cloudscape-design/components/modal";
import Box from "@cloudscape-design/components/box";
import { NotSimulated } from "../../kit/common.jsx";

export default function GapButton({ text, feature, note, variant }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant={variant} onClick={() => setOpen(true)}>{text}</Button>
      <Modal visible={open} onDismiss={() => setOpen(false)} header={text} footer={<Box float="right"><Button onClick={() => setOpen(false)}>Close</Button></Box>}>
        <NotSimulated feature={feature || text} note={note} />
      </Modal>
    </>
  );
}
