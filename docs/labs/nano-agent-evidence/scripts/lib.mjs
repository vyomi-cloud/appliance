import { chromium } from "/Users/sudhirganti/Applications/simulator/appliance-v4nightaws/.ci-node/node_modules/playwright/index.mjs";
export const SP="/private/tmp/claude-501/-Users-sudhirganti-Applications-simulator-appliance-integF-packaging-tunnel/808d2878-fee3-409c-8be9-52dbc4c4b641/scratchpad";
export async function launch(profile){
  return chromium.launchPersistentContext(profile,{executablePath:"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",headless:false,viewport:{width:1400,height:900},args:["--headless=new","--enable-unsafe-webgpu","--use-angle=metal"],ignoreDefaultArgs:["--headless"]});
}
