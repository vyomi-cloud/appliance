import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import { href, follow } from "../../../common/router.js";
import { KeyValue } from "../../kit/common.jsx";
import { getLayoutSettings, getExploreSettings } from "./prefs.js";

export default function Settings() {
  const [layout] = useState(getLayoutSettings);
  const [explore] = useState(getExploreSettings);
  return (
    <ContentLayout header={<Header variant="h1">Settings</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Layout and navigation settings"
          actions={<Button href={href("dynamodb", "settings", "layout")} onFollow={follow}>Edit</Button>}
          columns={3} items={[
            ["Content density", layout.density], ["Default entry page", layout.defaultEntryPage], ["Default table tab", layout.defaultTableTab],
          ]} />
        <KeyValue title="Explore items settings"
          actions={<Button href={href("dynamodb", "settings", "explore-items")} onFollow={follow}>Edit</Button>}
          columns={3} items={[
            ["Default query type", explore.defaultQueryType], ["Default item editor view", explore.defaultItemEditorView], ["Default JSON view syntax", explore.defaultJsonSyntax],
          ]} />
      </SpaceBetween>
    </ContentLayout>
  );
}
