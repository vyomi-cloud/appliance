/* Console Home: recently visited services + all services by category. */
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Link from "@cloudscape-design/components/link";
import Box from "@cloudscape-design/components/box";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Badge from "@cloudscape-design/components/badge";
import { CATEGORIES, SERVICES } from "../services/registry.js";
import { follow } from "../../common/router.js";
import { getRegion } from "../../common/wire.js";

export default function Home() {
  return (
    <ContentLayout header={<Header variant="h1" description={`Region ${getRegion()} · backed by your local Vyomi simulator`}>Console Home</Header>}>
      <SpaceBetween size="l">
        {CATEGORIES.map((cat) => {
          const svcs = SERVICES.filter((s) => s.category === cat);
          if (!svcs.length) return null;
          return (
            <Container key={cat} header={<Header variant="h2">{cat}</Header>}>
              <ColumnLayout columns={3} variant="text-grid">
                {svcs.map((s) => (
                  <div key={s.id}>
                    <SpaceBetween direction="horizontal" size="xs">
                      <Link href={`#/${s.id}`} onFollow={follow} fontSize="heading-s">{s.title}</Link>
                      {!s.load && <Badge>classic</Badge>}
                    </SpaceBetween>
                    <Box variant="small" color="text-body-secondary">{s.description}</Box>
                  </div>
                ))}
              </ColumnLayout>
            </Container>
          );
        })}
      </SpaceBetween>
    </ContentLayout>
  );
}
