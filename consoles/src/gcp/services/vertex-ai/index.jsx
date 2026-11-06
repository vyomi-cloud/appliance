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
import { Dashboard, ModelGarden, Endpoints, EndpointDetail, Models, Datasets, Training, Pipelines, Batch, Workbench, VectorSearch, FeatureStore, Experiments } from "./Pages.jsx";

export default {
  nav: [
    { text: "Dashboard", href: "#/vertex-ai", icon: DashboardIcon },
    { text: "Model Garden", href: "#/vertex-ai/model-garden", icon: WidgetsIcon },
    { text: "Vertex AI Studio", href: "#/vertex-ai/studio", icon: AutoAwesomeIcon },
    { text: "Endpoints", href: "#/vertex-ai/endpoints", icon: CableIcon, match: ["#/vertex-ai/endpoints/"] },
    { text: "Model Registry", href: "#/vertex-ai/models", icon: HubIcon },
    { text: "Datasets", href: "#/vertex-ai/datasets", icon: StorageIcon },
    { text: "Training", href: "#/vertex-ai/training", icon: ModelTrainingIcon },
    { text: "Pipelines", href: "#/vertex-ai/pipelines", icon: AccountTreeIcon },
    { text: "Batch predictions", href: "#/vertex-ai/batch", icon: PlaylistPlayIcon },
    { text: "Workbench", href: "#/vertex-ai/workbench", icon: TerminalIcon },
    { text: "Vector Search", href: "#/vertex-ai/vector-search", icon: SearchIcon },
    { text: "Feature Store", href: "#/vertex-ai/feature-store", icon: StorageIcon },
    { text: "Experiments", href: "#/vertex-ai/experiments", icon: ScienceIcon },
  ],
  routes: [
    { pattern: "/vertex-ai", component: Dashboard },
    { pattern: "/vertex-ai/model-garden", component: ModelGarden },
    { pattern: "/vertex-ai/studio", component: Studio },
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
