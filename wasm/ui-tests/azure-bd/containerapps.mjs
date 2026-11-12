// Container Apps create wizard: Basics (name; RG/region/env default, env "Create new environment" auto-creates cae-{rg}) -> Review + create -> Create.
export default async function ({ page, name, dispatch }) {
  const box = page.getByLabel("Container app name");
  await box.waitFor({ timeout: 30000 });
  await box.fill(name);
  await dispatch(page.getByRole("button", { name: /Review \+ create/ }).first());
  await dispatch(page.getByRole("button", { name: /^Create$/ }).first());
}
