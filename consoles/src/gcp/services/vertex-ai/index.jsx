import DashboardIcon from "@mui/icons-material/esm/Dashboard.js";
import WidgetsIcon from "@mui/icons-material/esm/Widgets.js";
import AutoAwesomeIcon from "@mui/icons-material/esm/AutoAwesomeOutlined.js";
import HubIcon from "@mui/icons-material/esm/Hub.js";
import ModelTrainingIcon from "@mui/icons-material/esm/ModelTraining.js";
import StorageIcon from "@mui/icons-material/esm/Storage.js";
import AccountTreeIcon from "@mui/icons-material/esm/AccountTree.js";
import PlaylistPlayIcon from "@mui/icons-material/esm/PlaylistPlay.js";
import TerminalIcon from "@mui/icons-material/esm/Terminal.js";
import SearchIcon from "@mui/icons-material/esm/Search.js";
import ScienceIcon from "@mui/icons-material/esm/Science.js";
import CableIcon from "@mui/icons-material/esm/Cable.js";
import Studio from "./Studio.jsx";
import { Overview, AgentStudio, AgentGarden, Tutorials, Deployments } from "./AgentPages.jsx";
import { ModelGarden, ModelDetail } from "./GardenPages.jsx";
import SchoolIcon from "@mui/icons-material/esm/School.js";
import AgentIcon from "@mui/icons-material/esm/SmartToyOutlined.js";
import BarChartIcon from "@mui/icons-material/esm/BarChart.js";
import TuneIcon from "@mui/icons-material/esm/Tune.js";
import LightbulbIcon from "@mui/icons-material/esm/LightbulbOutlined.js";
import MemoryIcon from "@mui/icons-material/esm/Memory.js";
import PolicyIcon from "@mui/icons-material/esm/PolicyOutlined.js";
import SecurityIcon from "@mui/icons-material/esm/SecurityOutlined.js";
import GppIcon from "@mui/icons-material/esm/GppGoodOutlined.js";
import SpokeIcon from "@mui/icons-material/esm/Hub.js";
import ChatIcon from "@mui/icons-material/esm/ForumOutlined.js";
import ExtensionIcon from "@mui/icons-material/esm/ExtensionOutlined.js";
import DescriptionIcon from "@mui/icons-material/esm/DescriptionOutlined.js";
import CodeIcon from "@mui/icons-material/esm/Code.js";
import { Endpoints, EndpointDetail, Models, Datasets, Training, Pipelines, Batch, Workbench, VectorSearch, FeatureStore, Experiments } from "./Pages.jsx";

const B = "#/vertex-ai";
const MODEL_PATHS = ["/vertex-ai/model-garden", "/vertex-ai/models", "/vertex-ai/endpoints", "/vertex-ai/batch", "/vertex-ai/datasets", "/vertex-ai/feature-store", "/vertex-ai/experiments", "/vertex-ai/training", "/vertex-ai/pipelines", "/vertex-ai/evaluation", "/vertex-ai/provisioned-throughput", "/vertex-ai/metadata", "/vertex-ai/monitoring", "/vertex-ai/ray", "/vertex-ai/claude-models"];
const AGENT_PATHS = ["/vertex-ai/agent-garden", "/vertex-ai/adk", "/vertex-ai/mcp-servers", "/vertex-ai/rag-engine", "/vertex-ai/vector-search", "/vertex-ai/search", "/vertex-ai/agent-retrieval", "/vertex-ai/deployments", "/vertex-ai/memory-bank", "/vertex-ai/sessions", "/vertex-ai/agent-registry", "/vertex-ai/policies", "/vertex-ai/gateways", "/vertex-ai/security", "/vertex-ai/topology"];
const under = (path, list) => list.some((p) => path === p || path.startsWith(p + "/"));
const TUTORIALS = { text: "Tutorials", href: `${B}/tutorials`, icon: SchoolIcon, pinned: true };

