/* Step 1 of "Create instance": pick the database engine, then go to the full form. */
import { Box, Button, Stack, Typography } from "@mui/material";
import { PageHeader, Section } from "../../kit/common.jsx";

const ENGINES = [["MySQL", "MYSQL"], ["PostgreSQL", "POSTGRES"], ["SQL Server", "SQLSERVER"]];

export default function ChooseEngine() {
  return (
    <Box sx={{ maxWidth: 880 }}>
      <PageHeader title="Create an instance" />
      <Section title="Choose your database engine">
        <Typography variant="body2" sx={{ fontWeight: 500, mb: 1.5 }}>Engine</Typography>
        <Stack useFlexGap direction="row" spacing={2} sx={{ flexWrap: "wrap", rowGap: 2 }}>
          {ENGINES.map(([label, v]) => (
            <Button key={v} variant="outlined" sx={{ py: 3, px: 4 }} href={`#/sql/create/instance?engine=${v}`}>Choose {label}</Button>
          ))}
        </Stack>
      </Section>
    </Box>
  );
}