const TOP = [
  { text: "Overview", href: B, icon: DashboardIcon },
  { text: "Studio", href: `${B}/studio`, icon: AutoAwesomeIcon, match: [`${B}/studio/`] },
  { text: "Models", href: `${B}/model-garden`, icon: WidgetsIcon, chevron: true },
  { text: "Agents", href: `${B}/agent-garden`, icon: AgentIcon, chevron: true },
  { text: "Notebooks", href: `${B}/workbench`, icon: TerminalIcon, chevron: true },
  TUTORIALS,
];
const MODELS = [
  { back: { text: "Models", href: B } },
  { text: "Model Garden", href: `${B}/model-garden`, icon: WidgetsIcon, match: [`${B}/model-garden/`] },
  { text: "Tuning", href: `${B}/training?tab=tuning`, icon: TuneIcon },
  { text: "Evaluation", href: `${B}/evaluation`, icon: BarChartIcon },
  { text: "Model Registry", href: `${B}/models`, icon: LightbulbIcon },
  { text: "Endpoints", href: `${B}/endpoints`, icon: CableIcon, match: [`${B}/endpoints/`] },
  { text: "Batch Inference", href: `${B}/batch`, icon: PlaylistPlayIcon },
  { text: "Provisioned Throughput", href: `${B}/provisioned-throughput`, icon: MemoryIcon },
  { section: "Partner services", collapsible: true, items: [{ text: "Claude models", href: `${B}/claude-models`, icon: AutoAwesomeIcon }] },
  { section: "More services", collapsible: true, items: [
    { text: "Datasets", href: `${B}/datasets`, icon: StorageIcon }, { text: "Feature Store", href: `${B}/feature-store`, icon: StorageIcon },
    { text: "Experiments", href: `${B}/experiments`, icon: ScienceIcon }, { text: "Training", href: `${B}/training`, icon: ModelTrainingIcon },
    { text: "Ray on Agent Platform", href: `${B}/ray`, icon: SpokeIcon }, { text: "Pipelines", href: `${B}/pipelines`, icon: AccountTreeIcon },
    { text: "Metadata", href: `${B}/metadata`, icon: DescriptionIcon }, { text: "Monitoring", href: `${B}/monitoring`, icon: BarChartIcon }] },
  TUTORIALS,
];
const AGENTS = [
  { back: { text: "Agents", href: B } },
  { button: { text: "New agent", href: `${B}/agent-garden` } },
  { section: "Build", collapsible: true, items: [
    { text: "Agent Garden", href: `${B}/agent-garden`, icon: AgentIcon }, { text: "ADK", href: `${B}/adk`, icon: CodeIcon },
    { text: "MCP Servers", href: `${B}/mcp-servers`, icon: ExtensionIcon }, { text: "RAG Engine", href: `${B}/rag-engine`, icon: SearchIcon },
    { text: "Vector Search", href: `${B}/vector-search`, icon: SpokeIcon }, { text: "Search", href: `${B}/search`, icon: SearchIcon },
    { text: "Agent Retrieval", href: `${B}/agent-retrieval`, icon: AgentIcon }] },
  { section: "Scale", collapsible: true, items: [
    { text: "Deployments", href: `${B}/deployments`, icon: HubIcon }, { text: "Memory Bank", href: `${B}/memory-bank`, icon: StorageIcon }, { text: "Sessions", href: `${B}/sessions`, icon: ChatIcon }] },
  { section: "Govern", collapsible: true, items: [
    { text: "Agent Registry", href: `${B}/agent-registry`, icon: StorageIcon }, { text: "Policies", href: `${B}/policies`, icon: PolicyIcon },
    { text: "Gateways", href: `${B}/gateways`, icon: CableIcon }, { text: "Security", href: `${B}/security`, icon: SecurityIcon }, { text: "Topology", href: `${B}/topology`, icon: GppIcon }] },
  { section: "Optimize", collapsible: true, items: [{ text: "Evaluation", href: `${B}/evaluation`, icon: BarChartIcon }] },
  TUTORIALS,
];
const NOTEBOOKS = [{ back: { text: "Notebooks", href: B } }, { text: "Workbench", href: `${B}/workbench`, icon: TerminalIcon }, TUTORIALS];

/** Product nav depends on the route, like the native console: top level, then Models / Agents / Notebooks drill-ins. */
function nav(path) {
  if (path === "/vertex-ai/studio" || path.startsWith("/vertex-ai/app-builder")) return null;   // Studio has its own rail
  if (under(path, AGENT_PATHS)) return AGENTS;
  if (under(path, MODEL_PATHS)) return MODELS;
  if (path.startsWith("/vertex-ai/workbench")) return NOTEBOOKS;
  return TOP;
}

export default {
  nav,
  routes: [
    { pattern: "/vertex-ai", component: Overview },
    { pattern: "/vertex-ai/model-garden", component: ModelGarden },
    { pattern: "/vertex-ai/model-garden/:publisher/:id", component: ModelDetail },
    { pattern: "/vertex-ai/studio", component: AgentStudio },
    { pattern: "/vertex-ai/studio/prompt", component: Studio },
    { pattern: "/vertex-ai/tutorials", component: Tutorials },
    { pattern: "/vertex-ai/agent-garden", component: AgentGarden },
    { pattern: "/vertex-ai/deployments", component: Deployments },
    { pattern: "/vertex-ai/endpoints", component: Endpoints },
    { pattern: "/vertex-ai/endpoints/:location/:id", component: EndpointDetail },
    { pattern: "/vertex-ai/models", component: Models },
    { pattern: "/vertex-ai/datasets", component: Datasets },
    { pattern: "/vertex-ai/training", component: Training },
    { pattern: "/vertex-ai/pipelines", component: Pipelines },
    { pattern: "/vertex-ai/batch", component: Batch },
    { pattern: "/vertex-ai/workbench", component: Workbench },
    { pattern: "/vertex-ai/vector-search", component: VectorSearch },
    { pattern: "/vertex-ai/feature-store", component: FeatureStore },
    { pattern: "/vertex-ai/experiments", component: Experiments },
  ],
};
